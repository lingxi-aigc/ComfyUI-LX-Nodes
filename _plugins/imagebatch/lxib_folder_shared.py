"""
空文件夹通信机制

loader 遇到空文件夹项时通知 saver 提前创建，
解决 ComfyUI 的 input → output 拓扑顺序问题。
"""

import threading

_lock = threading.RLock()
_pending: list = []


def push_pending_empty_folders(folder_paths: list) -> None:
    """将需要预创建的空文件夹路径推入通信队列。"""
    with _lock:
        for p in folder_paths:
            if p and p not in _pending:
                _pending.append(p)


def pop_pending_empty_folders() -> list:
    """取出并清空所有待创建的空文件夹路径。"""
    with _lock:
        result = list(_pending)
        _pending.clear()
        return result
