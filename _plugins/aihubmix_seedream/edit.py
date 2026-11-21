from __future__ import annotations

import base64
import json
import re
import time
from io import BytesIO
from typing import Any

import requests
import torch
from PIL import Image

import comfy.model_management  # type: ignore[reportMissingImports]
import comfy.utils  # type: ignore[reportMissingImports]
from comfy_execution.graph_utils import ExecutionBlocker  # type: ignore[reportMissingImports]

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_utils import pil2tensor, tensor2pil


AIHUBMIX_BASE_URL = "https://aihubmix.com"
AIHUBMIX_MODELS = [
    "doubao-seedream-5.0-lite",
    "doubao-seedream-4-5",
    "doubao-seedream-4-0",
]
IMAGE_SIZES = ["1K", "2K", "3K", "4K"]
MAX_INPUT_IMAGES = 10
REQUEST_TIMEOUT = 300
EMPTY_IMAGE_SIZE = (1024, 1024)


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _redact_key(text: str) -> str:
    value = _clean_text(text)
    if len(value) <= 8:
        return "***" if value else ""
    return f"{value[:4]}***{value[-4:]}"


def _image_to_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _data_url_to_image(value: str) -> Image.Image | None:
    match = re.match(r"^data:image/[^;]+;base64,(.+)$", value.strip(), re.I | re.S)
    if not match:
        return None
    raw = base64.b64decode(re.sub(r"\s+", "", match.group(1)))
    return Image.open(BytesIO(raw)).convert("RGB")


def _blank_image() -> Image.Image:
    return Image.new("RGB", EMPTY_IMAGE_SIZE, (255, 255, 255))


def _batch_tensor(images: list[Image.Image]) -> torch.Tensor:
    if not images:
        return pil2tensor(_blank_image())

    width = max(max(1, image.width) for image in images)
    height = max(max(1, image.height) for image in images)
    tensors = []
    for image in images:
        normalized = image.convert("RGB")
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        x = max(0, (width - normalized.width) // 2)
        y = max(0, (height - normalized.height) // 2)
        canvas.paste(normalized, (x, y))
        tensors.append(pil2tensor(canvas))
    return torch.cat(tensors, dim=0)


def _collect_strings(value: Any, output: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            output.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _collect_strings(item, output)
        return
    if isinstance(value, dict):
        priority_keys = (
            "url",
            "image",
            "image_url",
            "output_url",
            "download_url",
            "file_url",
            "b64_json",
        )
        for key in priority_keys:
            if key in value:
                _collect_strings(value.get(key), output)
        for key in ("images", "image_urls", "urls", "output", "result", "results", "data"):
            if key in value:
                _collect_strings(value.get(key), output)


def _extract_image_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    _collect_strings(payload.get("output"), values)
    for key in ("images", "image_urls", "urls", "result", "results", "data"):
        _collect_strings(payload.get(key), values)
    if not values:
        _collect_strings(payload, values)

    result: list[str] = []
    seen = set()
    for value in values:
        if (
            value.startswith("http://")
            or value.startswith("https://")
            or value.startswith("data:image/")
            or re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", value)
        ):
            key = value[:256]
            if key not in seen:
                seen.add(key)
                result.append(value)
    return result


class AIHubmixSeedreamEdit:
    SEARCH_ALIASES = (
        "lx",
        "LX",
        "灵犀",
        "aihubmix",
        "seedream",
        "doubao",
        "豆包",
        "图生图",
        "多图编辑",
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for index in range(2, MAX_INPUT_IMAGES + 1):
            optional[f"image{index}"] = ("IMAGE",)

        return {
            "required": {
                "image1": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True}),
                "model": (AIHUBMIX_MODELS, {"default": AIHUBMIX_MODELS[0]}),
                "size": (IMAGE_SIZES, {"default": "2K"}),
                "apikey": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "response", "image_urls", "explanation")
    FUNCTION = "edit"
    CATEGORY = f"{LX_RELAY_CATEGORY}/AIHUBMIX"

    def _input_images(self, image1, kwargs: dict[str, Any]) -> list[Image.Image]:
        images: list[Image.Image] = []
        for tensor in [image1] + [kwargs.get(f"image{i}") for i in range(2, MAX_INPUT_IMAGES + 1)]:
            if tensor is None:
                continue
            images.extend(tensor2pil(tensor))
        return images[:MAX_INPUT_IMAGES]

    def _request(self, model: str, api_key: str, prompt: str, size: str, images: list[Image.Image]):
        endpoint = f"{AIHUBMIX_BASE_URL}/v1/models/doubao/{model}/predictions"
        image_values = [_image_to_data_url(image) for image in images]
        image_payload: str | list[str]
        image_payload = image_values[0] if len(image_values) == 1 else image_values

        payload = {
            "input": {
                "prompt": prompt,
                "image": image_payload,
                "size": size,
                "sequential_image_generation": "disabled",
                "stream": False,
                "response_format": "url",
                "watermark": False,
            }
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return requests.post(endpoint, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)

    def _download_value(self, value: str) -> Image.Image:
        data_image = _data_url_to_image(value)
        if data_image is not None:
            return data_image

        if value.startswith("http://") or value.startswith("https://"):
            response = requests.get(value, timeout=90)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGB")

        raw = base64.b64decode(re.sub(r"\s+", "", value))
        return Image.open(BytesIO(raw)).convert("RGB")

    def _poll_if_needed(self, result: dict[str, Any], api_key: str) -> dict[str, Any]:
        status = _clean_text(result.get("status")).lower()
        poll_url = ""
        urls = result.get("urls")
        if isinstance(urls, dict):
            poll_url = _clean_text(urls.get("get"))
        if not poll_url and result.get("id"):
            poll_url = f"{AIHUBMIX_BASE_URL}/v1/predictions/{result['id']}"

        if status not in {"starting", "processing", "queued", "running", "pending"} or not poll_url:
            return result

        headers = {"Authorization": f"Bearer {api_key}"}
        start = time.time()
        while time.time() - start < REQUEST_TIMEOUT:
            comfy.model_management.throw_exception_if_processing_interrupted()
            time.sleep(1.5)
            response = requests.get(poll_url, headers=headers, timeout=30)
            if response.status_code >= 400:
                return result
            current = response.json()
            current_status = _clean_text(current.get("status")).lower()
            if current_status in {"succeeded", "success", "completed", "done"}:
                return current
            if current_status in {"failed", "canceled", "cancelled", "error"}:
                return current
        return result

    def _error_result(self, message: str, response: dict[str, Any] | None = None):
        payload = response or {"code": "error", "message": message}
        return (
            ExecutionBlocker(None),
            json.dumps(payload, ensure_ascii=False),
            "[]",
            message,
        )

    def edit(self, image1, prompt, model, size, apikey, **kwargs):
        try:
            api_key = _clean_text(apikey)
            if not api_key or api_key.lower() in {"none", "null"}:
                return self._error_result("AIHUBMIX apikey 不能为空。")

            text = _clean_text(prompt)
            if not text:
                return self._error_result("prompt 不能为空。")

            images = self._input_images(image1, kwargs)
            if not images:
                return self._error_result("至少需要连接 image1。")

            pbar = comfy.utils.ProgressBar(100)
            pbar.update_absolute(10)
            print(
                f"[AIHUBMIX Seedream] edit | model={model} | size={size} | "
                f"images={len(images)} | key={_redact_key(api_key)}"
            )

            response = self._request(model, api_key, text, size, images)
            pbar.update_absolute(50)
            body_text = response.text
            try:
                result = response.json()
            except Exception:
                result = {"status": response.status_code, "body": body_text[:1000]}

            if response.status_code >= 400:
                message = f"AIHUBMIX HTTP {response.status_code}: {body_text[:500]}"
                return self._error_result(message, result if isinstance(result, dict) else None)

            if isinstance(result, dict):
                result = self._poll_if_needed(result, api_key)
            else:
                result = {"result": result}

            pbar.update_absolute(70)
            values = _extract_image_values(result)
            if not values:
                return self._error_result(f"响应里没有找到图片 URL 或 base64：{json.dumps(result, ensure_ascii=False)[:800]}", result)

            output_images = []
            for index, value in enumerate(values, start=1):
                comfy.model_management.throw_exception_if_processing_interrupted()
                pbar.update_absolute(70 + min(25, index * 5))
                output_images.append(self._download_value(value))

            pbar.update_absolute(100)
            image_urls = [value for value in values if value.startswith("http://") or value.startswith("https://")]
            return (
                _batch_tensor(output_images),
                json.dumps(result, ensure_ascii=False),
                json.dumps(image_urls, ensure_ascii=False),
                "",
            )
        except comfy.model_management.InterruptProcessingException:
            print("[AIHUBMIX Seedream] interrupted by user")
            raise
        except Exception as exc:
            return self._error_result(str(exc))
