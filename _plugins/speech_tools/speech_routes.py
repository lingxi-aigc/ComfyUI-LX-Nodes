from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from .audio_utils import decode_pcm16_base64
from .sensevoice_engine import ENGINE


ROUTE_MARKER = "_lx_speech_recognition_routes_registered"
ROUTE_SPECS = (
    ("GET", "/lx/speech/status"),
    ("POST", "/lx/speech/download"),
    ("POST", "/lx/speech/transcribe"),
)


def _route_table_has_any(routes: Any, specs: tuple[tuple[str, str], ...]) -> bool:
    try:
        existing = {
            (getattr(item, "method", "").upper(), getattr(item, "path", ""))
            for item in getattr(routes, "_items", [])
        }
        return any((method, path) in existing for method, path in specs)
    except Exception:
        return False


def _json_error(message: str, status: int = 500) -> web.Response:
    return web.json_response({"status": "error", "message": message}, status=status)


def register_routes() -> None:
    try:
        from server import PromptServer
    except Exception as exc:
        print(f"[语音识别输入] PromptServer 导入失败，跳过路由注册: {exc}")
        return

    if not hasattr(PromptServer, "instance") or PromptServer.instance is None:
        print("[语音识别输入] PromptServer 尚未初始化，跳过路由注册")
        return

    routes = PromptServer.instance.routes
    if getattr(PromptServer.instance, ROUTE_MARKER, False) or _route_table_has_any(routes, ROUTE_SPECS):
        setattr(PromptServer.instance, ROUTE_MARKER, True)
        return

    setattr(PromptServer.instance, ROUTE_MARKER, True)

    @routes.get("/lx/speech/status")
    async def speech_status(request):
        return web.json_response(ENGINE.status())

    @routes.post("/lx/speech/download")
    async def speech_download(request):
        return web.json_response(ENGINE.start_download())

    @routes.post("/lx/speech/transcribe")
    async def speech_transcribe(request):
        try:
            payload = await request.json()
        except Exception:
            return _json_error("invalid json payload", status=400)

        try:
            audio, sample_rate, duration = decode_pcm16_base64(payload)
        except Exception as exc:
            return _json_error(str(exc), status=400)

        try:
            result = await asyncio.to_thread(ENGINE.transcribe, audio, sample_rate)
            result["input_duration"] = duration
            return web.json_response(result)
        except Exception as exc:
            return _json_error(str(exc), status=500)
