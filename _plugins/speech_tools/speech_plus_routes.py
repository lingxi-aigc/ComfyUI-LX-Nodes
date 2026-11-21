from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from aiohttp import WSMsgType, web

from .audio_utils import decode_pcm16_base64
from .funasr_streaming_engine import ENGINE, format_missing_dependencies


ROUTE_MARKER = "_lx_speech_recognition_plus_routes_registered"
ROUTE_SPECS = (
    ("GET", "/lx/speech_plus/status"),
    ("POST", "/lx/speech_plus/download"),
    ("GET", "/lx/speech_plus/ws"),
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


async def _send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> None:
    if not ws.closed:
        await ws.send_json(payload)


async def _handle_ws_message(ws: web.WebSocketResponse, session, payload: dict[str, Any]) -> bool:
    message_type = str(payload.get("type") or "")

    if message_type == "start":
        await _send_json(ws, {"type": "status", "status": "LISTENING", "message": "LISTENING"})
        return True

    if message_type == "stop":
        result = await asyncio.to_thread(session.transcribe_chunk, np.zeros(0, dtype=np.float32), 16000, True)
        await _send_json(ws, {"type": "final", **result})
        await _send_json(ws, {"type": "status", "status": "READY", "message": "READY"})
        return False

    if message_type != "audio":
        await _send_json(ws, {"type": "error", "message": f"unsupported message type: {message_type}"})
        return True

    try:
        audio, sample_rate, duration = decode_pcm16_base64(payload)
    except Exception as exc:
        await _send_json(ws, {"type": "error", "message": str(exc)})
        return True

    is_final = bool(payload.get("is_final"))
    result = await asyncio.to_thread(session.transcribe_chunk, audio, sample_rate, is_final)
    await _send_json(
        ws,
        {
            "type": "final" if is_final else "partial",
            **result,
            "input_duration": duration,
        },
    )
    return not is_final


def register_routes() -> None:
    try:
        from server import PromptServer
    except Exception as exc:
        print(f"[语音识别输入Plus] PromptServer 导入失败，跳过路由注册: {exc}")
        return

    if not hasattr(PromptServer, "instance") or PromptServer.instance is None:
        print("[语音识别输入Plus] PromptServer 尚未初始化，跳过路由注册")
        return

    routes = PromptServer.instance.routes
    if getattr(PromptServer.instance, ROUTE_MARKER, False) or _route_table_has_any(routes, ROUTE_SPECS):
        setattr(PromptServer.instance, ROUTE_MARKER, True)
        return

    setattr(PromptServer.instance, ROUTE_MARKER, True)

    @routes.get("/lx/speech_plus/status")
    async def speech_plus_status(request):
        return web.json_response(ENGINE.status())

    @routes.post("/lx/speech_plus/download")
    async def speech_plus_download(request):
        return web.json_response(ENGINE.start_download())

    @routes.get("/lx/speech_plus/ws")
    async def speech_plus_ws(request):
        ws = web.WebSocketResponse(max_msg_size=2 * 1024 * 1024)
        await ws.prepare(request)

        session = None
        try:
            status = ENGINE.status()
            if status.get("missing_dependencies"):
                await _send_json(
                    ws,
                    {
                        "type": "error",
                        "message": format_missing_dependencies(status["missing_dependencies"]),
                    },
                )
                return ws

            if not status.get("model_exists"):
                await _send_json(ws, {"type": "error", "message": "streaming speech model is not downloaded"})
                return ws

            await asyncio.to_thread(ENGINE.ensure_loaded)
            session = ENGINE.create_session()
            await _send_json(ws, {"type": "ready", "status": "READY", "message": "READY"})

            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        payload = message.json()
                    except Exception:
                        await _send_json(ws, {"type": "error", "message": "invalid json payload"})
                        continue

                    keep_open = await _handle_ws_message(ws, session, payload)
                    if not keep_open:
                        break
                elif message.type == WSMsgType.ERROR:
                    break
        except Exception as exc:
            await _send_json(ws, {"type": "error", "message": str(exc)})
        finally:
            session.close() if session else None
            await ws.close()

        return ws
