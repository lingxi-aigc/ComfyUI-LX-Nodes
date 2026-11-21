from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


AIPAI_HOST_SUFFIX = "aipaiai.cn"
AIPAI_ADOBE_FORMAT = "v1/images (AIPAI Adobe)"
AIPAI_IMAGE_QUALITIES = ["1K", "2K", "4K"]
AIPAI_IMAGE_SIZES = {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "16:9": "1536x864", "9:16": "864x1536",
    "4:3": "1536x1152", "3:4": "1152x1536",
    "5:4": "1536x1232", "4:5": "1232x1536",
    "21:9": "1536x656",
}
AIPAI_IMAGE_RATIOS = ["auto", *AIPAI_IMAGE_SIZES]
AIPAI_ADOBE_SIZES = {
    "1:1": ("1024x1024", "2048x2048", "2880x2880"),
    "5:4": ("1120x896", "2240x1792", "3200x2560"),
    "4:3": ("1152x864", "2304x1728", "3264x2448"),
    "3:2": ("1248x832", "2496x1664", "3504x2336"),
    "16:9": ("1280x720", "2560x1440", "3840x2160"),
    "21:9": ("1456x624", "3024x1296", "3696x1584"),
    "4:5": ("896x1120", "1792x2240", "2560x3200"),
    "3:4": ("864x1152", "1728x2304", "2448x3264"),
    "2:3": ("832x1248", "1664x2496", "2336x3504"),
    "9:16": ("720x1280", "1440x2560", "2160x3840"),
    "1:2": ("704x1408", "1408x2816", "1920x3840"),
    "2:1": ("1408x704", "2816x1408", "3840x1920"),
    "9:21": ("624x1456", "1296x3024", "1584x3696"),
}


def is_aipaiai_adobe(api_format: str, model: str) -> bool:
    return api_format == AIPAI_ADOBE_FORMAT or model.endswith("-firefly")


def is_aipaiai_base_url(value: object) -> bool:
    """Return True for AI派's normal and accelerated API hosts."""
    text = "" if value is None else str(value).strip()
    if not text:
        return False
    candidate = text if "://" in text else f"https://{text}"
    try:
        hostname = (urlsplit(candidate).hostname or "").lower().rstrip(".")
    except Exception:
        return False
    return hostname == AIPAI_HOST_SUFFIX or hostname.endswith(f".{AIPAI_HOST_SUFFIX}")


def normalize_aipaiai_base_url(value: object) -> str:
    """
    Accept both API-root and OpenAI-SDK-style AI派 base URLs.

    The plugin appends /v1/images/... itself, while AI派 also documents /v1 as
    an SDK base_url. Strip only that exact suffix to avoid /v1/v1/images/....
    """
    text = "" if value is None else str(value).strip().rstrip("/")
    if not text or not is_aipaiai_base_url(text):
        return text
    candidate = text if "://" in text else f"https://{text}"
    try:
        parts = urlsplit(candidate)
    except Exception:
        return text
    path = parts.path.rstrip("/")
    if path != "/v1":
        return candidate
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def aipaiai_image_size(ratio: object, size="2K", adobe=False) -> str:
    """Use Adobe's resolution presets or the ordinary channel's input sizes."""
    text = "" if ratio is None else str(ratio).strip()
    if adobe:
        tier = AIPAI_IMAGE_QUALITIES.index(size) if size in AIPAI_IMAGE_QUALITIES else 1
        if not text or text == "auto":
            text = "1:1"
        if text in AIPAI_ADOBE_SIZES:
            return AIPAI_ADOBE_SIZES[text][tier]
    if not text or text == "auto":
        return AIPAI_IMAGE_SIZES["1:1"]
    if not adobe and text in AIPAI_IMAGE_SIZES:
        return AIPAI_IMAGE_SIZES[text]
    if ":" not in text:
        return "auto"
    left, right = text.split(":", 1)
    try:
        width = float(left.strip())
        height = float(right.strip())
    except (TypeError, ValueError):
        return "auto"
    if width <= 0 or height <= 0:
        return "auto"
    ratio_value = width / height
    # Keep custom/model-specific ratios instead of silently turning them into 3:2.
    long_edge = {"1K": 1280, "2K": 2560, "4K": 3840}.get(size, 2560) if adobe else 1536
    w = long_edge if ratio_value >= 1 else long_edge * ratio_value
    h = long_edge / ratio_value if ratio_value >= 1 else long_edge
    return f"{max(16, round(w / 16) * 16)}x{max(16, round(h / 16) * 16)}"


def aipaiai_cache_fields(size: object, adobe=False, detail_quality="medium") -> dict[str, str]:
    quality = "" if size is None else str(size).strip().upper()
    if quality not in AIPAI_IMAGE_QUALITIES:
        quality = "2K"
    return {
        "provider_profile": "aipaiai_adobe_v2" if adobe else "aipaiai_images_v2",
        "quality": detail_quality if adobe else quality,
        "resolution": quality if adobe else "",
        "moderation": "",
        "response_format": "url",
    }
