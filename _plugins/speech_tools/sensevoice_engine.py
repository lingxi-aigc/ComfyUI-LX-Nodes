from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from .audio_utils import TARGET_SAMPLE_RATE, resample_linear, rms
from .text_postprocess import postprocess_text


MODEL_REPO_ID = "lovemefan/SenseVoice-onnx"
MODEL_SUBDIR = Path("speech") / "sensevoice_onnx_int8"
REQUIRED_MODEL_FILES = (
    "am.mvn",
    "embedding.npy",
    "chn_jpn_yue_eng_ko_spectok.bpe.model",
    "sense-voice-encoder-int8.onnx",
    "fsmn-am.mvn",
    "fsmn-config.yaml",
    "fsmnvad-offline.onnx",
)

LANGUAGES = {
    "auto": 0,
    "zh": 3,
    "en": 4,
    "yue": 7,
    "ja": 11,
    "ko": 12,
    "nospeech": 13,
}

RESULT_RE = re.compile(r"<\|(.+?)\|><\|(.+?)\|><\|(.+?)\|><\|(.+?)\|>(.*)", re.S)


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
        ("onnxruntime", "onnxruntime"),
        ("sensevoice", "sensevoice"),
    )
    for module_name, package_name in checks:
        try:
            __import__(module_name)
        except Exception:
            missing.append(package_name)
    return missing


class SenseVoiceEngine:
    def __init__(self) -> None:
        self.model_dir = _models_root() / MODEL_SUBDIR
        self._download_lock = threading.Lock()
        self._download_thread: threading.Thread | None = None
        self._download_progress = 100 if self.model_exists() else 0
        self._download_message = "READY" if self.model_exists() else "MODEL_MISSING"
        self._download_error = ""

        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._processor: Any | None = None
        self._device = "cpu"
        self._num_threads = 4
        self._language = "zh"

    def required_paths(self) -> list[Path]:
        return [self.model_dir / filename for filename in REQUIRED_MODEL_FILES]

    def model_exists(self) -> bool:
        return _has_required_files(self.model_dir)

    def status(self) -> dict[str, Any]:
        missing = _missing_imports()
        downloading = self._download_thread is not None and self._download_thread.is_alive()
        return {
            "model_exists": self.model_exists(),
            "model_loaded": self._processor is not None,
            "downloading": downloading,
            "progress": self._download_progress,
            "message": self._download_message,
            "error": self._download_error,
            "missing_dependencies": missing,
            "model_dir": str(self.model_dir),
            "repo_id": MODEL_REPO_ID,
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

    def ensure_loaded(self) -> None:
        if self._processor is not None:
            return
        if not self.model_exists():
            raise RuntimeError("speech model is not downloaded")

        missing = [name for name in _missing_imports() if name != "huggingface_hub"]
        if missing:
            raise RuntimeError(f"missing dependency: {', '.join(missing)}")

        with self._load_lock:
            if self._processor is not None:
                return

            from sensevoice.onnx.sense_voice_ort_session import SenseVoiceInferenceSession
            from sensevoice.utils.frontend import WavFrontend
            from sensevoice.utils.fsmn_vad import FSMNVad

            frontend = WavFrontend(str(self.model_dir / "am.mvn"))
            model = SenseVoiceInferenceSession(
                str(self.model_dir / "embedding.npy"),
                str(self.model_dir / "sense-voice-encoder-int8.onnx"),
                str(self.model_dir / "chn_jpn_yue_eng_ko_spectok.bpe.model"),
                self._device,
                self._num_threads,
            )
            vad = FSMNVad(str(self.model_dir))
            self._processor = {
                "frontend": frontend,
                "model": model,
                "vad": vad,
            }

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_SAMPLE_RATE) -> dict[str, Any]:
        start = time.time()
        waveform = resample_linear(audio.astype(np.float32, copy=False), sample_rate, TARGET_SAMPLE_RATE)
        waveform = np.clip(waveform, -1.0, 1.0)
        duration = waveform.shape[0] / float(TARGET_SAMPLE_RATE)

        if duration < 0.25 or rms(waveform) < 0.003:
            return {
                "status": "success",
                "text": "",
                "raw": "",
                "duration": duration,
                "elapsed": time.time() - start,
            }

        self.ensure_loaded()

        with self._infer_lock:
            assert self._processor is not None
            frontend = self._processor["frontend"]
            model = self._processor["model"]
            vad = self._processor["vad"]

            raw_parts: list[str] = []
            text_parts: list[str] = []
            segments = vad.segments_offline(waveform)
            if not segments:
                segments = [(0, int(duration * 1000))]

            for part in segments:
                start_ms = max(0, int(part[0]))
                end_ms = max(start_ms, int(part[1]))
                start_sample = int(start_ms * TARGET_SAMPLE_RATE / 1000)
                end_sample = int(end_ms * TARGET_SAMPLE_RATE / 1000)
                segment = waveform[start_sample:end_sample]
                if segment.shape[0] < int(0.2 * TARGET_SAMPLE_RATE):
                    continue

                audio_feats = frontend.get_features(segment)
                result = model(
                    audio_feats[None, ...],
                    language=LANGUAGES[self._language],
                    use_itn=True,
                )
                raw_text = str(result or "")
                raw_parts.append(raw_text)
                text = self._extract_text(raw_text)
                if text:
                    text_parts.append(text)

            try:
                vad.vad.all_reset_detection()
            except Exception:
                pass

        joined = "".join(text_parts)
        return {
            "status": "success",
            "text": postprocess_text(joined),
            "raw": "\n".join(raw_parts),
            "duration": duration,
            "elapsed": time.time() - start,
        }

    @staticmethod
    def _extract_text(raw_text: str) -> str:
        match = RESULT_RE.match(raw_text.strip())
        if match:
            return match.group(5).strip()
        return raw_text.strip()


ENGINE = SenseVoiceEngine()
