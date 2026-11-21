from __future__ import annotations

import base64
from typing import Any

import numpy as np


TARGET_SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 15.0


def decode_pcm16_base64(payload: dict[str, Any]) -> tuple[np.ndarray, int, float]:
    sample_rate = int(payload.get("sample_rate") or TARGET_SAMPLE_RATE)
    channels = max(1, int(payload.get("channels") or 1))
    encoded = str(payload.get("audio") or "")
    if not encoded:
        raise ValueError("missing audio payload")

    raw = base64.b64decode(encoded)
    samples = np.frombuffer(raw, dtype="<i2")
    if samples.size == 0:
        raise ValueError("empty audio payload")

    if channels > 1:
        usable = samples.size - (samples.size % channels)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1).astype(np.int16)

    audio = samples.astype(np.float32) / 32768.0
    duration = float(audio.shape[0]) / float(sample_rate)
    if duration > MAX_AUDIO_SECONDS:
        raise ValueError(f"audio segment is too long: {duration:.1f}s")

    return audio, sample_rate, duration


def resample_linear(audio: np.ndarray, source_rate: int, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    if source_rate == target_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size == 0:
        return audio.astype(np.float32, copy=False)

    duration = audio.shape[0] / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    source_x = np.linspace(0.0, duration, num=audio.shape[0], endpoint=False)
    target_x = np.linspace(0.0, duration, num=target_length, endpoint=False)
    return np.interp(target_x, source_x, audio).astype(np.float32)


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
