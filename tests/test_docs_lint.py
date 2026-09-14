from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.docs_lint import DOC_BUCKETS, run


class DocsLintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "README.md").write_text("# Project\n\n[Docs](docs/index.md)\n")
        (self.root / "STATUS.md").write_text("# Status\n")
        for bucket in DOC_BUCKETS:
            (self.root / "docs" / bucket).mkdir(parents=True)
        (self.root / "docs" / "index.md").write_text(
            "# Documentation\n\n[Model](architecture/model.md#purpose)\n"
        )
        (self.root / "docs" / "architecture" / "model.md").write_text(
            "# Model\n\n## Purpose\n"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_valid_base_contract_passes(self):
        self.assertEqual([], run(self.root))

    def test_alias_and_stray_docs_entries_fail(self):
        (self.root / "docs" / "adr").mkdir()
        (self.root / "docs" / "notes.md").write_text("# Notes\n")

        errors = run(self.root)

        self.assertTrue(any("docs/adr/" in error for error in errors))
        self.assertTrue(any("docs/notes.md" in error for error in errors))

    def test_os_knowledge_directory_is_not_required(self):
        self.assertFalse((self.root / "knowledge").exists())
        self.assertEqual([], run(self.root))

    def test_optional_tool_guidance_does_not_become_documentation_authority(self):
        (self.root / "CLAUDE.md").write_text("# Shared tool guidance\n")

        self.assertEqual([], run(self.root))

    def test_broken_link_and_anchor_fail(self):
        (self.root / "README.md").write_text(
            "# Project\n\n[Missing](docs/missing.md)\n[Anchor](STATUS.md#missing)\n"
        )

        errors = run(self.root)

        self.assertTrue(any("broken relative link" in error for error in errors))
        self.assertTrue(any("missing heading anchor" in error for error in errors))

    def test_links_in_code_examples_are_not_validated(self):
        (self.root / "README.md").write_text(
            "# Project\n\n```markdown\n[Example](missing.md)\n```\n"
        )

        self.assertEqual([], run(self.root))

    def test_historical_archive_links_do_not_become_current_contract(self):
        (self.root / "docs" / "archive" / "snapshot.md").write_text(
            "# Historical snapshot\n\n[Former path](../missing.md)\n"
        )

        self.assertEqual([], run(self.root))


if __name__ == "__main__":
    unittest.main()
