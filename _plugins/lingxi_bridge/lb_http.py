"""
LingxiBridge HTTP 客户端模块

统一所有 HTTP 请求的：
- 线程本地 Session 连接池复用（减少 TCP/TLS 握手开销，避免跨线程共享 Session）
- 指数退避重试（429 / 5xx 自动重试）
- 线程池并发上传（多张图同时上传到 RH）
"""

import time
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

HTTP_WORKERS_MIN = 16
HTTP_WORKERS_MAX = 256


# ─── 线程本地 Session（requests 连接池）─────────────────────────────────────────

_session_lock = threading.Lock()
_thread_local = threading.local()
_sessions_by_thread: dict[int, requests.Session] = {}


def _new_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=16,
        pool_maxsize=32,
        max_retries=retry,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session._lx_closed = False
    return session


def _get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is not None and not getattr(session, "_lx_closed", False):
        return session

    session = _new_session()
    _thread_local.session = session
    with _session_lock:
        _sessions_by_thread[threading.get_ident()] = session
    return session


def get_session() -> requests.Session:
    """公开别名，内部与外部统一使用这个函数获取 session。"""
    return _get_session()


def close_current_session() -> None:
    """关闭当前线程持有的 Session。"""
    session = getattr(_thread_local, "session", None)
    if session is None:
        return
    try:
        session._lx_closed = True
        session.close()
    finally:
        _thread_local.session = None
        with _session_lock:
            ident = threading.get_ident()
            if _sessions_by_thread.get(ident) is session:
                _sessions_by_thread.pop(ident, None)


def close_all_sessions() -> None:
    """关闭已登记的所有线程本地 Session，用于用户中断时尽快释放连接。"""
    with _session_lock:
        sessions = list(_sessions_by_thread.values())
        _sessions_by_thread.clear()

    for session in sessions:
        try:
            session._lx_closed = True
            session.close()
        except Exception:
            pass

    current = getattr(_thread_local, "session", None)
    if current in sessions:
        _thread_local.session = None


# ─── 线程池（用于并发上传，如 RH 多图同时上传）──────────────────────────────────

_executor: Optional[ThreadPoolExecutor] = None
_executor_workers = 0
_desired_workers = HTTP_WORKERS_MIN
_exec_lock = threading.Lock()


def _clamp_worker_count(value) -> int:
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        count = HTTP_WORKERS_MIN
    return max(HTTP_WORKERS_MIN, min(HTTP_WORKERS_MAX, count))


def auto_worker_count(concurrency: int) -> int:
    return _clamp_worker_count(max(HTTP_WORKERS_MIN, int(concurrency) * 2))


def configure_executor(max_workers: int) -> int:
    """Resize the shared HTTP executor and return the active worker count."""
    global _executor, _executor_workers, _desired_workers
    desired = _clamp_worker_count(max_workers)
    with _exec_lock:
        _desired_workers = desired
        if _executor is not None and _executor_workers == desired:
            return _executor_workers

        old_executor = _executor
        _executor = ThreadPoolExecutor(
            max_workers=desired,
            thread_name_prefix="LingxiBridge-HTTP",
        )
        _executor_workers = desired

    if old_executor is not None:
        old_executor.shutdown(wait=False, cancel_futures=False)
    print(f"[LingxiBridge] HTTP workers set to {desired}")
    return desired


def configure_executor_for_concurrency(concurrency: int) -> int:
    return configure_executor(auto_worker_count(concurrency))


def _get_executor() -> ThreadPoolExecutor:
    global _executor, _executor_workers
    if _executor is None:
        with _exec_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=_desired_workers,
                    thread_name_prefix="LingxiBridge-HTTP",
                )
                _executor_workers = _desired_workers
    return _executor


# ─── 核心请求函数 ──────────────────────────────────────────────────────────────


def _build_request_kwargs(url, session, kwargs):
    merged = dict(kwargs)
    merged.pop("url", None)
    return {
        "method": merged.pop("method", "GET"),
        "url": url,
        **merged,
    }


def http_get(url, session=None, **kwargs) -> requests.Response:
    if session is None:
        session = _get_session()
    req_kwargs = _build_request_kwargs(url, session, kwargs)
    return session.request(**req_kwargs)


def http_post(url, session=None, **kwargs) -> requests.Response:
    if session is None:
        session = _get_session()
    req_kwargs = _build_request_kwargs(url, session, kwargs)
    req_kwargs["method"] = "POST"
    return session.request(**req_kwargs)


def http_download_stream(url, session=None, timeout=120):
    if session is None:
        session = _get_session()
    t0 = time.time()
    resp = session.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()
    data = b"".join(resp.iter_content(65536))
    return data, time.time() - t0


# ─── 并发上传（线程池方式，用于 RH 多图同时上传）───────────────────────────────


def http_parallel_post(tasks):
    """
    并发执行多个 POST 请求（线程池方式）。
    用于 RH 多图同时上传，或其他需要真正并行的场景。
    所有任务必须是 POST。
    """
    executor = _get_executor()

    def _submit_one(task):
        session = _get_session()
        url = task.get("url")
        timeout = task.get("timeout", 300)
        task_kwargs = {k: v for k, v in task.items() if k not in ("url", "timeout")}
        try:
            resp = session.post(url, timeout=timeout, **task_kwargs)
            resp.raise_for_status()
            return {"success": True, "response": resp, "error": None}
        except Exception as e:
            return {"success": False, "response": None, "error": e}

    futures = [executor.submit(_submit_one, dict(t)) for t in tasks]
    return [f.result() for f in futures]
