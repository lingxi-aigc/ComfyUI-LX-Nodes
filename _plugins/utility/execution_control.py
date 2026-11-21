from __future__ import annotations

import ast
import asyncio
import ctypes
import inspect
import logging
import sys
import textwrap
import threading
from functools import lru_cache
from types import FrameType
from typing import Any


_ROUTE_MARKER = "_lx_execution_control_routes_registered"
_ROUTE_SPECS = (("POST", "/lx/execution/force-stop"),)
_EXECUTOR_GUARD_MARKER = "_lx_force_stop_executor_guard"
_force_stop_lock = threading.Lock()


def _route_table_has_any(routes: Any, specs: tuple[tuple[str, str], ...]) -> bool:
    try:
        existing = {
            (getattr(item, "method", "").upper(), getattr(item, "path", ""))
            for item in getattr(routes, "_items", [])
        }
        return any((method.upper(), path) in existing for method, path in specs)
    except Exception:
        return False


def _queue_snapshot(prompt_queue: Any) -> tuple[list[Any], list[Any]]:
    if prompt_queue is None:
        return [], []
    try:
        running, pending = prompt_queue.get_current_queue_volatile()
        return list(running or []), list(pending or [])
    except Exception:
        try:
            running, pending = prompt_queue.get_current_queue()
            return list(running or []), list(pending or [])
        except Exception:
            return [], []


def _prompt_id(item: Any) -> Any:
    try:
        return item[1]
    except Exception:
        return None


def _running_prompt_ids(prompt_queue: Any) -> set[Any]:
    running, _pending = _queue_snapshot(prompt_queue)
    return {prompt_id for item in running if (prompt_id := _prompt_id(item)) is not None}


def _node_from_queue_item(item: Any, node_id: Any) -> tuple[str | None, str | None]:
    if node_id is None:
        return None, None
    try:
        prompt = item[2]
    except Exception:
        return str(node_id), None
    if not isinstance(prompt, dict):
        return str(node_id), None

    candidates = (node_id, str(node_id))
    for candidate in candidates:
        node = prompt.get(candidate)
        if isinstance(node, dict):
            node_type = node.get("class_type")
            return str(candidate), str(node_type) if node_type is not None else None
    return str(node_id), None


def _current_node_info(server: Any, running: list[Any]) -> tuple[str | None, str | None]:
    node_id = getattr(server, "last_node_id", None)
    if node_id is None or not running:
        return None, None
    return _node_from_queue_item(running[0], node_id)


def _node_type_from_prompt(prompt: Any, node_id: Any) -> str | None:
    if not isinstance(prompt, dict) or node_id is None:
        return None
    for candidate in (node_id, str(node_id)):
        node = prompt.get(candidate)
        if isinstance(node, dict) and node.get("class_type") is not None:
            return str(node["class_type"])
    return None


def _install_prompt_executor_guard() -> bool:
    """Keep a forced exception from escaping asyncio.run and killing the worker."""
    try:
        import comfy.model_management as model_management
        import execution
    except Exception:
        return False

    executor_class = getattr(execution, "PromptExecutor", None)
    original_execute = getattr(executor_class, "execute", None)
    if executor_class is None or not callable(original_execute):
        return False
    if getattr(original_execute, _EXECUTOR_GUARD_MARKER, False):
        return True

    def guarded_execute(executor, prompt, prompt_id, *args, **kwargs):
        executor.history_result = {"outputs": {}, "meta": {}}
        try:
            return original_execute(executor, prompt, prompt_id, *args, **kwargs)
        except model_management.InterruptProcessingException:
            executor.success = False
            server = getattr(executor, "server", None)
            node_id = getattr(server, "last_node_id", None)
            node_type = _node_type_from_prompt(prompt, node_id)
            message = {
                "prompt_id": prompt_id,
                "node_id": node_id,
                "node_type": node_type,
                "executed": [],
                "forced": True,
            }
            try:
                already_reported = any(
                    event == "execution_interrupted"
                    and isinstance(payload, dict)
                    and payload.get("prompt_id") == prompt_id
                    for event, payload in getattr(executor, "status_messages", [])
                )
                if not already_reported:
                    executor.add_message("execution_interrupted", message, broadcast=True)
            except Exception:
                logging.exception("[LX Force Stop] Failed to report forced interruption")
            try:
                model_management.interrupt_current_processing(False)
            except Exception:
                pass
            if server is not None:
                server.last_node_id = None
            logging.warning(
                "[LX Force Stop] Recovered prompt worker after an outer forced interruption "
                "for prompt %s at node %s (%s)",
                prompt_id,
                node_id,
                node_type,
            )
            return None

    setattr(guarded_execute, _EXECUTOR_GUARD_MARKER, True)
    setattr(guarded_execute, "_lx_original_execute", original_execute)
    executor_class.execute = guarded_execute
    return True


def _walk_frames(frame: FrameType | None):
    while frame is not None:
        yield frame
        frame = frame.f_back


def _exception_name(node: ast.expr | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _exception_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Tuple):
        return ",".join(_exception_name(item) for item in node.elts)
    return ""


@lru_cache(maxsize=16)
def _interrupt_catch_ranges(code: Any) -> tuple[tuple[int, int], ...]:
    """Return source ranges protected by an InterruptProcessingException handler."""
    try:
        source_lines, start_line = inspect.getsourcelines(code)
        tree = ast.parse(textwrap.dedent("".join(source_lines)))
    except Exception:
        return ()

    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handles_interrupt = any(
            "InterruptProcessingException" in _exception_name(handler.type)
            for handler in node.handlers
        )
        if not handles_interrupt or not node.body:
            continue
        first = node.body[0]
        last = node.body[-1]
        end_lineno = getattr(last, "end_lineno", last.lineno)
        ranges.append(
            (
                start_line + first.lineno - 1,
                start_line + end_lineno - 1,
            )
        )
    return tuple(ranges)


def _frame_is_safely_interruptible(frame: FrameType) -> bool:
    return any(start <= frame.f_lineno <= end for start, end in _interrupt_catch_ranges(frame.f_code))


def _locate_prompt_worker(
    prompt_queue: Any,
    target_prompt_ids: set[Any],
) -> dict[str, Any]:
    """Locate the active prompt worker and a ComfyUI exception-safe execution frame."""
    worker_found = False
    best_node_id: str | None = None
    best_node_type: str | None = None

    for thread_id, top_frame in sys._current_frames().items():
        frames = list(_walk_frames(top_frame))
        is_prompt_worker = any(
            frame.f_code.co_name == "prompt_worker"
            and frame.f_locals.get("q") is prompt_queue
            for frame in frames
        )
        if not is_prompt_worker:
            continue

        worker_found = True
        for frame in frames:
            frame_prompt_id = frame.f_locals.get("prompt_id")
            if frame_prompt_id not in target_prompt_ids:
                continue

            if "unique_id" in frame.f_locals and "class_type" in frame.f_locals:
                node_id = frame.f_locals.get("unique_id")
                node_type = frame.f_locals.get("class_type")
                best_node_id = str(node_id) if node_id is not None else best_node_id
                best_node_type = str(node_type) if node_type is not None else best_node_type

            if _frame_is_safely_interruptible(frame):
                return {
                    "thread_id": thread_id,
                    "safe": True,
                    "node_id": best_node_id,
                    "node_type": best_node_type,
                    "reason": None,
                }

    return {
        "thread_id": None,
        "safe": False,
        "node_id": best_node_id,
        "node_type": best_node_type,
        "reason": "unsafe_frame" if worker_found else "worker_not_found",
    }


def _inject_interrupt(thread_id: int) -> tuple[bool, str | None]:
    try:
        import comfy.model_management as model_management

        exception_type = model_management.InterruptProcessingException
        setter = ctypes.pythonapi.PyThreadState_SetAsyncExc
        setter.argtypes = (ctypes.c_ulong, ctypes.py_object)
        setter.restype = ctypes.c_int
        result = setter(ctypes.c_ulong(thread_id), ctypes.py_object(exception_type))
    except Exception as exc:
        return False, f"inject_failed: {exc}"

    if result == 1:
        return True, None
    if result > 1:
        try:
            clearer = ctypes.PYFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)(
                ("PyThreadState_SetAsyncExc", ctypes.pythonapi)
            )
            clearer(ctypes.c_ulong(thread_id), None)
        except Exception:
            pass
        return False, "inject_affected_multiple_threads"
    return False, "worker_thread_disappeared"


def _try_known_cancel_adapter(node_id: str | None, node_type: str | None) -> str | None:
    """Use a node's own cancellation state before escalating to thread interruption."""
    if node_id is None or node_type != "Nui.OpenPoseEditor":
        return None

    for module_name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        try:
            module_file = str(getattr(module, "__file__", "") or "")
            if "openpose" not in module_name.lower() and "openpose" not in module_file.lower():
                continue
            mappings = getattr(module, "NODE_CLASS_MAPPINGS", None)
            paused_nodes = getattr(module, "PAUSED_NODES", None)
            if not isinstance(mappings, dict) or "Nui.OpenPoseEditor" not in mappings:
                continue
            if not isinstance(paused_nodes, dict) or node_id not in paused_nodes:
                continue
            paused_nodes[node_id] = {"status": "cancel"}
            return "Nui.OpenPoseEditor"
        except Exception:
            continue
    return None


def _dispatch_native_interrupt(prompt_queue: Any, running: list[Any]) -> bool:
    dispatched = False
    interrupt_if_running = getattr(prompt_queue, "interrupt_if_running", None)
    if callable(interrupt_if_running):
        for item in running:
            prompt_id = _prompt_id(item)
            if prompt_id is not None:
                try:
                    dispatched = bool(interrupt_if_running(prompt_id)) or dispatched
                except Exception:
                    pass
        if dispatched:
            return True

    try:
        import nodes

        nodes.interrupt_processing()
        return True
    except Exception:
        return dispatched


async def _wait_for_prompts_to_exit(
    prompt_queue: Any,
    target_prompt_ids: set[Any],
    timeout_ms: int,
) -> bool:
    if not target_prompt_ids:
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0, timeout_ms) / 1000.0
    while True:
        if target_prompt_ids.isdisjoint(_running_prompt_ids(prompt_queue)):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.1)


def _clamp_ms(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _result_message(
    *,
    had_running: bool,
    stopped: bool,
    mode: str,
    cleared_pending: int,
    node_id: str | None,
    node_type: str | None,
    failure_reason: str | None,
) -> str:
    queue_suffix = f"，并清空 {cleared_pending} 个等待任务" if cleared_pending else ""
    node_label = node_type or "当前节点"
    if node_id is not None:
        node_label = f"{node_label}（#{node_id}）"

    if not had_running:
        return f"当前没有正在运行的任务{queue_suffix}。" if cleared_pending else "当前没有正在运行的任务。"
    if stopped and mode == "forced":
        return f"已强制停止 {node_label}{queue_suffix}。"
    if stopped:
        return f"已停止 {node_label}{queue_suffix}。"

    reason_text = {
        "unsafe_frame": "当前节点处于无法安全注入异常的异步或原生调用中",
        "worker_not_found": "没有定位到 ComfyUI 工作流执行线程",
        "worker_thread_disappeared": "工作流执行线程已发生变化",
        "execution_moved": "工作流执行位置正在变化，已取消本次线程注入",
        "inject_affected_multiple_threads": "线程校验异常，已撤销强制中断",
    }.get(failure_reason, "当前节点没有响应强制中断")
    return f"{reason_text}；ComfyUI 未重启，任务仍显示为运行中{queue_suffix}。"


def register_execution_control_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as exc:
        print(f"[灵犀节点] 强制停止路由注册失败，已跳过: {exc}")
        return

    if not hasattr(PromptServer, "instance") or PromptServer.instance is None:
        print("[灵犀节点] PromptServer 尚未初始化，跳过强制停止路由注册")
        return

    server = PromptServer.instance
    routes = server.routes
    if not _install_prompt_executor_guard():
        logging.warning(
            "[LX Force Stop] PromptExecutor outer guard was not installed; "
            "thread interruption will remain limited to ComfyUI's inner protected frame."
        )
    if getattr(server, _ROUTE_MARKER, False) or _route_table_has_any(routes, _ROUTE_SPECS):
        setattr(server, _ROUTE_MARKER, True)
        return
    setattr(server, _ROUTE_MARKER, True)

    @routes.post("/lx/execution/force-stop")
    async def force_stop_execution(request):
        if not _force_stop_lock.acquire(blocking=False):
            return web.json_response(
                {"success": False, "message": "另一次强制停止仍在进行中，请稍候。"},
                status=409,
            )

        try:
            try:
                data = await request.json() if request.can_read_body else {}
            except Exception:
                data = {}

            clear_pending = bool(data.get("clear_pending", True))
            cooperative_wait_ms = _clamp_ms(data.get("cooperative_wait_ms"), 700, 100, 3000)
            forced_wait_ms = _clamp_ms(data.get("forced_wait_ms"), 1800, 300, 5000)
            allow_thread_interrupt = bool(data.get("allow_thread_interrupt", True))

            prompt_queue = getattr(server, "prompt_queue", None)
            if prompt_queue is None:
                return web.json_response(
                    {"success": False, "message": "ComfyUI 任务队列尚未初始化。"},
                    status=503,
                )

            running, pending = _queue_snapshot(prompt_queue)
            cleared_pending = len(pending) if clear_pending else 0
            if clear_pending and pending:
                prompt_queue.wipe_queue()

            target_prompt_ids = {
                prompt_id for item in running if (prompt_id := _prompt_id(item)) is not None
            }
            had_running = bool(target_prompt_ids)
            node_id, node_type = _current_node_info(server, running)

            worker_info = _locate_prompt_worker(prompt_queue, target_prompt_ids) if had_running else {}
            node_id = worker_info.get("node_id") or node_id
            node_type = worker_info.get("node_type") or node_type

            if not had_running:
                message = _result_message(
                    had_running=False,
                    stopped=True,
                    mode="idle",
                    cleared_pending=cleared_pending,
                    node_id=node_id,
                    node_type=node_type,
                    failure_reason=None,
                )
                return web.json_response(
                    {
                        "success": True,
                        "stopped": True,
                        "had_running": False,
                        "mode": "idle",
                        "cleared_pending": cleared_pending,
                        "message": message,
                    }
                )

            adapter = _try_known_cancel_adapter(node_id, node_type)
            native_dispatched = _dispatch_native_interrupt(prompt_queue, running)
            stopped = await _wait_for_prompts_to_exit(
                prompt_queue,
                target_prompt_ids,
                cooperative_wait_ms,
            )
            mode = "cooperative" if stopped else "pending"
            failure_reason = None
            injected = False

            if not stopped and allow_thread_interrupt:
                worker_info = _locate_prompt_worker(prompt_queue, target_prompt_ids)
                node_id = worker_info.get("node_id") or node_id
                node_type = worker_info.get("node_type") or node_type
                if worker_info.get("safe") and worker_info.get("thread_id") is not None:
                    # A second snapshot avoids injecting during the tiny transition
                    # between PromptExecutor.execute() and PromptQueue.task_done().
                    await asyncio.sleep(0.04)
                    stable_worker = _locate_prompt_worker(prompt_queue, target_prompt_ids)
                    same_thread = stable_worker.get("thread_id") == worker_info.get("thread_id")
                    still_running = not target_prompt_ids.isdisjoint(_running_prompt_ids(prompt_queue))
                    if stable_worker.get("safe") and same_thread and still_running:
                        injected, failure_reason = _inject_interrupt(int(worker_info["thread_id"]))
                    else:
                        failure_reason = "execution_moved"
                    if injected:
                        logging.warning(
                            "[LX Force Stop] Injected InterruptProcessingException into prompt worker "
                            "for prompt(s) %s at node %s (%s)",
                            ", ".join(str(item) for item in target_prompt_ids),
                            node_id,
                            node_type,
                        )
                        stopped = await _wait_for_prompts_to_exit(
                            prompt_queue,
                            target_prompt_ids,
                            forced_wait_ms,
                        )
                        mode = "forced" if stopped else "uninterruptible"
                        if not stopped:
                            failure_reason = "injected_but_still_running"
                    else:
                        mode = "uninterruptible"
                else:
                    mode = "uninterruptible"
                    failure_reason = worker_info.get("reason") or "unsafe_frame"
            elif not stopped:
                mode = "uninterruptible"
                failure_reason = "thread_interrupt_disabled"

            message = _result_message(
                had_running=True,
                stopped=stopped,
                mode=mode,
                cleared_pending=cleared_pending,
                node_id=node_id,
                node_type=node_type,
                failure_reason=failure_reason,
            )
            return web.json_response(
                {
                    "success": True,
                    "stopped": stopped,
                    "had_running": True,
                    "mode": mode,
                    "native_dispatched": native_dispatched,
                    "injected": injected,
                    "adapter": adapter,
                    "cleared_pending": cleared_pending,
                    "prompt_ids": [str(item) for item in target_prompt_ids],
                    "node_id": node_id,
                    "node_type": node_type,
                    "failure_reason": failure_reason,
                    "message": message,
                }
            )
        except Exception as exc:
            logging.exception("[LX Force Stop] Force-stop request failed")
            return web.json_response({"success": False, "message": str(exc)}, status=500)
        finally:
            _force_stop_lock.release()
