"""Speech recognition input node."""

from .speech_recognition_input import SpeechRecognitionInput
from .speech_recognition_input_plus import SpeechRecognitionInputPlus

NODE_CLASS_MAPPINGS = {
    "LX_SpeechRecognitionInput": SpeechRecognitionInput,
    "LX_SpeechRecognitionInputPlus": SpeechRecognitionInputPlus,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LX_SpeechRecognitionInput": "语音识别输入",
    "LX_SpeechRecognitionInputPlus": "语音识别输入Plus",
}

try:
    from .speech_routes import register_routes

    register_routes()
except Exception as exc:
    print(f"[语音识别输入] 路由注册失败，节点仍会加载: {exc}")

try:
    from .speech_plus_routes import register_routes as register_plus_routes

    register_plus_routes()
except Exception as exc:
    print(f"[语音识别输入Plus] 路由注册失败，节点仍会加载: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
