"""Lightweight checks for ComfyUI-LX-Nodes.

This script avoids importing ComfyUI-only modules. It checks Python syntax,
JSON files, static node key duplicates, optional JS syntax via node, tracked
private runtime files, and common secret-looking strings.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from build_release import collect_files, validate_third_party


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", ".codex_tmp", ".pytest_cache", ".mypy_cache", "node_modules", ".vs", "dist", ".venv", "venv", "build"}
RUNTIME_DIRS = (
    ROOT / "_plugins" / "utility" / "qwen3vl_cache",
    ROOT / "_plugins" / "utility" / "qwen_text_cache",
    ROOT / "_plugins" / "lingxi_concurrent_bridge" / "cache",
    ROOT / "_plugins" / "lingxi_task_queue" / "cache",
)
PRIVATE_PATHS = (
    ".env",
    ".env.local",
    ".env.production",
    ".codex_tmp",
    ".vs",
    "dist",
    "_plugins/_shared/relay_config.local.json",
    "_plugins/_shared/relay_config.local.json.tmp",
    "_plugins/_shared/relay_config.local.json.broken",
    "_plugins/_shared/relay_config.json",
    "_plugins/lingxi_bridge/relay_config.local.json",
    "_plugins/lingxi_bridge/relay_config.local.json.tmp",
    "_plugins/lingxi_bridge/relay_config.local.json.broken",
    "_plugins/lingxi_bridge/relay_config.json",
    "_plugins/utility/qwen3vl_cache",
    "_plugins/utility/qwen_text_cache",
    "_plugins/lingxi_concurrent_bridge/cache",
    "_plugins/lingxi_task_queue/cache",
)
USER_DOCS_REQUIRED_PATTERNS = (
    ("docs/USAGE.md", "usage guide"),
    ("docs/OPEN_SOURCE_REVIEW.md", "authorization review list"),
    ("docs/RELEASING.md", "release instructions"),
    ("examples/text_basic.json", "basic example workflow"),
    ("_plugins/imagebatch", "integrated folder image nodes"),
    ("_plugins/prompt_batch", "integrated TXT series nodes"),
    ("_plugins/lingxi_bridge", "integrated relay nodes"),
    ("_plugins/lingxi_bridge/relay_config.local.json", "relay local config path"),
    ("_plugins/_shared/relay_config.example.json", "shared config example path"),
    ("_plugins/_shared/relay_config.local.json", "shared local config path"),
    ("sam3.1_multiplex.pt", "SAM3 checkpoint note"),
    ("bpe_simple_vocab_16e6.txt.gz", "SAM3 BPE note"),
    ("requirements-full.txt", "advanced dependency install note"),
    ("灵犀环境诊断", "environment diagnostics node"),
    ("动态输出", "dynamic prompt splitter note"),
    ("动态增删 IMAGE 输入/输出端口", "dynamic image resize note"),
)
RELEASE_ADVISORY_PATHS = (
    "LICENSE",
    "NOTICE",
    "licenses",
    "third_party.json",
    "release.json",
    "CONTRIBUTING.md",
    "tools",
    "examples",
    ".github",
    "docs/OPEN_SOURCE_REVIEW.md",
    "docs/RELEASING.md",
    "tests",
    "_plugins/imagebatch",
    "_plugins/prompt_batch",
    "_plugins/lingxi_bridge",
    "_plugins/lingxi_concurrent_bridge",
    "_plugins/lingxi_task_queue",
    "_plugins/lingxi_folder_batch",
    "_plugins/aihubmix_seedream",
    "web/imagebatch",
    "web/prompt_batch",
    "web/lingxi_bridge",
    "web/lingxi_concurrent_bridge",
    "web/lingxi_task_queue",
    "web/lingxi_folder_batch",
    "web/aihubmix_seedream",
    "CHANGELOG.md",
    "requirements-full.txt",
    "_plugins/_shared",
    "_plugins/auto_cutout",
    "_plugins/categories.py",
    "_plugins/global_input",
    "_plugins/group_control",
    "_plugins/image_edit",
    "_plugins/set_get",
    "_plugins/speech_tools",
    "_plugins/translation_tools",
    "_plugins/utility/any_switch.py",
    "_plugins/utility/boolean_select.py",
    "_plugins/utility/memory_release.py",
    "_plugins/utility/qwen3vl_reverse.py",
    "_plugins/utility/select_switch.py",
    "_plugins/utility/show_text.py",
    "docs/ADOPTED_PLUGINS.md",
    "web/auto_cutout.js",
    "web/global_input",
    "web/group_control",
    "web/image_compression",
    "web/image_edit",
    "web/meta_node",
    "web/set_get",
    "web/speech_tools",
    "web/translation_tools",
    "web/utility",
    "web/workflow_organizer",
)
SECRET_SCAN_EXTS = {".py", ".js", ".json", ".md", ".txt", ".yml", ".yaml"}
SECRET_PATTERNS = (
    ("openai-like-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{30,}\b")),
)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _skip_path(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return True
    try:
        rel = _rel(path)
    except ValueError:
        rel = ""
    if any(rel == private_path or rel.startswith(private_path.rstrip("/") + "/") for private_path in PRIVATE_PATHS):
        return True
    return any(_is_relative_to(path, runtime_dir) for runtime_dir in RUNTIME_DIRS)


def check_python_compile() -> bool:
    ok = True
    for path in sorted(ROOT.rglob("*.py")):
        if _skip_path(path):
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:
            print(f"[python] {_rel(path)}: {exc}")
            ok = False
    return ok


def check_json_files() -> bool:
    ok = True
    for path in sorted(ROOT.rglob("*.json")):
        if _skip_path(path):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[json] {_rel(path)}: {exc}")
            ok = False
    return ok


def _literal_mapping_keys(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "NODE_CLASS_MAPPINGS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _literal_node_mappings(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mappings: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "NODE_CLASS_MAPPINGS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Name)
            ):
                mappings.append((key.value, value.id))
    return mappings


def _literal_class_attr(
    class_name: str,
    classes: dict[str, ast.ClassDef],
    attr_name: str,
    seen: set[str] | None = None,
) -> object:
    seen = seen or set()
    if class_name in seen:
        return None
    seen.add(class_name)
    node = classes.get(class_name)
    if node is None:
        return None

    for stmt in node.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == attr_name for t in stmt.targets):
            continue
        try:
            return ast.literal_eval(stmt.value)
        except Exception:
            return None

    for base in node.bases:
        if isinstance(base, ast.Name):
            value = _literal_class_attr(base.id, classes, attr_name, seen)
            if value is not None:
                return value
    return None


def check_node_key_duplicates() -> bool:
    seen: dict[str, str] = {}
    ok = True
    for init_file in sorted((ROOT / "_plugins").glob("*/__init__.py")):
        for key in sorted(_literal_mapping_keys(init_file)):
            owner = init_file.parent.name
            if key in seen:
                print(f"[node-key] duplicate {key!r}: {seen[key]} and {owner}")
                ok = False
            else:
                seen[key] = owner
    return ok


def check_search_aliases() -> bool:
    required = {"lx", "LX", "灵犀"}
    classes: dict[str, ast.ClassDef] = {}
    mappings: list[tuple[str, str, str]] = []

    for path in sorted(ROOT.rglob("*.py")):
        if _skip_path(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
        for node_key, class_name in _literal_node_mappings(path):
            mappings.append((_rel(path), node_key, class_name))

    ok = True
    checked: set[tuple[str, str]] = set()
    for path, node_key, class_name in mappings:
        identity = (node_key, class_name)
        if identity in checked:
            continue
        checked.add(identity)
        aliases = _literal_class_attr(class_name, classes, "SEARCH_ALIASES")
        alias_set = set(aliases or []) if isinstance(aliases, (list, tuple)) else set()
        missing = sorted(required - alias_set)
        if missing:
            print(f"[search-aliases] {node_key!r} ({class_name}, {path}) missing: {', '.join(missing)}")
            ok = False
    return ok


def check_private_files_untracked() -> bool:
    git = shutil.which("git")
    if not git:
        print("[private-files] git not found; skipped")
        return True

    result = subprocess.run(
        [git, "ls-files", "--", *PRIVATE_PATHS],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print("[private-files] git ls-files failed; skipped")
        if result.stderr:
            print(result.stderr.rstrip())
        return True

    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if tracked:
        for path in tracked:
            print(f"[private-files] tracked runtime/private path: {path}")
        return False
    return True


def check_secret_patterns() -> bool:
    ok = True
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or _skip_path(path) or path.suffix.lower() not in SECRET_SCAN_EXTS:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    print(f"[secret] possible {name}: {_rel(path)}:{line_no}")
                    ok = False
    return ok


def check_documentation_drift() -> bool:
    readme = ROOT / "README.md"
    guide = ROOT / "docs" / "USAGE.md"
    if not readme.is_file() or not guide.is_file():
        print("[docs] README.md or docs/USAGE.md missing")
        return False

    text = readme.read_text(encoding="utf-8") + "\n" + guide.read_text(encoding="utf-8")
    ok = True
    for pattern, reason in USER_DOCS_REQUIRED_PATTERNS:
        if pattern not in text:
            print(f"[docs] User documentation missing {reason}: {pattern}")
            ok = False
    return ok


def check_dynamic_output_cleanup() -> bool:
    checks = (
        (
            ROOT / "_plugins" / "prompt_tools" / "lx_prompt_splitter.py",
            (
                ("for index in range(MAX_PROMPT_OUTPUTS)", "prompt splitter still fills the old fixed output count"),
            ),
        ),
        (
            ROOT / "_plugins" / "image_compression" / "nodes.py",
            (
                ("blank_image = torch.zeros", "multi resize still creates blank placeholder outputs"),
                ("for index in range(1, MAX_RESIZE_ROUTES + 1)", "multi resize still loops over the old fixed route count"),
            ),
        ),
    )
    ok = True
    for path, patterns in checks:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, reason in patterns:
            if pattern in text:
                print(f"[dynamic-output] {reason}: {_rel(path)}")
                ok = False
    return ok


def check_release_git_advisory() -> bool:
    git = shutil.which("git")
    if not git:
        print("[release] git not found; skipped")
        return True

    result = subprocess.run(
        [git, "ls-files", "--others", "--exclude-standard", "--", *RELEASE_ADVISORY_PATHS],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print("[release] git ls-files failed; skipped")
        if result.stderr:
            print(result.stderr.rstrip())
        return True

    untracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if untracked:
        examples = ", ".join(untracked[:12])
        extra = len(untracked) - min(12, len(untracked))
        suffix = f", +{extra} more" if extra > 0 else ""
        print(
            "[release] advisory: likely release files are untracked; "
            "git/manager releases will miss them until staged/tracked: "
            f"{examples}{suffix}"
        )
    return True


def check_global_input_mirror_drift() -> bool:
    """Advisory only: duplicated global_input front-end files should not drift."""
    web_dir = ROOT / "web" / "global_input"
    plugin_dir = ROOT / "_plugins" / "global_input" / "js"
    if not web_dir.is_dir() or not plugin_dir.is_dir():
        return True

    web_files = {
        path.relative_to(web_dir).as_posix(): path
        for path in web_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".js", ".css"}
    }
    plugin_files = {
        path.relative_to(plugin_dir).as_posix(): path
        for path in plugin_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".js", ".css"}
    }
    names = sorted(set(web_files) | set(plugin_files))
    missing = [name for name in names if name not in web_files or name not in plugin_files]
    changed = [
        name
        for name in names
        if name in web_files and name in plugin_files and web_files[name].read_bytes() != plugin_files[name].read_bytes()
    ]

    if missing or changed:
        examples = ", ".join((missing + changed)[:8])
        extra = len(missing) + len(changed) - min(8, len(missing) + len(changed))
        suffix = f", +{extra} more" if extra > 0 else ""
        print(
            "[mirror] advisory: web/global_input and _plugins/global_input/js differ "
            f"({len(missing)} missing, {len(changed)} changed): {examples}{suffix}"
        )
    return True


def _frontend_text_for_mirror_compare(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(
        r'import \{ app \} from "[./]+scripts/app\.js";',
        'import { app } from "__COMFY_APP__";',
        text,
        count=1,
    )


def check_group_control_mirror_drift() -> bool:
    """Advisory only: active group_control mirror may differ by import depth."""
    web_file = ROOT / "web" / "group_control" / "group_control.js"
    plugin_file = ROOT / "_plugins" / "group_control" / "web" / "js" / "group_control.js"
    if not web_file.is_file() or not plugin_file.is_file():
        return True

    if _frontend_text_for_mirror_compare(web_file) != _frontend_text_for_mirror_compare(plugin_file):
        print(
            "[mirror] advisory: web/group_control/group_control.js and "
            "_plugins/group_control/web/js/group_control.js differ beyond import depth"
        )
    return True


def check_js_syntax() -> bool:
    node = shutil.which("node")
    if not node:
        print("[js] node not found; skipped")
        return True

    ok = True
    for path in sorted((ROOT / "web").rglob("*.js")):
        result = subprocess.run(
            [node, "--check", str(path)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[js] {_rel(path)}")
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip())
            ok = False
    return ok


def check_third_party_notices() -> bool:
    try:
        validate_third_party(ROOT, collect_files(ROOT))
    except (ValueError, OSError, KeyError) as exc:
        print(f"[licenses] {exc}")
        return False
    return True


def main() -> int:
    checks = [
        ("python compile", check_python_compile),
        ("json", check_json_files),
        ("node keys", check_node_key_duplicates),
        ("search aliases", check_search_aliases),
        ("private files", check_private_files_untracked),
        ("secret patterns", check_secret_patterns),
        ("documentation drift", check_documentation_drift),
        ("dynamic output cleanup", check_dynamic_output_cleanup),
        ("release git advisory", check_release_git_advisory),
        ("global_input mirror advisory", check_global_input_mirror_drift),
        ("group_control mirror advisory", check_group_control_mirror_drift),
        ("js syntax", check_js_syntax),
        ("third-party license retention", check_third_party_notices),
    ]
    failed = []
    for name, fn in checks:
        print(f"Checking {name}...")
        if not fn():
            failed.append(name)
    if failed:
        print("Failed checks: " + ", ".join(failed))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
