from __future__ import annotations

import threading
import re
from pathlib import Path
from typing import Any

import numpy as np

from .audio_utils import TARGET_SAMPLE_RATE, resample_linear


MODEL_REPO_ID = "funasr/paraformer-zh-streaming"
MODEL_SUBDIR = Path("speech") / "paraformer_zh_streaming"
REQUIRED_MODEL_FILES = (
    "am.mvn",
    "config.yaml",
    "configuration.json",
    "model.pt",
    "seg_dict",
    "tokens.json",
)

CHUNK_SIZE = [0, 10, 5]
ENCODER_CHUNK_LOOK_BACK = 4
DECODER_CHUNK_LOOK_BACK = 1
QUESTION_TAIL_RE = re.compile(
    r"(吗|么|呢|是不是|有没有|可不可以|能不能|行不行|怎么样|如何|为什么|什么|哪里|哪儿|谁|多少|几)\s*$"
)
PUNCT_RE = re.compile(r"[。！？!?，,、；;：:\s]+$")
COMMA_CUES = (
    "然后",
    "但是",
    "不过",
    "如果",
    "因为",
    "所以",
    "就是",
    "其实",
    "另外",
    "还有",
    "你现在",
    "我现在",
    "你没有",
)


def _normalize_text(text: str) -> str:
    return str(text or "").replace("\r", " ").replace("\n", " ").strip()


def _merge_overlap(left: str, right: str) -> str:
    base = _normalize_text(left)
    addition = _normalize_text(right)
    if not base:
        return addition
    if not addition:
        return base
    if addition in base:
        return base
    if base in addition:
        return addition

    max_overlap = min(len(base), len(addition))
    for size in range(max_overlap, 0, -1):
        if base[-size:] == addition[:size]:
            return base + addition[size:]

    if base[-1:].isascii() and addition[:1].isascii():
        return f"{base} {addition}"
    return base + addition


def _restore_final_punctuation(text: str) -> str:
    value = _normalize_text(text)
    if not value:
        return ""

    value = value.replace(",", "，").replace("?", "？").replace("!", "！")
    for cue in COMMA_CUES:
        value = value.replace(cue, f"，{cue}")

    value = re.sub(r"，+", "，", value)
    value = re.sub(r"^，", "", value)
    value = re.sub(r"\s*([，。！？；：、])\s*", r"\1", value)
    value = re.sub(r"([，。！？；：、])\1+", r"\1", value)
    value = PUNCT_RE.sub("", value).strip()
    if not value:
        return ""

    if QUESTION_TAIL_RE.search(value):
        return f"{value}？"
    return value


def _models_root() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.models_dir)
    except Exception:
        return Path(__file__).resolve().parents[4] / "models"


def _has_required_files(model_dir: Path) -> bool:
    return all((model_dir / filename).is_file() for filename in REQUIRED_MODEL_FILES)


def _missing_imports() -> list[str]:
    missing: list[str] = []
    checks = (
        ("huggingface_hub", "huggingface_hub"),
        ("funasr", "funasr"),
        ("torch", "torch"),
    )
    for module_name, package_name in checks:
        try:
            __import__(module_name)
        except Exception:
            missing.append(package_name)
    return missing


def format_missing_dependencies(missing: list[str]) -> str:
    if not missing:
        return ""
    return (
        f"Missing Plus dependency: {', '.join(missing)}. "
        "Install ComfyUI-LX-Nodes/requirements-full.txt in this ComfyUI Python environment."
    )


def _pick_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


class FunASRStreamingSession:
    def __init__(self, engine: "FunASRStreamingEngine") -> None:
        self.engine = engine
        self.cache: dict[str, Any] = {}
        self.seen_audio = False
        self.transcript = ""
        self.final_text = ""
        self.last_raw_text = ""
        self.audio_parts: list[np.ndarray] = []
        self.closed = False

    def transcribe_chunk(self, audio: np.ndarray, sample_rate: int, is_final: bool = False) -> dict[str, Any]:
        if self.closed:
            return self.result(is_final=is_final)

        model = self.engine.ensure_loaded()
        audio = np.asarray(audio, dtype=np.float32)
        chunk = resample_linear(audio, sample_rate, TARGET_SAMPLE_RATE)
        if chunk.size == 0 and not is_final:
            return self.result(is_final=False)
        if chunk.size == 0 and is_final and not self.seen_audio:
            return self.result(is_final=True)
        if chunk.size > 0:
            self.seen_audio = True
            self.audio_parts.append(chunk.copy())

        raw_text = self._generate_stream_text(model, chunk, is_final)
        if raw_text:
            if len(raw_text) >= len(self.transcript) and self.transcript and self.transcript in raw_text:
                self.transcript = raw_text
            else:
                self.transcript = _merge_overlap(self.transcript, raw_text)
            self.last_raw_text = raw_text

        if is_final:
            final_text = self._generate_final_text(model)
            if final_text:
                self.final_text = final_text
        return self.result(is_final=is_final)

    def result(self, is_final: bool = False) -> dict[str, Any]:
        text = self.final_text if is_final and self.final_text else self.transcript
        if is_final:
            text = _restore_final_punctuation(text)
        return {
            "text": text,
            "partial": self.last_raw_text,
            "confirmed": self.transcript,
            "is_final": bool(is_final),
        }

    def _generate_stream_text(self, model, chunk: np.ndarray, is_final: bool) -> str:
        with self.engine._infer_lock:
            result = model.generate(
                input=chunk,
                cache=self.cache,
                is_final=bool(is_final),
                chunk_size=CHUNK_SIZE,
                encoder_chunk_look_back=ENCODER_CHUNK_LOOK_BACK,
                decoder_chunk_look_back=DECODER_CHUNK_LOOK_BACK,
                disable_pbar=True,
            )
        return _normalize_text(self.engine.extract_text(result))

    def _generate_final_text(self, model) -> str:
        if not self.audio_parts:
            return ""

        full_audio = np.concatenate(self.audio_parts).astype(np.float32, copy=False)
        if full_audio.size == 0:
            return ""

        with self.engine._infer_lock:
            result = model.generate(
                input=full_audio,
                chunk_size=CHUNK_SIZE,
                encoder_chunk_look_back=ENCODER_CHUNK_LOOK_BACK,
                decoder_chunk_look_back=DECODER_CHUNK_LOOK_BACK,
                disable_pbar=True,
            )
        return _normalize_text(self.engine.extract_text(result))

    def close(self) -> None:
        self.closed = True
        self.cache.clear()
        self.audio_parts.clear()


class FunASRStreamingEngine:
    def __init__(self) -> None:
        self.model_dir = _models_root() / MODEL_SUBDIR
        self._download_lock = threading.Lock()
        self._download_thread: threading.Thread | None = None
        self._download_progress = 100 if self.model_exists() else 0
        self._download_message = "READY" if self.model_exists() else "MODEL_MISSING"
        self._download_error = ""
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._model: Any | None = None
        self._device = _pick_device()

    def required_paths(self) -> list[Path]:
        return [self.model_dir / filename for filename in REQUIRED_MODEL_FILES]

    def model_exists(self) -> bool:
        return _has_required_files(self.model_dir)

    def status(self) -> dict[str, Any]:
        missing = _missing_imports()
        downloading = self._download_thread is not None and self._download_thread.is_alive()
        return {
            "model_exists": self.model_exists(),
            "model_loaded": self._model is not None,
            "downloading": downloading,
            "progress": self._download_progress,
            "message": self._download_message,
            "error": self._download_error,
            "missing_dependencies": missing,
            "model_dir": str(self.model_dir),
            "repo_id": MODEL_REPO_ID,
            "device": self._device,
        }

    def start_download(self) -> dict[str, Any]:
        if self.model_exists():
            self._download_progress = 100
            self._download_message = "READY"
            self._download_error = ""
            return self.status()

        missing = [name for name in _missing_imports() if name == "huggingface_hub"]
        if missing:
            self._download_error = f"Missing dependency: {', '.join(missing)}"
            self._download_message = "ERROR"
            return self.status()

        with self._download_lock:
            if self._download_thread is not None and self._download_thread.is_alive():
                return self.status()

            self._download_error = ""
            self._download_message = "DOWNLOADING"
            self._download_progress = 0
            self._download_thread = threading.Thread(target=self._download_worker, daemon=True)
            self._download_thread.start()
        return self.status()

    def _download_worker(self) -> None:
        try:
            from huggingface_hub import hf_hub_download

            self.model_dir.mkdir(parents=True, exist_ok=True)
            total = len(REQUIRED_MODEL_FILES)
            for index, filename in enumerate(REQUIRED_MODEL_FILES):
                if (self.model_dir / filename).is_file():
                    self._download_progress = int(((index + 1) / total) * 100)
                    continue

                self._download_message = f"DOWNLOADING {filename}"
                self._download_progress = int((index / total) * 100)
                hf_hub_download(
                    repo_id=MODEL_REPO_ID,
                    filename=filename,
                    local_dir=str(self.model_dir),
                    local_dir_use_symlinks=False,
                    resume_download=True,
                )
                self._download_progress = int(((index + 1) / total) * 100)

            if self.model_exists():
                self._download_progress = 100
                self._download_message = "READY"
                self._download_error = ""
            else:
                missing = [path.name for path in self.required_paths() if not path.is_file()]
                self._download_message = "ERROR"
                self._download_error = f"Model download incomplete: {', '.join(missing)}"
        except Exception as exc:
            self._download_message = "ERROR"
            self._download_error = str(exc)

    def ensure_loaded(self):
        if self._model is not None:
            return self._model

        if not self.model_exists():
            raise RuntimeError("streaming speech model is not downloaded")

        missing = [name for name in _missing_imports() if name != "huggingface_hub"]
        if missing:
            raise RuntimeError(format_missing_dependencies(missing))

        with self._load_lock:
            if self._model is not None:
                return self._model

            from funasr import AutoModel

            self._model = AutoModel(
                model=str(self.model_dir),
                device=self._device,
                disable_update=True,
                disable_pbar=True,
            )
            return self._model

    def create_session(self) -> FunASRStreamingSession:
        return FunASRStreamingSession(self)

    def extract_text(self, result: Any) -> str:
        if isinstance(result, list):
            parts = [self.extract_text(item) for item in result]
            return "".join(part for part in parts if part)
        if isinstance(result, dict):
            value = result.get("text") or result.get("preds") or result.get("sentence")
            return "" if value is None else str(value)
        return "" if result is None else str(result)


ENGINE = FunASRStreamingEngine()
