"""User-scoped filesystem routes for the LX workflow library."""

import asyncio
import hashlib
from inspect import iscoroutinefunction
import json
import logging
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from uuid import uuid4

from aiohttp import web


_PREFIX = "/lx/workflow-library"
_INVALID_NAME = re.compile(r'[<>:"\\|?*\x00-\x1f]|%[0-9a-fA-F]{2}')
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
_TRASH_NAME = ".lx-workflow-library-trash"


def _parts(value, *, allow_empty=False):
    if value == "" and allow_empty:
        return ()
    if not isinstance(value, str):
        raise web.HTTPBadRequest(reason="路径格式无效")
    parts = tuple(value.split("/"))
    if any(
        not part
        or part.startswith(".")
        or part.endswith((".", " "))
        or _INVALID_NAME.search(part)
        or PureWindowsPath(part).is_reserved()
        for part in parts
    ):
        raise web.HTTPBadRequest(reason="路径或文件夹名称包含不支持的字符")
    return parts


def _name(value):
    parts = _parts(value)
    if len(parts) != 1:
        raise web.HTTPBadRequest(reason="请输入单个文件或文件夹的名称")
    return parts[0]


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _is_hidden(info):
    return bool(getattr(info, "st_file_attributes", 0) & _HIDDEN)


def _stamp(info):
    fields = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return hashlib.blake2s(repr(fields).encode("ascii"), digest_size=12).hexdigest()


def _check_stamp(data, current):
    expected = data.get("stamp")
    if expected is not None and expected != current:
        raise web.HTTPConflict(reason="工作流或文件夹已改变，请刷新后重试")


def _directory(path, *, missing_ok=False, reject_hidden=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return False
        raise web.HTTPNotFound(reason="文件夹不存在") from None
    if _is_link(info):
        raise web.HTTPForbidden(reason="工作流目录不能是链接或重解析点")
    if reject_hidden and _is_hidden(info):
        raise web.HTTPForbidden(reason="不能操作隐藏文件夹")
    if not stat.S_ISDIR(info.st_mode):
        raise web.HTTPBadRequest(reason="所选路径不是文件夹")
    return True


def _inside_directory(root, parts):
    path = root
    _directory(path)
    for part in parts:
        path = path / part
        _directory(path, reject_hidden=True)
    return path


def _new_path(parent, name, *, ignore_name=None):
    if any(
        item.name != ignore_name and item.name.casefold() == name.casefold()
        for item in parent.iterdir()
    ):
        raise web.HTTPConflict(reason="目标位置已有同名文件或文件夹")
    return parent / name


def _workflow_file(root, data):
    parts = _parts(data.get("source"))
    source = _inside_directory(root, parts[:-1]) / parts[-1]
    info = source.lstat()
    if _is_link(info):
        raise web.HTTPForbidden(reason="工作流文件不能是链接或重解析点")
    if _is_hidden(info):
        raise web.HTTPForbidden(reason="不能操作隐藏工作流文件")
    if not stat.S_ISREG(info.st_mode) or source.suffix.lower() != ".json":
        raise web.HTTPBadRequest(reason="只能操作工作流 JSON 文件")
    current = _stamp(info)
    _check_stamp(data, current)
    return source, current


def _trash_directory(root):
    storage = root.parent / _TRASH_NAME
    if not _directory(storage, missing_ok=True):
        storage.mkdir(exist_ok=True)
    _directory(storage)
    return storage


def _remove_empty_trash_entry(entry, manifest):
    try:
        manifest.unlink(missing_ok=True)
        entry.rmdir()
    except OSError:
        logging.warning("[LX Workflow Library] Could not remove an empty trash record")


def _public_root(request, user_manager, folder_paths):
    try:
        user_id = user_manager.get_request_user_id(request)
    except KeyError:
        raise web.HTTPForbidden(reason="当前用户无权访问工作流目录") from None
    directory = folder_paths.get_public_user_directory(user_id)
    if not directory:
        raise web.HTTPForbidden(reason="当前用户无权访问工作流目录")
    base = Path(os.path.abspath(folder_paths.get_user_directory()))
    user = Path(os.path.abspath(directory))
    if user.parent != base:
        raise web.HTTPForbidden(reason="工作流目录不在当前用户的存储范围内")
    root = user / "workflows"
    for directory in (*reversed(root.parents), root):
        if not _directory(directory, missing_ok=True):
            break
    return root


def _tree(root):
    if not _directory(root, missing_ok=True):
        return []
    entries = []
    pending = [root]
    while pending:
        directory = pending.pop()
        if not _directory(directory, missing_ok=True):
            continue
        try:
            children = os.scandir(directory)
        except (FileNotFoundError, NotADirectoryError):
            continue
        with children:
            for item in children:
                if item.name.startswith("."):
                    continue
                path = Path(item.path)
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if _is_link(info) or _is_hidden(info):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode) and path.suffix.lower() == ".json":
                    kind = "file"
                else:
                    continue
                entries.append({
                    "path": path.relative_to(root).as_posix(),
                    "name": item.name,
                    "type": kind,
                    "stamp": _stamp(info),
                })
    return sorted(entries, key=lambda item: (item["type"] != "directory", item["path"].casefold(), item["path"]))


async def _payload(request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(reason="请求内容必须为 JSON 对象") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(reason="请求内容必须为 JSON 对象")
    return body


def register_routes():
    import folder_paths
    from server import PromptServer

    server = getattr(PromptServer, "instance", None)
    if server is None or getattr(server, "_lx_workflow_library_routes_registered", False):
        return

    routes = server.routes

    def response(handler):
        is_async = iscoroutinefunction(handler)

        async def wrapped(request):
            try:
                data = await _payload(request) if request.method == "POST" else None
                root = _public_root(request, server.user_manager, folder_paths)
                result = handler(data, root)
                return web.json_response(await result if is_async else result)
            except web.HTTPException as error:
                return web.json_response({"error": error.reason}, status=error.status)
            except FileExistsError:
                return web.json_response({"error": "目标位置已有同名文件或文件夹"}, status=409)
            except FileNotFoundError:
                return web.json_response({"error": "工作流或文件夹不存在"}, status=404)
            except PermissionError:
                return web.json_response({"error": "没有权限操作该工作流或文件夹"}, status=403)
            except OSError:
                logging.exception("[LX Workflow Library] Filesystem operation failed")
                return web.json_response({"error": "工作流目录操作失败，请检查目录状态"}, status=500)

        return wrapped

    @routes.get(f"{_PREFIX}/tree")
    @response
    async def tree(_, root):
        return {"entries": await asyncio.to_thread(_tree, root)}

    @routes.post(f"{_PREFIX}/folder")
    @response
    def create_folder(data, root):
        parent = _parts(data.get("parent"), allow_empty=True)
        name = _name(data.get("name"))
        if not parent and not _directory(root, missing_ok=True):
            root.mkdir(parents=True, exist_ok=True)
        destination = _new_path(_inside_directory(root, parent), name)
        destination.mkdir()
        return {"path": destination.relative_to(root).as_posix()}

    @routes.post(f"{_PREFIX}/move-folder")
    @response
    def move_folder(data, root):
        source = _inside_directory(root, _parts(data.get("source")))
        target = _inside_directory(root, _parts(data.get("target"), allow_empty=True))
        current = _stamp(source.lstat())
        _check_stamp(data, current)
        if target == source or source in target.parents:
            raise web.HTTPBadRequest(reason="不能把文件夹移动到自身或其子文件夹内")
        if source.parent == target:
            return {"path": source.relative_to(root).as_posix(), "stamp": current}
        destination = _new_path(target, source.name)
        source.rename(destination)
        return {"path": destination.relative_to(root).as_posix(), "stamp": _stamp(destination.lstat())}

    @routes.post(f"{_PREFIX}/check-move")
    @response
    def check_move(data, root):
        source, current = _workflow_file(root, data)
        target = _inside_directory(root, _parts(data.get("target"), allow_empty=True))
        destination = source if source.parent == target else _new_path(target, source.name)
        return {"path": destination.relative_to(root).as_posix(), "stamp": current}

    @routes.post(f"{_PREFIX}/rename-folder")
    @response
    def rename_folder(data, root):
        source = _inside_directory(root, _parts(data.get("source")))
        name = _name(data.get("name"))
        current = _stamp(source.lstat())
        _check_stamp(data, current)
        if source.name == name:
            return {"path": source.relative_to(root).as_posix(), "stamp": current}
        destination = _new_path(source.parent, name, ignore_name=source.name)
        source.rename(destination)
        return {"path": destination.relative_to(root).as_posix(), "stamp": _stamp(destination.lstat())}

    @routes.post(f"{_PREFIX}/check-rename")
    @response
    def check_rename(data, root):
        source, current = _workflow_file(root, data)
        name = _name(data.get("name"))
        if PureWindowsPath(name).suffix.lower() != ".json":
            raise web.HTTPBadRequest(reason="工作流文件名必须以 .json 结尾")
        if source.name == name:
            return {"path": source.relative_to(root).as_posix(), "stamp": current}
        if os.name == "nt" and source.name.casefold() == name.casefold():
            raise web.HTTPConflict(reason="仅修改文件名大小写时，请先改为不同的名称")
        destination = _new_path(source.parent, name, ignore_name=source.name)
        return {"path": destination.relative_to(root).as_posix(), "stamp": current}

    @routes.post(f"{_PREFIX}/check-delete")
    @response
    def check_delete(data, root):
        source, current = _workflow_file(root, data)
        return {"path": source.relative_to(root).as_posix(), "stamp": current}

    @routes.post(f"{_PREFIX}/delete-folder")
    @response
    def delete_folder(data, root):
        source = _inside_directory(root, _parts(data.get("source")))
        _check_stamp(data, _stamp(source.lstat()))
        relative = source.relative_to(root).as_posix()
        trash_id = uuid4().hex
        entry = _trash_directory(root) / trash_id
        entry.mkdir()
        manifest = entry / "manifest.json"
        try:
            with manifest.open("x", encoding="utf-8") as output:
                json.dump({"path": relative}, output, ensure_ascii=False)
            source.rename(entry / "folder")
        except OSError:
            _remove_empty_trash_entry(entry, manifest)
            raise
        return {"path": relative, "trashId": trash_id}

    server._lx_workflow_library_routes_registered = True


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

register_routes()
