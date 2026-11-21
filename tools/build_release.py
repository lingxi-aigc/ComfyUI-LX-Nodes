"""Build and verify a source archive without local state or Git history."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "__init__.py", "README.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "requirements.txt", "requirements-full.txt", ".gitignore", ".gitattributes",
    "release.json", "LICENSE", "NOTICE", "third_party.json",
    "pyproject.toml",
}
FOLDERS = {
    "_plugins": {".py", ".js", ".css", ".md"},
    "web": {".js", ".css", ".md"},
    "tools": {".py"},
    "tests": {".py"},
    "docs": {".md"},
    "examples": {".json", ".md"},
    ".github": {".md", ".yml", ".yaml"},
    "licenses": {".txt", ".md"},
}
LOCAL_DIRS = {
    ".git", ".vs", ".cursor", ".codex", ".agents", ".codex_tmp", "dist",
    ".venv", "venv", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules",
    "cache", "models", "runtime",
}
SECRET_PATTERNS = (
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{30,}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{25,}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("aws-access-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)


def is_local(relative: Path) -> bool:
    return (
        any(part in LOCAL_DIRS or part.endswith("_cache") for part in relative.parts)
        or relative.name.startswith(".env")
        or ".local." in relative.name
        or relative.suffix in {".pyc", ".pyo", ".tmp", ".broken", ".log", ".pre-merge"}
        or (relative.name.startswith("relay_config") and relative.name != "relay_config.example.json")
    )


def collect_files(root: Path) -> list[Path]:
    files = []
    candidates = [root / name for name in ROOT_FILES if (root / name).exists()]
    for folder in FOLDERS:
        base = root / folder
        if base.is_symlink():
            raise ValueError(f"Symbolic links cannot be packaged: {folder}")
        if base.is_dir():
            candidates.extend(base.rglob("*"))
    for path in candidates:
        relative = path.relative_to(root)
        if is_local(relative):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Symbolic links cannot be packaged: {relative.as_posix()}")
        if not path.is_file():
            continue
        if len(relative.parts) > 1:
            allowed = path.suffix in FOLDERS[relative.parts[0]]
            allowed |= relative.parts[0] == "_plugins" and path.name.endswith(".example.json")
            allowed |= relative.parts[:2] == ("docs", "media") and path.suffix.lower() in {".png", ".webp"}
            if not allowed:
                raise ValueError(f"Unreviewed release file type: {relative.as_posix()}")
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def secret_findings(content: bytes, path: str) -> list[dict]:
    findings = []
    for number, line in enumerate(content.decode("utf-8", errors="replace").splitlines(), 1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({"path": path, "line": number, "kind": kind})
    return findings


def validate_third_party(root: Path, files: list[Path]) -> None:
    manifest_path = root / "third_party.json"
    if not manifest_path.is_file():
        metadata = json.loads((root / "release.json").read_text(encoding="utf-8"))
        if metadata.get("license"):
            raise ValueError("Declared source license requires third_party.json")
        return
    included = {p.relative_to(root).as_posix() for p in files}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for required in ("LICENSE", "NOTICE", "third_party.json"):
        if required not in included:
            raise ValueError(f"Required licensing file missing: {required}")
    for component in manifest["components"]:
        license_file = component["license_file"]
        if license_file not in included:
            raise ValueError(f"Required third-party license missing: {license_file}")
        data = (root / license_file).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != component["license_sha256_lf"]:
            raise ValueError(f"Third-party license text changed: {license_file}")
        for scope in component["paths"]:
            matched = [p for p in files if p.relative_to(root).as_posix() == scope or p.relative_to(root).as_posix().startswith(scope + "/")]
            if not matched:
                raise ValueError(f"Third-party source scope missing: {scope}")
            for source in matched:
                if source.suffix in {".js", ".css"} and component["header_marker"] not in source.read_text(encoding="utf-8")[:700]:
                    raise ValueError(f"Third-party attribution missing: {source.relative_to(root).as_posix()}")


def scan_git_history(root: Path) -> dict:
    """Inspect blobs reachable from local refs; never print matched values."""
    git = shutil.which("git")
    if not git:
        return {"status": "unavailable", "reason": "git not installed"}
    result = subprocess.run(
        [git, "rev-list", "--objects", "--all"], cwd=root,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        return {"status": "unavailable", "reason": "no readable local Git history"}
    objects = [line.split(" ", 1) for line in result.stdout.splitlines() if " " in line]
    if not objects:
        return {"status": "unavailable", "reason": "empty local Git history"}
    findings = []
    scanned = 0
    for oid, path in objects:
        kind = subprocess.run([git, "cat-file", "-t", oid], cwd=root, capture_output=True)
        if kind.returncode or kind.stdout.strip() != b"blob":
            continue
        blob = subprocess.run([git, "cat-file", "blob", oid], cwd=root, capture_output=True)
        if blob.returncode:
            return {"status": "unavailable", "reason": "Git blob read failed"}
        scanned += 1
        for finding in secret_findings(blob.stdout, path):
            findings.append({**finding, "blob": oid})
    return {"status": "findings" if findings else "passed", "scanned_blobs": scanned, "findings": findings}


def public_release_errors(root: Path, metadata: dict, files: list[Path], history: dict) -> list[str]:
    errors = []
    for field in ("authorization_review", "runtime_validation"):
        if metadata.get(field) != "complete":
            errors.append(f"{field} is not complete")
    if not metadata.get("license") or not (root / "LICENSE").is_file() or not (root / "LICENSE").read_text(encoding="utf-8").strip():
        errors.append("a confirmed license and nonempty LICENSE file are required")
    if metadata.get("stage") != "public":
        errors.append("release stage is not public")
    if history["status"] != "passed":
        errors.append("local Git history secret scan did not pass")
    git = shutil.which("git")
    result = subprocess.run([git, "ls-files", "-z"], cwd=root, capture_output=True) if git else None
    tracked = set(result.stdout.decode("utf-8").split("\0")) if result and result.returncode == 0 else set()
    untracked = [p.relative_to(root).as_posix() for p in files if p.relative_to(root).as_posix() not in tracked]
    if untracked:
        errors.append(f"{len(untracked)} release files are not tracked by Git")
    if git:
        changes = subprocess.run([git, "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True)
        if changes.returncode or changes.stdout.strip():
            errors.append("tracked changes must be committed before public release")
    return errors


def verify_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip():
            raise ValueError("Archive CRC check failed")
        manifest = json.loads(zipped.read("ComfyUI-LX-Nodes/RELEASE_MANIFEST.json"))
        expected = {"ComfyUI-LX-Nodes/" + entry["path"] for entry in manifest["files"]}
        expected.add("ComfyUI-LX-Nodes/RELEASE_MANIFEST.json")
        if len(zipped.namelist()) != len(expected) or set(zipped.namelist()) != expected:
            raise ValueError("Archive file list differs from the manifest")
        for entry in manifest["files"]:
            relative = Path(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or is_local(relative):
                raise ValueError("Private or unsafe archive path")
            data = zipped.read("ComfyUI-LX-Nodes/" + entry["path"])
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"Archive hash mismatch: {entry['path']}")
        return manifest


def build_archive(root: Path, *, public: bool = False) -> Path:
    metadata = json.loads((root / "release.json").read_text(encoding="utf-8"))
    version = metadata["version"]
    if metadata["project"] != "ComfyUI-LX-Nodes" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?", version):
        raise ValueError("Invalid release project or version")
    files = collect_files(root)
    required = {"__init__.py", "README.md", "release.json", "requirements.txt", "docs/OPEN_SOURCE_REVIEW.md"}
    if required - {p.relative_to(root).as_posix() for p in files}:
        raise ValueError("Required release files are missing")
    if metadata.get("license") and not {"LICENSE", "NOTICE", "third_party.json"}.issubset({p.relative_to(root).as_posix() for p in files}):
        raise ValueError("Declared source license requires LICENSE, NOTICE and third_party.json")
    validate_third_party(root, files)
    contents = [(p.relative_to(root).as_posix(), p.read_bytes()) for p in files]
    findings = [finding for path, data in contents for finding in secret_findings(data, path)]
    if findings:
        for finding in findings:
            print(f"[secret] {finding['path']}:{finding['line']} ({finding['kind']})", file=sys.stderr)
        raise ValueError("Possible credentials in release sources; inspect the reported locations")
    history = scan_git_history(root)
    errors = public_release_errors(root, metadata, files, history)
    if public and errors:
        raise ValueError("Public release blocked:\n- " + "\n- ".join(errors))
    manifest = {
        "project": metadata["project"], "version": version,
        "distribution": "public" if public else "private-review",
        "public_release_ready": not errors, "pending_items": errors,
        "git_history_scan": history,
        "files": [{"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for path, data in contents],
    }
    contents.append(("RELEASE_MANIFEST.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
    output = root / "dist"
    output.mkdir(exist_ok=True)
    archive = output / f"ComfyUI-LX-Nodes-v{version}{'' if public else '-review'}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path, data in contents:
            info = zipfile.ZipInfo("ComfyUI-LX-Nodes/" + path, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, data)
    verify_archive(temporary)
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Archive: {archive.name} ({len(files)} source files)")
    print(f"SHA256: {digest}")
    print(f"Local Git history scan: {history['status']}")
    if errors:
        print("Review archive only. Pending public release items:")
        for error in errors:
            print(f"- {error}")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", help="require completed release checks")
    args = parser.parse_args()
    check = subprocess.run([sys.executable, str(ROOT / "tools/check_project.py")], cwd=ROOT)
    if check.returncode:
        return check.returncode
    try:
        build_archive(ROOT, public=args.public)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
