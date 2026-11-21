from __future__ import annotations

import re


FILLER_PATTERNS = (
    "嗯",
    "呃",
    "啊",
    "那个",
    "这个",
    "就是",
    "然后",
    "其实",
    "你看",
    "怎么说呢",
)

TERM_REPLACEMENTS = (
    (re.compile(r"空飞\s*UI", re.IGNORECASE), "ComfyUI"),
    (re.compile(r"康菲\s*UI", re.IGNORECASE), "ComfyUI"),
    (re.compile(r"康复\s*UI", re.IGNORECASE), "ComfyUI"),
    (re.compile(r"comfy\s*ui", re.IGNORECASE), "ComfyUI"),
    (re.compile(r"劳拉", re.IGNORECASE), "LoRA"),
    (re.compile(r"lora", re.IGNORECASE), "LoRA"),
    (re.compile(r"control\s*net", re.IGNORECASE), "ControlNet"),
    (re.compile(r"康特\s*耐特", re.IGNORECASE), "ControlNet"),
    (re.compile(r"康特\s*net", re.IGNORECASE), "ControlNet"),
    (re.compile(r"\bvae\b", re.IGNORECASE), "VAE"),
)

QUESTION_TAIL_RE = re.compile(r"(吗|么|呢|是不是|可不可以|能不能|行不行|怎么样|如何|为什么|什么|哪里|哪儿|谁|多少|几)\s*$")
TRAILING_PUNCT_RE = re.compile(r"[。！？!?，,、；;：:\s]+$")
PUNCT_RUN_RE = re.compile(r"([。！？!?，,、；;：:])\1+")


def normalize_spaces(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"[\u3000\t\r\n]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def strip_fillers(text: str) -> str:
    value = normalize_spaces(text)
    if not value:
        return ""

    for filler in FILLER_PATTERNS:
        value = re.sub(
            rf"(^|[，,。！？!?、；;：:\s]){re.escape(filler)}(?=$|[，,。！？!?、；;：:\s])",
            r"\1",
            value,
        )

    return normalize_spaces(value)


def fix_terms(text: str) -> str:
    value = str(text or "")
    for pattern, replacement in TERM_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value


def normalize_punctuation(text: str) -> str:
    value = str(text or "")
    value = value.replace(",", "，").replace("?", "？").replace("!", "！")
    value = re.sub(r"\s*([，。！？；：、])\s*", r"\1", value)
    value = PUNCT_RUN_RE.sub(r"\1", value)
    value = re.sub(r"^[，,。！？!?、；;：:\s]+", "", value)
    return value.strip()


def apply_prompt_punctuation(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""

    value = value.replace("。", "，")
    value = value.replace("；", "，").replace(";", "，")
    value = value.replace("、", "，")
    value = value.replace("：", "，").replace(":", "，")
    value = re.sub(r"，{2,}", "，", value)
    value = re.sub(r"，([？！])", r"\1", value)
    value = re.sub(r"([？！])，", r"\1", value)
    value = re.sub(r"[。]{2,}", "，", value)
    value = re.sub(r"[？]{2,}", "？", value)
    value = re.sub(r"[！]{2,}", "！", value)
    return value.strip()


def ensure_prompt_tail(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if re.search(r"[？！]$", value):
        return value

    stripped = TRAILING_PUNCT_RE.sub("", value).strip()
    if not stripped:
        return ""

    if QUESTION_TAIL_RE.search(stripped):
        return f"{stripped}？"
    return stripped


def postprocess_text(text: str) -> str:
    value = normalize_spaces(text)
    value = strip_fillers(value)
    value = fix_terms(value)
    value = normalize_punctuation(value)
    value = apply_prompt_punctuation(value)
    value = ensure_prompt_tail(value)
    return value
