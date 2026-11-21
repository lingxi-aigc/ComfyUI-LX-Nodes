from __future__ import annotations

import asyncio
import gc
import threading
import time
from typing import Any

from ..categories import LX_UTILITY_CATEGORY

try:
    import psutil
except Exception:
    psutil = None


class AnyType(str):
    def __ne__(self, value: object) -> bool:
        return False


ANY = AnyType("*")
GB = 1024 ** 3
_MENU_CLEANUP_ROUTE_MARKER = "_lx_memory_cleanup_routes_registered"
_MENU_CLEANUP_ROUTE_SPECS = (("POST", "/lx/memory/cleanup"),)
_cleanup_lock = threading.Lock()


def _bytes_to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return float(value) / GB


def _format_gb(value: float | None) -> str:
    if value is None:
        return "未知"
    return f"{value:.2f} GB"


def _format_delta(value: float | None) -> str:
    if value is None:
        return "未知"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f} GB"


def _get_memory_snapshot() -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {
        "vram_free": None,
        "ram_free": None,
    }

    try:
        import comfy.model_management as model_management

        device = model_management.get_torch_device()
        vram_free = model_management.get_free_memory(device)
        snapshot["vram_free"] = _bytes_to_gb(vram_free)
    except Exception:
        pass

    try:
        if psutil is not None:
            snapshot["ram_free"] = _bytes_to_gb(psutil.virtual_memory().available)
    except Exception:
        pass

    return snapshot


def _run_cleanup(clean_cache: bool, unload_models: bool) -> list[str]:
    actions: list[str] = []

    try:
        import comfy.model_management as model_management
    except Exception:
        model_management = None

    if unload_models and model_management is not None:
        model_management.unload_all_models()
        actions.append("卸载模型")

    if clean_cache:
        if model_management is not None:
            try:
                model_management.cleanup_models()
            except Exception:
                pass
            try:
                model_management.cleanup_models_gc()
            except Exception:
                pass

        gc.collect()

        if model_management is not None:
            model_management.soft_empty_cache(force=True)

        actions.append("清理缓存")

    return actions


def _effect_label(vram_delta: float | None, ram_delta: float | None) -> str:
    deltas = [item for item in (vram_delta, ram_delta) if item is not None]
    if not deltas:
        return "已执行"
    if any(item >= 0.5 for item in deltas):
        return "已执行，有效"
    if any(item >= 0.05 for item in deltas):
        return "已执行，变化较小"
    return "已执行，无明显变化"


def _next_cleanup_count(current_count: int, cycle: int) -> int:
    return ((current_count // cycle) + 1) * cycle


def _memory_delta(before: dict[str, float | None], after: dict[str, float | None], key: str) -> float | None:
    before_value = before[key]
    after_value = after[key]
    if before_value is None or after_value is None:
        return None
    return after_value - before_value


def _build_cleanup_status(
    title: str,
    actions: list[str],
    before: dict[str, float | None],
    after: dict[str, float | None],
) -> tuple[str, dict[str, Any]]:
    vram_delta = _memory_delta(before, after, "vram_free")
    ram_delta = _memory_delta(before, after, "ram_free")
    label = _effect_label(vram_delta, ram_delta)
    action_text = "、".join(actions) or "无"

    lines = [
        f"{title}：本次{label}",
        "",
        f"清理内容：{action_text}",
        "",
        f"显存可用：{_format_gb(before['vram_free'])} -> {_format_gb(after['vram_free'])}（{_format_delta(vram_delta)}）",
        f"内存可用：{_format_gb(before['ram_free'])} -> {_format_gb(after['ram_free'])}（{_format_delta(ram_delta)}）",
    ]

    if label.endswith("变化较小") or label.endswith("无明显变化"):
        lines.extend(
            [
                "",
                "说明：当前没有明显可释放资源，或资源仍被后续节点占用。",
            ]
        )

    status = "\n".join(lines)
    return status, {
        "label": label,
        "actions": actions,
        "vram_before": before["vram_free"],
        "vram_after": after["vram_free"],
        "vram_delta": vram_delta,
        "ram_before": before["ram_free"],
        "ram_after": after["ram_free"],
        "ram_delta": ram_delta,
        "status": status,
    }


def run_memory_cleanup_now(clean_cache: bool = True, unload_models: bool = True) -> dict[str, Any]:
    with _cleanup_lock:
        before = _get_memory_snapshot()
        actions = _run_cleanup(clean_cache=clean_cache, unload_models=unload_models)
        after = _get_memory_snapshot()

    status, payload = _build_cleanup_status("彻底清理内存/显存", actions, before, after)
    payload.update(
        {
            "success": True,
            "clean_cache": clean_cache,
            "unload_models": unload_models,
            "message": status,
        }
    )
    return payload


def _route_table_has_any(routes: Any, specs: tuple[tuple[str, str], ...]) -> bool:
    try:
        existing = {
            (getattr(item, "method", "").upper(), getattr(item, "path", ""))
            for item in getattr(routes, "_items", [])
        }
        return any((method.upper(), path) in existing for method, path in specs)
    except Exception:
        return False


def _has_running_prompt(prompt_queue: Any) -> bool:
    if prompt_queue is None:
        return False
    try:
        running, _queued = prompt_queue.get_current_queue_volatile()
        return bool(running)
    except Exception:
        return False


def _schedule_native_cleanup(prompt_queue: Any, clean_cache: bool, unload_models: bool) -> bool:
    if prompt_queue is None:
        return False
    try:
        if unload_models:
            prompt_queue.set_flag("unload_models", True)
        if clean_cache:
            prompt_queue.set_flag("free_memory", True)
        return True
    except Exception:
        return False


def register_memory_cleanup_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as exc:
        print(f"[灵犀节点] 内存清理路由注册失败，跳过: {exc}")
        return

    if not hasattr(PromptServer, "instance") or PromptServer.instance is None:
        print("[灵犀节点] PromptServer 尚未初始化，跳过内存清理路由注册")
        return

    routes = PromptServer.instance.routes
    if getattr(PromptServer.instance, _MENU_CLEANUP_ROUTE_MARKER, False) or _route_table_has_any(
        routes,
        _MENU_CLEANUP_ROUTE_SPECS,
    ):
        setattr(PromptServer.instance, _MENU_CLEANUP_ROUTE_MARKER, True)
        return
    setattr(PromptServer.instance, _MENU_CLEANUP_ROUTE_MARKER, True)

    @routes.post("/lx/memory/cleanup")
    async def cleanup_memory(request):
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"success": False, "message": "invalid json payload"}, status=400)

        clean_cache = bool(data.get("clean_cache", True))
        unload_models = bool(data.get("unload_models", True))
        prompt_queue = getattr(PromptServer.instance, "prompt_queue", None)

        if _has_running_prompt(prompt_queue):
            queued = _schedule_native_cleanup(prompt_queue, clean_cache, unload_models)
            message = "当前有任务正在执行，彻底清理已排队，将在任务结束后卸载模型并释放内存/显存。"
            return web.json_response(
                {
                    "success": True,
                    "queued": queued,
                    "clean_cache": clean_cache,
                    "unload_models": unload_models,
                    "message": message,
                    "status": message,
                }
            )

        try:
            result = await asyncio.to_thread(
                run_memory_cleanup_now,
                clean_cache=clean_cache,
                unload_models=unload_models,
            )
        except Exception as exc:
            return web.json_response({"success": False, "message": str(exc)}, status=500)

        result["queued"] = False
        return web.json_response(result)


class LXMemoryRelease:
    DESCRIPTION = "按执行次数周期性释放显存缓存、系统内存和可选的已加载模型。"
    CATEGORY = LX_UTILITY_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "显存释放", "内存释放", "显存/内存释放", "memory release"]
    RETURN_TYPES = (ANY, "STRING")
    RETURN_NAMES = ("输出", "状态")
    FUNCTION = "release"
    OUTPUT_NODE = True

    _counter_lock = threading.Lock()
    _counters: dict[str, int] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "清理缓存": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "执行 Python 垃圾回收、ComfyUI 残留模型引用清理和显存缓存清理。",
                    },
                ),
                "卸载模型": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "卸载当前已加载模型。释放更彻底，但下次运行需要重新加载模型。",
                    },
                ),
                "清理周期（次）": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 100000,
                        "step": 1,
                        "display": "number",
                        "tooltip": "每次执行到本节点都会计数。1 表示每次都清理；10 表示第 10、20、30... 次执行到本节点时清理。",
                    },
                ),
            },
            "optional": {
                "触发": (ANY, {"forceInput": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    def release(
        self,
        清理缓存: bool,
        卸载模型: bool,
        触发: Any = None,
        unique_id: str | None = None,
        **kwargs,
    ):
        cycle = max(1, int(kwargs.get("清理周期（次）", 1)))
        counter_key = str(unique_id or "default")

        with self._counter_lock:
            current_count = self._counters.get(counter_key, 0) + 1
            self._counters[counter_key] = current_count

        should_cleanup = current_count % cycle == 0
        next_count = _next_cleanup_count(current_count, cycle)
        action_text = "、".join(
            item
            for item, enabled in (("清理缓存", 清理缓存), ("卸载模型", 卸载模型))
            if enabled
        ) or "无"

        if not should_cleanup:
            remaining = cycle - (current_count % cycle)
            status = "\n".join(
                [
                    "显存内存释放：本次跳过",
                    "",
                    f"累计执行：{current_count} 次",
                    f"清理周期：每 {cycle} 次清理一次",
                    f"清理内容：{action_text}",
                    "",
                    f"下次清理：第 {next_count} 次（还差 {remaining} 次）",
                ]
            )
            return {"ui": {"text": [status]}, "result": (触发, status)}

        if not 清理缓存 and not 卸载模型:
            status = "\n".join(
                [
                    "显存内存释放：未执行",
                    "",
                    f"累计执行：{current_count} 次",
                    f"清理周期：每 {cycle} 次清理一次",
                    "清理内容：无",
                    "",
                    "说明：清理缓存和卸载模型均未开启。",
                    f"下次清理：第 {next_count} 次",
                ]
            )
            return {"ui": {"text": [status]}, "result": (触发, status)}

        before = _get_memory_snapshot()
        _run_cleanup(bool(清理缓存), bool(卸载模型))
        after = _get_memory_snapshot()

        vram_before = before["vram_free"]
        vram_after = after["vram_free"]
        ram_before = before["ram_free"]
        ram_after = after["ram_free"]
        vram_delta = None if vram_before is None or vram_after is None else vram_after - vram_before
        ram_delta = None if ram_before is None or ram_after is None else ram_after - ram_before
        label = _effect_label(vram_delta, ram_delta)

        lines = [
            f"显存内存释放：本次{label}",
            "",
            f"累计执行：{current_count} 次",
            f"清理周期：每 {cycle} 次清理一次",
            f"清理内容：{action_text}",
            "",
            f"显存可用：{_format_gb(vram_before)} -> {_format_gb(vram_after)}（{_format_delta(vram_delta)}）",
            f"内存可用：{_format_gb(ram_before)} -> {_format_gb(ram_after)}（{_format_delta(ram_delta)}）",
        ]

        if label.endswith("变化较小") or label.endswith("无明显变化"):
            lines.extend(
                [
                    "",
                    "说明：当前没有明显可释放资源，或资源仍被后续节点占用。",
                ]
            )

        lines.extend(["", f"下次清理：第 {next_count} 次"])

        status = "\n".join(lines)
        return {"ui": {"text": [status]}, "result": (触发, status)}

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()
