"""Release packaging must exclude local state and keep verifiable source bytes."""

from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lx_build_release", ROOT / "tools/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".codex_tmp" / "release-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
        self.write("README.md", "# Example\n")
        self.write("requirements.txt", "")
        self.write("docs/OPEN_SOURCE_REVIEW.md", "Pending review\n")
        self.write("release.json", json.dumps({
            "project": "ComfyUI-LX-Nodes", "version": "0.1.0-rc.1",
            "stage": "review", "authorization_review": "pending",
            "license": None, "runtime_validation": "pending",
        }))
        self.write("_plugins/example/__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
        self.write("_plugins/example/relay_config.example.json", "{}\n")
        self.write("_plugins/example/relay_config.local.json", "sk-" + "A" * 24)
        self.write("_plugins/example/relay_config.json", "private data")
        self.write("_plugins/example/relay_config.local.json.broken", "private data")
        self.write("_plugins/utility/qwen_text_cache/result.json", "private response")
        self.write("_plugins/example/__pycache__/example.pyc", "bytecode")
        self.write(".codex_tmp/backup.py", "backup")
        self.write(".env", "private environment")
        self.write("dist/old.zip", "old release")
        self.write("web/example/ui.js", "export const title = 'hello';\n")
        self.history_patch = patch.object(release, "scan_git_history", return_value={"status": "passed", "scanned_blobs": 1, "findings": []})
        self.history_patch.start()
        self.addCleanup(self.history_patch.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def build(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return release.build_archive(self.root, **kwargs)

    def add_license_fixture(self):
        metadata = json.loads((self.root / "release.json").read_text())
        metadata["license"] = "GPL-3.0-only"
        self.write("release.json", json.dumps(metadata))
        self.write("LICENSE", "Test source license\n")
        self.write("NOTICE", "Test attribution\n")
        self.write("licenses/upstream.txt", "Test upstream permission\n")
        self.write("web/example/ui.js", "// Derived from test upstream\nexport const title = 'hello';\n")
        self.write("third_party.json", json.dumps({"components": [{
            "license_file": "licenses/upstream.txt",
            "license_sha256_lf": hashlib.sha256(b"Test upstream permission\n").hexdigest(),
            "paths": ["web/example/ui.js"],
            "header_marker": "Derived from test upstream",
        }]}))

    def test_private_files_excluded_and_source_bytes_preserved(self):
        archive = self.build()
        manifest = release.verify_archive(archive)
        names = {entry["path"] for entry in manifest["files"]}
        self.assertIn("_plugins/example/relay_config.example.json", names)
        self.assertIn("web/example/ui.js", names)
        self.assertFalse(any("cache" in name or "local.json" in name or name.endswith("relay_config.json") for name in names))
        self.assertEqual(manifest["distribution"], "private-review")
        self.assertFalse(manifest["public_release_ready"])
        with zipfile.ZipFile(archive) as zipped:
            for entry in manifest["files"]:
                self.assertEqual(zipped.read("ComfyUI-LX-Nodes/" + entry["path"]), (self.root / entry["path"]).read_bytes())
            self.assertTrue(all(name.startswith("ComfyUI-LX-Nodes/") for name in zipped.namelist()))
        self.assertEqual(archive.with_suffix(".zip.sha256").read_text().split()[0], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_same_sources_produce_same_archive(self):
        first = self.build().read_bytes()
        self.assertEqual(first, self.build().read_bytes())

    def test_review_cannot_be_built_as_public(self):
        with self.assertRaisesRegex(ValueError, "Public release blocked"):
            self.build(public=True)

    def test_source_secret_blocks_build_without_printing_value(self):
        secret = "sk-" + "B" * 24
        self.write("web/example/secret.js", "const key = '" + secret + "';\n")
        log = io.StringIO()
        with redirect_stderr(log), self.assertRaisesRegex(ValueError, "Possible credentials"):
            self.build()
        self.assertIn("web/example/secret.js:1", log.getvalue())
        self.assertNotIn(secret, log.getvalue())

    def test_unknown_runtime_resource_requires_review(self):
        self.write("_plugins/example/model.safetensors", "weights")
        with self.assertRaisesRegex(ValueError, "Unreviewed release file type"):
            self.build()

    def test_documentation_images_are_scoped_to_media(self):
        self.write("docs/media/example.png", "sample image bytes")
        manifest = release.verify_archive(self.build())
        self.assertIn("docs/media/example.png", {entry["path"] for entry in manifest["files"]})
        self.write("docs/unreviewed.png", "sample image bytes")
        with self.assertRaisesRegex(ValueError, "Unreviewed release file type"):
            self.build()

    def test_extra_archive_file_fails_verification(self):
        archive = self.build()
        with zipfile.ZipFile(archive, "a") as zipped:
            zipped.writestr("ComfyUI-LX-Nodes/unlisted.txt", "unexpected")
        with self.assertRaisesRegex(ValueError, "file list differs"):
            release.verify_archive(archive)

    def test_license_texts_and_notices_are_packaged(self):
        self.add_license_fixture()
        manifest = release.verify_archive(self.build())
        names = {entry["path"] for entry in manifest["files"]}
        self.assertTrue({"LICENSE", "NOTICE", "third_party.json", "licenses/upstream.txt"}.issubset(names))

    def test_changed_third_party_license_blocks_packaging(self):
        self.add_license_fixture()
        self.write("licenses/upstream.txt", "Replaced terms\n")
        with self.assertRaisesRegex(ValueError, "license text changed"):
            self.build()

    def test_removed_source_attribution_blocks_packaging(self):
        self.add_license_fixture()
        self.write("web/example/ui.js", "export const title = 'hello';\n")
        with self.assertRaisesRegex(ValueError, "attribution missing"):
            self.build()


if __name__ == "__main__":
    unittest.main()
