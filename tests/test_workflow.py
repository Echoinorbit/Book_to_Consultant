"""End-to-end regressions for source-backed coverage and reader-owned text."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf


SCRIPTS = Path(__file__).resolve().parents[1] / "book-to-tutor" / "scripts"


def run(script, *args, expected=0):
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPTS / script), *map(str, args)],
        capture_output=True, encoding="utf-8",
    )
    if result.returncode != expected:
        raise AssertionError(f"{result.args}: {result.stdout}\n{result.stderr}")
    return result.stdout.strip()


class BookWorkflowTests(unittest.TestCase):
    def test_reimport_resume_and_cross_page_figure(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "库"
            vault.mkdir()
            pdf = base / "sample.pdf"
            with pymupdf.open() as sample:
                sample.new_page().insert_text((72, 100), "Figure body on the first page.")
                sample.new_page().insert_text((72, 100), "Caption on the second page.")
                sample.new_page().insert_text((72, 100), "Next section.")
                sample.save(pdf)
            add = ("import", "--vault", vault, "--pdf", pdf)
            first = json.loads(run("book_index.py", *add))
            book = Path(first["book"])
            self.assertFalse(json.loads(run("book_index.py", *add))["created"])
            note = book / "分块.md"
            note.write_text(
                "# 分块\n\n核对图体与下一页图注。\n<!-- pdf-pages: 1-2 -->\n"
                "[代码](原书.pdf#page=1) · [图注](原书.pdf#page=2)\n", encoding="utf-8",
            )
            args = ("mark", "--book", book, "--note", note.name, "--pages", "1-2", "--visual-checked")
            marked = json.loads(run("book_index.py", *args))
            self.assertEqual((marked["covered_count"], marked["pending"]), (2, "3"))
            viewer = Path(run("source_view.py", "--pdf", book / "原书.pdf", "--start", 1,
                              "--end", 2, "--out-dir", book / "材料"))
            view = viewer.read_text(encoding="utf-8")
            self.assertEqual(view.count("data:image/png;base64,"), 2)
            self.assertIn("#page=2", view)
            note.write_text("# 空笔记\n", encoding="utf-8")
            resumed = json.loads(run("book_index.py", "status", "--book", book))
            self.assertEqual(resumed["pending"], "1-3")
            self.assertEqual(resumed["stale_claims"][0]["note"], note.name)

    def test_cross_book_merge_keeps_manual_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            note = vault / "共享内存.md"
            original = "我的原话，保留。\r\n".encode("utf-8")
            note.write_bytes(original)
            incoming = vault / "contribution.md"

            def merge(key, text, expected=0):
                incoming.write_text(text, encoding="utf-8")
                return run("concept_note.py", "--vault", vault, "--note", note.name,
                           "--source-key", key, "--input", incoming, expected=expected)

            self.assertEqual(merge("book-a", "第一本的依据"), "appended")
            self.assertEqual(merge("book-b", "第二本的条件"), "appended")
            self.assertEqual(merge("book-b", "第二本的条件"), "unchanged")
            self.assertIn(original, note.read_bytes())
            edited = note.read_bytes().replace("第一本的依据".encode(), "我补充了限定条件".encode())
            note.write_bytes(edited)
            merge("book-a", "导师提出的新解释", expected=3)
            self.assertEqual(note.read_bytes(), edited)


if __name__ == "__main__":
    unittest.main()
