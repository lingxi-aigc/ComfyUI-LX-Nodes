from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..categories import LX_TEXT_CATEGORY


MODEL_REPO_ID = "facebook/nllb-200-distilled-600M"
MODEL_DIR_NAME = "nllb-200-distilled-600M-ct2-int8"
TOKENIZER_DIR_NAME = "nllb-200-distilled-600M-tokenizer"
DOWNLOAD_DIR_NAME = "_downloads"
COPY_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
)
DOWNLOAD_ALLOW_PATTERNS = (
    "config.json",
    "generation_config.json",
    "pytorch_model.bin",
    "*.safetensors",
    *COPY_TOKENIZER_FILES,
)
DEFAULT_DOWNLOAD_ENDPOINTS = (
    "https://hf-mirror.com",
    "https://huggingface.co",
)

TARGET_LANGUAGES = {
    "英文": "eng_Latn",
    "中文": "zho_Hans",
    "日文": "jpn_Jpan",
    "韩文": "kor_Hang",
}
TRANSLATION_MODES = ("提示词模式", "普通文本")
DEFAULT_TARGET = "英文"
DEFAULT_MODE = "提示词模式"

CT2_REQUIRED_FILES = ("model.bin", "config.json")
TOKENIZER_MODEL_FILES = ("tokenizer.json", "sentencepiece.bpe.model")

CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
ZH_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
JA_RE = re.compile(r"[\u3040-\u30ff]")
KO_RE = re.compile(r"[\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")
PROMPT_TOKEN_RE = re.compile(r"(<[^>]+>|__[^_\s]+__|\([^)]*:[0-9.]+\)|[,\n;，；、]+)")
PROMPT_DELIMITER_RE = re.compile(r"^[,\n;，；、]+$")
ASCII_TAG_RE = re.compile(r"^[A-Za-z0-9_ .:/\\+\-#'\"|]+$")
WEIGHT_RE = re.compile(r"^(\s*)\(([^)]*):([0-9.]+)\)(\s*)$")

_CACHE_LIMIT = 256
_cache_lock = threading.RLock()
_model_prepare_lock = threading.RLock()
_result_cache: OrderedDict[str, str] = OrderedDict()


def _models_root() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.models_dir)
    except Exception:
        return Path(__file__).resolve().parents[4] / "models"


def _translation_root() -> Path:
    return _models_root() / "translation"


def _split_endpoints(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def _download_endpoints() -> list[str]:
    endpoints: list[str] = []
    for env_name in ("LX_TRANSLATION_HF_ENDPOINTS", "LX_TRANSLATION_HF_ENDPOINT", "HF_ENDPOINT"):
        value = os.environ.get(env_name, "")
        if value:
            endpoints.extend(_split_endpoints(value))
    endpoints.extend(DEFAULT_DOWNLOAD_ENDPOINTS)

    unique: list[str] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        if endpoint and endpoint not in seen:
            unique.append(endpoint)
            seen.add(endpoint)
    return unique


def _candidate_model_dirs() -> list[Path]:
    root = _translation_root()
    return [
        root / MODEL_DIR_NAME,
        root / "nllb-200-distilled-600M-ct2",
        root / "nllb-200-distilled-600M",
    ]


def _candidate_tokenizer_dirs(model_dir: Path) -> list[Path]:
    root = _translation_root()
    return [
        model_dir,
        root / TOKENIZER_DIR_NAME,
        root / "nllb-200-distilled-600M",
    ]


def _has_ct2_model(path: Path) -> bool:
    return all((path / name).is_file() for name in CT2_REQUIRED_FILES)


def _has_tokenizer(path: Path) -> bool:
    return (path / "tokenizer_config.json").is_file() and any(
        (path / name).is_file() for name in TOKENIZER_MODEL_FILES
    )


def _find_model_dir() -> Path | None:
    for path in _candidate_model_dirs():
        if _has_ct2_model(path):
            return path
    return None


def _find_tokenizer_dir(model_dir: Path) -> Path | None:
    for path in _candidate_tokenizer_dirs(model_dir):
        if _has_tokenizer(path):
            return path
    return None


def _missing_dependency_message() -> str:
    missing: list[str] = []
    for module_name, package_name in (
        ("ctranslate2", "ctranslate2"),
        ("transformers", "transformers"),
        ("sentencepiece", "sentencepiece"),
    ):
        try:
            __import__(module_name)
        except Exception:
            missing.append(package_name)
    if not missing:
        return ""
    return "缺少依赖: " + ", ".join(missing) + "。请安装 requirements-full.txt 后重启 ComfyUI。"


def _model_missing_message() -> str:
    model_dir = _translation_root() / MODEL_DIR_NAME
    tokenizer_dir = _translation_root() / TOKENIZER_DIR_NAME
    return (
        "缺少离线翻译模型。请将 CTranslate2 INT8 模型放到:\n"
        f"{model_dir}\n\n"
        "至少需要 model.bin 和 config.json。\n"
        "tokenizer 文件可以放在同一目录，或放到:\n"
        f"{tokenizer_dir}\n\n"
        "推荐转换命令:\n"
        f'ct2-transformers-converter --model {MODEL_REPO_ID} --quantization int8 '
        "--copy_files tokenizer.json tokenizer_config.json sentencepiece.bpe.model special_tokens_map.json "
        f'--output_dir "{model_dir}"\n\n'
        "国内网络可设置下载源，例如:\n"
        "set HF_ENDPOINT=https://hf-mirror.com"
    )


def _download_source_model() -> Path:
    from huggingface_hub import snapshot_download

    local_dir = _translation_root() / DOWNLOAD_DIR_NAME / MODEL_REPO_ID.replace("/", "--")
    local_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for endpoint in _download_endpoints():
        try:
            print(f"[LX][OfflineTranslator] downloading {MODEL_REPO_ID} from {endpoint}")
            path = snapshot_download(
                repo_id=MODEL_REPO_ID,
                endpoint=endpoint,
                local_dir=str(local_dir),
                local_dir_use_symlinks=False,
                allow_patterns=list(DOWNLOAD_ALLOW_PATTERNS),
                resume_download=True,
                max_workers=4,
                etag_timeout=20,
            )
            return Path(path)
        except Exception as exc:
            message = f"{endpoint}: {exc}"
            errors.append(message)
            print(f"[LX][OfflineTranslator] download source failed: {message}")

    raise RuntimeError(
        "自动下载离线翻译原始模型失败，已尝试以下下载源:\n"
        + "\n".join(f"- {item}" for item in errors)
        + "\n\n可以手动设置环境变量 LX_TRANSLATION_HF_ENDPOINTS，例如:\n"
        "LX_TRANSLATION_HF_ENDPOINTS=https://hf-mirror.com,https://huggingface.co"
    )


def _prepare_model_dir() -> Path:
    model_dir = _find_model_dir()
    if model_dir is not None:
        return model_dir

    with _model_prepare_lock:
        model_dir = _find_model_dir()
        if model_dir is not None:
            return model_dir

        output_dir = _translation_root() / MODEL_DIR_NAME
        output_dir.parent.mkdir(parents=True, exist_ok=True)

        print(
            "[LX][OfflineTranslator] local model not found, downloading and converting "
            f"{MODEL_REPO_ID} to {output_dir}"
        )
        try:
            import huggingface_hub  # noqa: F401
            from ctranslate2.converters import TransformersConverter

            source_dir = _download_source_model()
            converter = TransformersConverter(
                str(source_dir),
                copy_files=list(COPY_TOKENIZER_FILES),
                low_cpu_mem_usage=True,
            )
            converter.convert(str(output_dir), quantization="int8", force=True)
        except Exception as exc:
            raise RuntimeError(
                "首次自动下载/转换离线翻译模型失败。请确认网络可访问 Hugging Face，"
                "并且磁盘至少预留约 6GB 临时空间。\n\n"
                f"原始错误: {exc}\n\n"
                f"{_model_missing_message()}"
            ) from exc

        model_dir = _find_model_dir()
        if model_dir is None:
            raise RuntimeError(
                "模型下载/转换完成后仍未找到 CTranslate2 文件。\n\n"
                f"{_model_missing_message()}"
            )
        print(f"[LX][OfflineTranslator] model is ready: {model_dir}")
        return model_dir


def _tokenizer_missing_message(model_dir: Path) -> str:
    tokenizer_dir = _translation_root() / TOKENIZER_DIR_NAME
    return (
        "缺少 NLLB tokenizer 文件。请把 tokenizer.json、tokenizer_config.json、"
        "sentencepiece.bpe.model、special_tokens_map.json 放到模型目录:\n"
        f"{model_dir}\n\n"
        "也可以单独放到:\n"
        f"{tokenizer_dir}"
    )


def _detect_language(text: str) -> str:
    if KO_RE.search(text):
        return "kor_Hang"
    if JA_RE.search(text):
        return "jpn_Jpan"
    if ZH_RE.search(text):
        return "zho_Hans"
    if LATIN_RE.search(text):
        return "eng_Latn"
    return "eng_Latn"


def _cache_key(text: str, target_language: str, mode: str) -> str:
    raw = f"{MODEL_DIR_NAME}\0{target_language}\0{mode}\0{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> str | None:
    with _cache_lock:
        value = _result_cache.get(key)
        if value is None:
            return None
        _result_cache.move_to_end(key)
        return value


def _cache_set(key: str, value: str) -> None:
    with _cache_lock:
        _result_cache[key] = value
        _result_cache.move_to_end(key)
        while len(_result_cache) > _CACHE_LIMIT:
            _result_cache.popitem(last=False)


def _split_text_with_newlines(text: str) -> list[str]:
    return re.split(r"(\n+)", text)


def _split_prompt(text: str) -> list[str]:
    return [part for part in PROMPT_TOKEN_RE.split(text) if part != ""]


def _is_prompt_delimiter(part: str) -> bool:
    return bool(PROMPT_DELIMITER_RE.match(part))


def _is_structural_prompt_part(part: str) -> bool:
    value = part.strip()
    if not value:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    if value.startswith("__") and value.endswith("__"):
        return True
    if value.startswith("[") and value.endswith("]") and ASCII_TAG_RE.match(value[1:-1].strip()):
        return True
    return False


def _should_translate_text(value: str, target_code: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if target_code == "eng_Latn":
        if ASCII_TAG_RE.match(stripped) and not CJK_RE.search(stripped):
            return False
        return bool(CJK_RE.search(stripped))
    return _detect_language(stripped) != target_code


def _should_translate_prompt_part(part: str, target_code: str) -> bool:
    if _is_prompt_delimiter(part) or _is_structural_prompt_part(part):
        return False
    return _should_translate_text(part, target_code)


def _preserve_outer_space(original: str, translated: str) -> str:
    leading_len = len(original) - len(original.lstrip())
    trailing_len = len(original) - len(original.rstrip())
    leading = original[:leading_len]
    trailing = original[len(original) - trailing_len :] if trailing_len else ""
    return f"{leading}{translated.strip()}{trailing}"


class _OfflineTranslatorEngine:
    def __init__(self) -> None:
        self._load_lock = threading.RLock()
        self._infer_lock = threading.RLock()
        self._translator: Any | None = None
        self._tokenizer: Any | None = None
        self._model_dir: Path | None = None
        self._tokenizer_dir: Path | str | None = None
        self._device = "cpu"

    def ensure_loaded(self) -> None:
        if self._translator is not None and self._tokenizer is not None:
            return

        dependency_error = _missing_dependency_message()
        if dependency_error:
            raise RuntimeError(dependency_error)

        model_dir = _prepare_model_dir()

        tokenizer_dir = _find_tokenizer_dir(model_dir)
        tokenizer_source: Path | str | None = tokenizer_dir
        if tokenizer_source is None:
            # Offline cache fallback. This never downloads because local_files_only=True.
            tokenizer_source = MODEL_REPO_ID

        with self._load_lock:
            if self._translator is not None and self._tokenizer is not None:
                return

            import ctranslate2
            from transformers import AutoTokenizer

            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    str(tokenizer_source),
                    src_lang="zho_Hans",
                    local_files_only=True,
                    use_fast=True,
                )
            except Exception as exc:
                if tokenizer_dir is None:
                    raise RuntimeError(_tokenizer_missing_message(model_dir)) from exc
                raise RuntimeError(f"tokenizer 加载失败: {exc}") from exc

            translator, device = self._load_translator(ctranslate2, model_dir)
            self._translator = translator
            self._tokenizer = tokenizer
            self._model_dir = model_dir
            self._tokenizer_dir = tokenizer_source
            self._device = device

    @staticmethod
    def _load_translator(ctranslate2_module: Any, model_dir: Path) -> tuple[Any, str]:
        devices = ["cpu"]
        try:
            import torch

            if torch.cuda.is_available():
                devices.insert(0, "cuda")
        except Exception:
            pass

        last_error: Exception | None = None
        for device in devices:
            try:
                translator = ctranslate2_module.Translator(
                    str(model_dir),
                    device=device,
                    compute_type="auto",
                )
                return translator, device
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"CTranslate2 模型加载失败: {last_error}")

    def translate_batch(self, texts: list[str], target_code: str) -> list[str]:
        self.ensure_loaded()
        assert self._translator is not None
        assert self._tokenizer is not None

        outputs = [""] * len(texts)
        groups: dict[str, list[tuple[int, str]]] = {}
        for index, text in enumerate(texts):
            if not text.strip():
                outputs[index] = text
                continue
            source_code = _detect_language(text)
            if source_code == target_code:
                outputs[index] = text
                continue
            groups.setdefault(source_code, []).append((index, text))

        with self._infer_lock:
            for source_code, items in groups.items():
                self._tokenizer.src_lang = source_code
                source_tokens = [
                    self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text))
                    for _, text in items
                ]
                results = self._translator.translate_batch(
                    source_tokens,
                    target_prefix=[[target_code] for _ in source_tokens],
                    beam_size=4,
                    max_batch_size=16,
                )

                for (index, original), result in zip(items, results):
                    tokens = list(result.hypotheses[0])
                    if tokens and tokens[0] == target_code:
                        tokens = tokens[1:]
                    ids = self._tokenizer.convert_tokens_to_ids(tokens)
                    translated = self._tokenizer.decode(ids, skip_special_tokens=True)
                    outputs[index] = _preserve_outer_space(original, translated)

        return outputs

    def info_prefix(self) -> str:
        model = self._model_dir.name if self._model_dir else MODEL_DIR_NAME
        return f"模型: {model} | 设备: {self._device}"


ENGINE = _OfflineTranslatorEngine()


def _translate_normal_text(text: str, target_code: str) -> str:
    parts = _split_text_with_newlines(text)
    indexes: list[int] = []
    pending: list[str] = []
    for index, part in enumerate(parts):
        if part and not part.isspace():
            indexes.append(index)
            pending.append(part)

    if pending:
        translated = ENGINE.translate_batch(pending, target_code)
        for index, value in zip(indexes, translated):
            parts[index] = value
    return "".join(parts)


def _translate_prompt_text(text: str, target_code: str) -> str:
    parts = _split_prompt(text)
    jobs: list[tuple[int, str, tuple[str, ...] | None]] = []
    pending: list[str] = []
    for index, part in enumerate(parts):
        weight_match = WEIGHT_RE.match(part)
        if weight_match:
            inner = weight_match.group(2)
            if _should_translate_text(inner, target_code):
                jobs.append((index, "weight", weight_match.groups()))
                pending.append(inner)
            continue

        if _should_translate_prompt_part(part, target_code):
            jobs.append((index, "plain", None))
            pending.append(part)

    if pending:
        translated = ENGINE.translate_batch(pending, target_code)
        for (index, kind, metadata), value in zip(jobs, translated):
            if kind == "weight" and metadata is not None:
                leading, _inner, weight, trailing = metadata
                parts[index] = f"{leading}({value.strip()}:{weight}){trailing}"
            else:
                parts[index] = value
    return "".join(parts)


class LXOfflineTranslator:
    """Translate text locally with a CTranslate2 NLLB model."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "离线翻译", "翻译", "translator", "translation"]
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("翻译结果", "信息")
    FUNCTION = "translate"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "文本": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
                "目标语言": (
                    list(TARGET_LANGUAGES.keys()),
                    {
                        "default": DEFAULT_TARGET,
                    },
                ),
                "翻译模式": (
                    list(TRANSLATION_MODES),
                    {
                        "default": DEFAULT_MODE,
                    },
                ),
            },
        }

    def translate(self, 文本: str = "", 目标语言: str = DEFAULT_TARGET, 翻译模式: str = DEFAULT_MODE):
        start = time.time()
        text = "" if 文本 is None else str(文本)
        target_language = 目标语言 if 目标语言 in TARGET_LANGUAGES else DEFAULT_TARGET
        mode = 翻译模式 if 翻译模式 in TRANSLATION_MODES else DEFAULT_MODE
        target_code = TARGET_LANGUAGES[target_language]

        if not text.strip():
            return ("", "未输入文本")

        key = _cache_key(text, target_language, mode)
        cached = _cache_get(key)
        if cached is not None:
            elapsed = time.time() - start
            return (
                cached,
                f"{ENGINE.info_prefix()} | 目标: {target_language} | 模式: {mode} | 缓存: 命中 | 耗时: {elapsed:.2f}s",
            )

        try:
            if mode == "普通文本":
                translated = _translate_normal_text(text, target_code)
            else:
                translated = _translate_prompt_text(text, target_code)
            _cache_set(key, translated)
            elapsed = time.time() - start
            info = (
                f"{ENGINE.info_prefix()} | 目标: {target_language} | 模式: {mode} "
                f"| 缓存: 未命中 | 耗时: {elapsed:.2f}s"
            )
            return (translated, info)
        except Exception as exc:
            elapsed = time.time() - start
            return ("", f"翻译失败: {exc}\n耗时: {elapsed:.2f}s")
