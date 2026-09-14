from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from tools.repo_lint import run


class RepoLintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def tearDown(self):
        self.temporary.cleanup()

    def track(self, relative: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", "--", relative], cwd=self.root, check=True)

    def test_safe_example_files_pass(self):
        self.track(".env.example")
        self.track("services/api/.env.test.example")

        self.assertEqual([], run(self.root))

    def test_tracked_local_environment_files_fail(self):
        self.track(".env")
        self.track("services/api/.env.local")

        errors = run(self.root)

        self.assertTrue(any(error.startswith(".env:") for error in errors))
        self.assertTrue(any("services/api/.env.local" in error for error in errors))

    def test_tracked_macos_metadata_fails(self):
        self.track("assets/.DS_Store")

        self.assertTrue(any("assets/.DS_Store" in error for error in run(self.root)))

    def test_tracked_python_runtime_cache_fails(self):
        self.track("tests/__pycache__/test_example.cpython-314.pyc")

        self.assertTrue(any("tracked Python runtime cache" in error for error in run(self.root)))

    def test_untracked_local_file_is_outside_repository_validation(self):
        (self.root / ".env").write_text("local only\n", encoding="utf-8")

        self.assertEqual([], run(self.root))

    def test_detrouble_os_records_fail(self):
        self.track("knowledge/episodes/owner-correction.json")
        self.track("knowledge/inbox/KNOW-EXAMPLE.md")
        self.track("knowledge/receipts/CLOSEOUT-EXAMPLE.json")
        self.track("planning/OGSM.md")

        errors = run(self.root)

        self.assertEqual(4, len(errors))
        self.assertTrue(all("OS Knowledge or Planning artifact" in error for error in errors))

    def test_product_folders_with_generic_names_remain_allowed(self):
        self.track("knowledge/articles/getting-started.md")
        self.track("planning-engine/src/index.ts")

        self.assertEqual([], run(self.root))


if __name__ == "__main__":
    unittest.main()
