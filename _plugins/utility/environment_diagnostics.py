from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from ..categories import LX_UTILITY_CATEGORY


BASIC_DEPENDENCIES = (
    ("Pillow", "PIL", "requirements.txt"),
    ("numpy", "numpy", "requirements.txt"),
    ("requests", "requests", "requirements.txt"),
    ("aiohttp", "aiohttp", "requirements.txt"),
    ("huggingface_hub", "huggingface_hub", "requirements.txt"),
)

FULL_DEPENDENCIES = (
    ("onnxruntime", "onnxruntime", "requirements-full.txt"),
    ("transformers", "transformers", "requirements-full.txt"),
    ("ctranslate2", "ctranslate2", "requirements-full.txt"),
    ("sentencepiece", "sentencepiece", "requirements-full.txt"),
    ("accelerate", "accelerate", "requirements-full.txt"),
    ("transparent-background", "transparent_background", "requirements-full.txt"),
    ("safetensors", "safetensors", "requirements-full.txt"),
    ("einops", "einops", "requirements-full.txt"),
    ("timm", "timm", "requirements-full.txt"),
    ("opencv-python", "cv2", "requirements-full.txt"),
    ("SenseVoice-python", "sensevoice", "requirements-full.txt"),
    ("funasr", "funasr", "requirements-full.txt"),
)

TRANSLATION_MODEL_DIR = Path("translation") / "nllb-200-distilled-600M-ct2-int8"
TRANSLATION_TOKENIZER_DIR = Path("translation") / "nllb-200-distilled-600M-tokenizer"
TRANSLATION_MODEL_FILES = ("model.bin", "config.json")
TRANSLATION_TOKENIZER_FILES = ("tokenizer.json", "sentencepiece.bpe.model")

SENSEVOICE_DIR = Path("speech") / "sensevoice_onnx_int8"
SENSEVOICE_FILES = (
    "am.mvn",
    "embedding.npy",
    "chn_jpn_yue_eng_ko_spectok.bpe.model",
    "sense-voice-encoder-int8.onnx",
    "fsmn-am.mvn",
    "fsmn-config.yaml",
    "fsmnvad-offline.onnx",
)

FUNASR_DIR = Path("speech") / "paraformer_zh_streaming"
FUNASR_FILES = (
    "am.mvn",
    "config.yaml",
    "configuration.json",
    "model.pt",
    "seg_dict",
    "tokens.json",
)

AUTO_CUTOUT_MODELS = {
    "BEN2": (Path("LX") / "auto_cutout" / "BEN2", ("BEN2.py",), ("BEN2_Base.pth",)),
    "RMBG-2.0": (
        Path("LX") / "auto_cutout" / "RMBG-2.0",
        ("birefnet.py", "BiRefNet_config.py", "config.json"),
        ("model.safetensors", "pytorch_model.bin"),
    ),
    "InSPyReNet": (Path("LX") / "auto_cutout" / "InSPyReNet", (), ("ckpt_base.pth",)),
    "BiRefNet-Matting": (
        Path("LX") / "auto_cutout" / "BiRefNet-Matting",
        ("birefnet.py", "BiRefNet_config.py", "config.json"),
        ("BiRefNet-matting.safetensors",),
    ),
    "BiRefNet-Dynamic": (
        Path("LX") / "auto_cutout" / "BiRefNet-Dynamic",
        ("birefnet.py", "BiRefNet_config.py", "config.json"),
        ("BiRefNet_dynamic.safetensors",),
    ),
}

SAM3_CHECKPOINT_CANDIDATES = (
    Path("LX") / "semantic_cutout" / "sam3.1_multiplex.pt",
    Path("SAM3") / "sam3.1_multiplex.pt",
    Path("sam3") / "sam3.1_multiplex.pt",
)
SAM3_BPE_CANDIDATES = (
    Path("LX") / "semantic_cutout" / "assets" / "bpe_simple_vocab_16e6.txt.gz",
    Path("LX") / "semantic_cutout" / "bpe_simple_vocab_16e6.txt.gz",
    Path("SAM3") / "assets" / "bpe_simple_vocab_16e6.txt.gz",
    Path("SAM3") / "bpe_simple_vocab_16e6.txt.gz",
    Path("sam3") / "assets" / "bpe_simple_vocab_16e6.txt.gz",
    Path("sam3") / "bpe_simple_vocab_16e6.txt.gz",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _custom_nodes_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cmd_arg(value: object) -> str:
    return f'"{value}"'


def _requirements_command(filename: str) -> str:
    return f"{_cmd_arg(sys.executable)} -m pip install -r {_cmd_arg(_repo_root() / filename)}"


def _upgrade_pip_command() -> str:
    return f"{_cmd_arg(sys.executable)} -m pip install --upgrade pip"


def _sam3_install_command() -> str:
    return f'{_cmd_arg(sys.executable)} -m pip install -e "D:\\path\\to\\official\\sam3"'


def _models_root() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.models_dir)
    except Exception:
        return Path(__file__).resolve().parents[4] / "models"


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _module_origin(module_name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return None
    origin = getattr(spec, "origin", None)
    if not origin or origin in {"built-in", "namespace"}:
        return None
    try:
        return Path(origin).resolve()
    except Exception:
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _package_version(package_name: str) -> str:
    candidates = {
        "Pillow": ("Pillow",),
        "opencv-python": ("opencv-python", "opencv-contrib-python", "opencv-python-headless"),
        "transparent-background": ("transparent-background",),
        "SenseVoice-python": ("SenseVoice-python", "sensevoice"),
    }.get(package_name, (package_name,))
    for candidate in candidates:
        try:
            return importlib.metadata.version(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue
        except Exception:
            continue
    return ""


def _dependency_status(name: str, module_name: str, install_group: str) -> dict[str, Any]:
    ok = _module_available(module_name)
    origin = _module_origin(module_name) if ok else None
    return {
        "name": name,
        "module": module_name,
        "install_group": install_group,
        "ok": ok,
        "version": _package_version(name) if ok else "",
        "origin": str(origin) if origin else "",
    }


def _dependency_line(status: dict[str, Any]) -> str:
    if status["ok"]:
        suffix = f" {status['version']}" if status.get("version") else ""
        return f"[OK] {status['name']}{suffix}"
    return f"[缺失] {status['name']} - 安装 {status['install_group']}"


def _has_files(directory: Path, filenames: tuple[str, ...]) -> bool:
    return all((directory / filename).is_file() for filename in filenames)


def _missing_files(directory: Path, filenames: tuple[str, ...]) -> list[str]:
    return [filename for filename in filenames if not (directory / filename).is_file()]


def _find_existing(root: Path, candidates: tuple[Path, ...]) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.is_file():
            return path
    return None


def _model_status(name: str, directory: Path, required: tuple[str, ...]) -> dict[str, Any]:
    missing = _missing_files(directory, required)
    return {
        "name": name,
        "directory": str(directory),
        "status": "ok" if not missing else "missing",
        "ready": not missing,
        "missing": missing,
    }


def _model_line(status: dict[str, Any]) -> str:
    if status["ready"]:
        return f"[OK] {status['name']}: {status['directory']}"
    missing = ", ".join(status.get("missing", [])[:4])
    return f"[缺失] {status['name']}: {status['directory']}，缺少 {missing}"


def _auto_cutout_status(
    root: Path,
    name: str,
    directory_rel: Path,
    required: tuple[str, ...],
    weights: tuple[str, ...],
) -> dict[str, Any]:
    directory = root / directory_rel
    required_missing = _missing_files(directory, required) if required else []
    weight_ok = any((directory / filename).is_file() for filename in weights)
    missing_parts = list(required_missing)
    if not weight_ok:
        missing_parts.append("权重文件(" + " 或 ".join(weights) + ")")

    if not required_missing and weight_ok:
        status = "ok"
        severity = "ok"
    elif not directory.exists():
        status = "optional_missing"
        severity = "optional"
    else:
        status = "incomplete"
        severity = "warning"

    return {
        "name": name,
        "directory": str(directory),
        "status": status,
        "severity": severity,
        "ready": status == "ok",
        "missing": missing_parts,
    }


def _auto_cutout_line(status: dict[str, Any]) -> str:
    if status["status"] == "ok":
        return f"[OK] {status['name']}: {status['directory']}"
    if status["status"] == "optional_missing":
        return f"[可按需下载] {status['name']}: {status['directory']}"
    missing = ", ".join(status.get("missing", [])[:5])
    return f"[不完整] {status['name']}: {status['directory']}，缺少 {missing}"


def _sam3_package_status() -> dict[str, Any]:
    origin = _module_origin("sam3")
    custom_nodes_root = _custom_nodes_root()
    if origin is None:
        return {
            "status": "missing",
            "severity": "error",
            "ok": False,
            "origin": "",
            "message": "语义抠图需要额外安装官方 sam3 Python 包。",
        }
    if _is_relative_to(origin, custom_nodes_root):
        return {
            "status": "custom_nodes_origin",
            "severity": "warning",
            "ok": False,
            "origin": str(origin),
            "message": "sam3 来自 custom_nodes，建议安装官方 sam3 到当前 Python 环境，避免复用其他插件内置包。",
        }
    return {
        "status": "ok",
        "severity": "ok",
        "ok": True,
        "origin": str(origin),
        "message": "sam3 已安装在当前 Python 环境。",
    }


def _sam3_package_line(status: dict[str, Any]) -> str:
    if status["status"] == "ok":
        return f"[OK] sam3 已安装在当前 Python 环境: {status['origin']}"
    if status["status"] == "custom_nodes_origin":
        return f"[注意] sam3 来自 custom_nodes: {status['origin']}；建议安装官方 sam3 到当前 Python 环境"
    return "[缺失] sam3 - 语义抠图需要额外安装官方 sam3 包"


def _section(title: str, lines: list[str]) -> list[str]:
    return ["", f"## {title}", *lines]


def _missing_names(items: list[dict[str, Any]]) -> list[str]:
    return [item["name"] for item in items if not item.get("ok", item.get("ready", False))]


class LXEnvironmentDiagnostics:
    """Report LX dependency and model readiness without downloading anything."""

    CATEGORY = LX_UTILITY_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "环境诊断", "依赖诊断", "模型诊断", "diagnostics"]
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("报告", "report_json")
    FUNCTION = "diagnose"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "检查高级依赖": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "关闭后只检查基础信息、基础依赖和模型目录。",
                    },
                ),
                "检查模型文件": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "只检查本地文件是否存在，不会下载模型。",
                    },
                ),
            }
        }

    def diagnose(self, 检查高级依赖=True, 检查模型文件=True):
        models_root = _models_root()
        repo_root = _repo_root()

        basic_dependencies = [
            _dependency_status(name, module_name, install_group)
            for name, module_name, install_group in BASIC_DEPENDENCIES
        ]
        full_dependencies = [
            _dependency_status(name, module_name, install_group)
            for name, module_name, install_group in FULL_DEPENDENCIES
        ] if 检查高级依赖 else []

        missing_basic = _missing_names(basic_dependencies)
        missing_full = _missing_names(full_dependencies)
        sam3_status = _sam3_package_status()

        commands: list[dict[str, str]] = []
        if missing_basic:
            commands.append({
                "title": "安装基础依赖",
                "command": _requirements_command("requirements.txt"),
                "reason": "基础节点依赖缺失。",
            })
        if missing_full:
            commands.append({
                "title": "安装高级依赖",
                "command": _requirements_command("requirements-full.txt"),
                "reason": "离线翻译、自动抠图、语音识别等高级功能依赖缺失。",
            })
        if missing_basic or missing_full:
            commands.append({
                "title": "可选：先升级 pip",
                "command": _upgrade_pip_command(),
                "reason": "pip 太旧时可以先执行这一条，再重新安装依赖。",
            })
        if not sam3_status["ok"]:
            commands.append({
                "title": "安装官方 sam3",
                "command": _sam3_install_command(),
                "reason": "把 D:\\path\\to\\official\\sam3 替换成官方 sam3 源码目录。",
            })

        model_payload: dict[str, Any] = {}
        model_actions: list[str] = []
        model_issue_count = 0

        if 检查模型文件:
            translation_dir = models_root / TRANSLATION_MODEL_DIR
            tokenizer_dirs = (translation_dir, models_root / TRANSLATION_TOKENIZER_DIR)
            tokenizer_found = next(
                (path for path in tokenizer_dirs if _has_files(path, TRANSLATION_TOKENIZER_FILES)),
                None,
            )
            translation_model = _model_status("离线翻译 CTranslate2 模型", translation_dir, TRANSLATION_MODEL_FILES)
            translation_tokenizer = {
                "name": "离线翻译 tokenizer",
                "directory": str(tokenizer_found or translation_dir),
                "fallback_directory": str(models_root / TRANSLATION_TOKENIZER_DIR),
                "status": "ok" if tokenizer_found else "missing",
                "ready": tokenizer_found is not None,
                "missing": [] if tokenizer_found else list(TRANSLATION_TOKENIZER_FILES),
            }
            translation_models = [translation_model, translation_tokenizer]

            speech_models = [
                _model_status("SenseVoice ONNX", models_root / SENSEVOICE_DIR, SENSEVOICE_FILES),
                _model_status("FunASR streaming", models_root / FUNASR_DIR, FUNASR_FILES),
            ]
            auto_cutout_models = [
                _auto_cutout_status(models_root, name, directory, required, weights)
                for name, (directory, required, weights) in AUTO_CUTOUT_MODELS.items()
            ]

            checkpoint = _find_existing(models_root, SAM3_CHECKPOINT_CANDIDATES)
            bpe = _find_existing(models_root, SAM3_BPE_CANDIDATES)
            sam3_resources = {
                "checkpoint": {
                    "name": "SAM3.1 权重",
                    "status": "ok" if checkpoint else "missing",
                    "ready": checkpoint is not None,
                    "path": str(checkpoint) if checkpoint else "",
                    "filename": "sam3.1_multiplex.pt",
                },
                "bpe": {
                    "name": "SAM3 BPE 词表",
                    "status": "ok" if bpe else "missing",
                    "ready": bpe is not None,
                    "path": str(bpe) if bpe else "",
                    "filename": "bpe_simple_vocab_16e6.txt.gz",
                },
                "recommended_directory": str(models_root / "LX" / "semantic_cutout"),
            }

            model_payload = {
                "translation": translation_models,
                "speech": speech_models,
                "auto_cutout": auto_cutout_models,
                "sam3_resources": sam3_resources,
            }

            for item in [*translation_models, *speech_models]:
                if not item["ready"]:
                    model_issue_count += 1
                    model_actions.append(f"{item['name']}：请补齐到 {item['directory']}")
            for item in auto_cutout_models:
                if item["status"] == "incomplete":
                    model_issue_count += 1
                    model_actions.append(f"{item['name']}：目录已存在但不完整，请补齐 {', '.join(item['missing'][:5])}")
            if not sam3_resources["checkpoint"]["ready"]:
                model_issue_count += 1
                model_actions.append(
                    f"SAM3.1 权重：请放到 {models_root / 'LX' / 'semantic_cutout' / 'sam3.1_multiplex.pt'}"
                )
            if not sam3_resources["bpe"]["ready"]:
                model_issue_count += 1
                model_actions.append(
                    f"SAM3 BPE 词表：请放到 {models_root / 'LX' / 'semantic_cutout' / 'assets' / 'bpe_simple_vocab_16e6.txt.gz'}"
                )

        summary_lines = []
        if missing_basic:
            summary_lines.append(f"[需要处理] 基础依赖缺失：{', '.join(missing_basic)}。")
        else:
            summary_lines.append("[OK] 基础依赖完整，基础节点可用。")

        if 检查高级依赖:
            if missing_full:
                summary_lines.append(f"[需要处理] 高级依赖缺失：{', '.join(missing_full)}。")
            else:
                summary_lines.append("[OK] 高级依赖完整。")
        else:
            summary_lines.append("[跳过] 未检查高级依赖。")

        if sam3_status["status"] == "ok":
            summary_lines.append("[OK] 官方 sam3 Python 包可用。")
        elif sam3_status["status"] == "custom_nodes_origin":
            summary_lines.append("[注意] sam3 来自 custom_nodes，语义抠图建议改为安装官方 sam3 包。")
        else:
            summary_lines.append("[需要处理] 语义抠图缺少官方 sam3 Python 包。")

        if 检查模型文件:
            if model_issue_count:
                summary_lines.append(f"[需要处理] 有 {model_issue_count} 处模型/资源文件缺失或不完整。")
            else:
                summary_lines.append("[OK] 已检查的模型/资源文件完整。")
        else:
            summary_lines.append("[跳过] 未检查模型文件。")

        environment = {
            "python": sys.executable,
            "python_version": platform.python_version(),
            "system": platform.platform(),
            "repo_root": str(repo_root),
            "models_root": str(models_root),
            "HF_ENDPOINT": os.environ.get("HF_ENDPOINT", "") or "未设置",
            "LX_TRANSLATION_HF_ENDPOINTS": os.environ.get("LX_TRANSLATION_HF_ENDPOINTS", "") or "未设置",
        }
        payload = {
            "type": "lx_environment_diagnostics",
            "version": 2,
            "ok": not missing_basic,
            "basic_dependencies_ok": not missing_basic,
            "advanced_dependencies_ok": not missing_full if 检查高级依赖 else None,
            "model_resources_checked": bool(检查模型文件),
            "model_issue_count": model_issue_count if 检查模型文件 else None,
            "summary": summary_lines,
            "environment": environment,
            "dependencies": {
                "basic": basic_dependencies,
                "advanced": full_dependencies,
            },
            "sam3": sam3_status,
            "models": model_payload,
            "commands": commands,
            "model_actions": model_actions,
        }

        lines: list[str] = [
            "# 灵犀环境诊断",
            "",
            *summary_lines,
            "",
            "## CMD 修复命令",
        ]
        if commands:
            for item in commands:
                lines.extend([
                    f"- {item['title']}：{item['reason']}",
                    f"  {item['command']}",
                ])
        else:
            lines.append("- 未发现需要通过 pip 安装修复的依赖。")

        if 检查模型文件:
            lines.extend(["", "## 模型/资源处理"])
            if model_actions:
                lines.extend([f"- {action}" for action in model_actions])
            else:
                lines.append("- 已检查的模型文件完整，不需要处理。")
            lines.append("- 模型文件不是 pip 依赖；本节点只检查状态，不会下载或移动文件。")

        lines.extend(_section("环境", [
            f"- Python: {environment['python']}",
            f"- Python 版本: {environment['python_version']}",
            f"- 系统: {environment['system']}",
            f"- 插件目录: {environment['repo_root']}",
            f"- ComfyUI models 目录: {environment['models_root']}",
            f"- HF_ENDPOINT: {environment['HF_ENDPOINT']}",
            f"- LX_TRANSLATION_HF_ENDPOINTS: {environment['LX_TRANSLATION_HF_ENDPOINTS']}",
        ]))

        lines.extend(_section("基础依赖", [_dependency_line(item) for item in basic_dependencies]))

        if 检查高级依赖:
            lines.extend(_section("高级依赖", [_dependency_line(item) for item in full_dependencies]))

        lines.extend(_section("SAM3 Python 包", [
            _sam3_package_line(sam3_status),
        ]))

        if 检查模型文件 and model_payload:
            translation_lines = [_model_line(item) for item in model_payload["translation"]]
            tokenizer = model_payload["translation"][1]
            if not tokenizer["ready"]:
                translation_lines[-1] = (
                    f"[缺失] 离线翻译 tokenizer: 请放到 {tokenizer['directory']} "
                    f"或 {tokenizer['fallback_directory']}"
                )
            lines.extend(_section("离线翻译模型", translation_lines))

            lines.extend(_section("语音模型", [
                _model_line(item) for item in model_payload["speech"]
            ]))

            lines.extend(_section("自动抠图模型", [
                _auto_cutout_line(item) for item in model_payload["auto_cutout"]
            ]))

            sam3_resources = model_payload["sam3_resources"]
            lines.extend(_section("SAM3.1 语义抠图资源", [
                f"[OK] SAM3.1 权重: {sam3_resources['checkpoint']['path']}"
                if sam3_resources["checkpoint"]["ready"]
                else "[缺失] SAM3.1 权重 sam3.1_multiplex.pt",
                f"[OK] SAM3 BPE 词表: {sam3_resources['bpe']['path']}"
                if sam3_resources["bpe"]["ready"]
                else "[缺失] SAM3 BPE 词表 bpe_simple_vocab_16e6.txt.gz",
                f"推荐目录: {sam3_resources['recommended_directory']}",
            ]))

        lines.extend(_section("说明", [
            "基础节点异常时，优先执行 requirements.txt 安装命令。",
            "离线翻译、自动抠图、语音识别缺依赖时，执行 requirements-full.txt 安装命令。",
            "语义抠图除了 requirements-full.txt，还需要官方 sam3 包、SAM3.1 权重和 BPE 词表。",
            "执行安装命令后请重启 ComfyUI，再重新运行本节点确认状态。",
            "本节点只检查状态，不会下载、转换模型，也不会修改环境。",
        ]))

        return ("\n".join(lines), json.dumps(payload, ensure_ascii=False, indent=2))
