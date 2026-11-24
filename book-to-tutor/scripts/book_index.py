"""Import a PDF into an Obsidian vault and track evidence-backed page coverage."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import quote, unquote


INDEX = ".book-index.json"
ENTRY = "阅读入口.md"
NOTES = "章节索引.md"
MARKER = re.compile(r"<!--\s*pdf-pages:\s*([\d,\s-]+?)\s*-->")
WIKI = re.compile(r"!?\[\[([^\]\n]+)\]\]")
MARKDOWN = re.compile(r"!?\[[^\]\n]*\]\((?:<([^>\n]+)>|([^\s()]+))\)")


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ranges(pages):
    spans = []
    for page in sorted(set(pages)):
        if spans and page == spans[-1][1] + 1:
            spans[-1][1] = page
        else:
            spans.append([page, page])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


def page_set(spec, count):
    pages = set()
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise ValueError(f"无效的 PDF 页码范围：{part!r}")
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= count:
            raise ValueError(f"页码必须在 1 至 {count} 之内，且起页不得大于终页")
        pages.update(range(start, end + 1))
    return pages


def inspect_pdf(path):
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError("读取 PDF 需要 PyMuPDF。请用运行此脚本的 Python 执行 python -m pip install pymupdf") from exc
    with pymupdf.open(path) as doc:
        if not doc.is_pdf or doc.needs_pass or not len(doc):
            raise ValueError("请提供可直接阅读且至少包含一页的 PDF")
        sparse, pictures = [], []
        for number, page in enumerate(doc, 1):
            if len("".join(page.get_text().split())) < 60:
                sparse.append(number)
            if page.get_image_info():
                pictures.append(number)
        toc = [{"level": depth, "title": title, "page": page}
               for depth, title, page in doc.get_toc() if 1 <= page <= len(doc)]
        return {"title": doc.metadata.get("title") or path.stem, "pages": len(doc),
                "outline": toc, "low_text_pages": ranges(sparse), "image_pages": ranges(pictures)}


def safe_name(title):
    title = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', " ", title)
    return " ".join(title.split())[:72].strip(" .") or "电子书"


def link_to(target, origin, page=None):
    rel = Path(os.path.relpath(target, origin)).as_posix()
    return quote(rel, safe="/") + (f"#page={page}" if page else "")


def write_index(book, data):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=book,
                                     delete=False, suffix=".tmp") as temp:
        name = Path(temp.name)
        try:
            json.dump(data, temp, indent=2, ensure_ascii=False)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        except BaseException:
            temp.close()
            name.unlink(missing_ok=True)
            raise
    try:
        os.replace(name, book / INDEX)
    finally:
        name.unlink(missing_ok=True)


@contextmanager
def shelf_lock(shelf):
    """The OS releases the byte-range lock even if the importer exits abruptly."""
    with (shelf / ".book-to-tutor.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def read_index(book):
    data = json.loads((book / INDEX).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("书籍索引版本不受支持")
    return data


def inside(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError(f"路径必须位于 {root} 内：{relative}")
    return path


def source_path(book, data):
    source = inside(book.parent.parent, data["source"])
    if not source.is_file() or fingerprint(source) != data["sha256"]:
        raise ValueError(f"来源 PDF 已移动或内容有变，请恢复原文件：{source}")
    return source


def write_entry(folder, book, source, data):
    title = " ".join(data["title"].split())
    lines = [f"# {title}", "", f"[打开原书]({link_to(source, book, 1)}) · PDF 共 {data['pages']} 页",
             "", "本书引用使用阅读器从 1 开始的 PDF 页码。", "", "## 原书目录", ""]
    for row in data["outline"]:
        label = " ".join(row["title"].split()).replace("[", "\\[").replace("]", "\\]")
        lines.append(f"{'  ' * min(row['level'] - 1, 6)}- [{label}]({link_to(source, book, row['page'])})")
    if not data["outline"]:
        lines.append("原 PDF 没有可定位的书签，可在阅读时补充目录。")
    lines += ["", f"[打开章节与概念笔记索引]({link_to(book / NOTES, book)})", ""]
    (folder / ENTRY).write_text("\n".join(lines), encoding="utf-8")
    (folder / NOTES).write_text("# 章节与概念笔记\n\n", encoding="utf-8")


def link_note(book, note):
    index = inside(book, NOTES)
    target = link_to(book / note, book)
    label = Path(note).stem.replace("[", "\\[").replace("]", "\\]")
    with index.open("a+", encoding="utf-8") as stream:
        stream.seek(0)
        if f"]({target})" not in stream.read():
            stream.write(f"\n- [{label}]({target})\n")


def import_book(vault, pdf, title):
    if not vault.is_dir() or not pdf.is_file():
        raise ValueError("请选择已存在的 Obsidian 库目录和 PDF 文件")
    sha = fingerprint(pdf)
    shelf = inside(vault, "书籍")
    shelf.mkdir(exist_ok=True)
    with shelf_lock(shelf):
        for book in shelf.glob(f"*-{sha[:12]}"):
            if book.is_dir() and not book.is_symlink() and (book / INDEX).is_file():
                previous = read_index(book)
                if previous["sha256"] == sha:
                    source_path(book, previous)
                    return {"book": str(book), "entry": str(book / ENTRY), "created": False}
        data = inspect_pdf(pdf)
        data["title"] = title or data["title"]
        book = shelf / f"{safe_name(data['title'])}-{sha[:12]}"
        if book.exists():
            raise ValueError(f"目标目录已存在且未识别为本书，已保留：{book}")
        pending = Path(tempfile.mkdtemp(prefix=".import-", dir=shelf))
        try:
            if pdf.is_relative_to(vault):
                source = pdf
                verified = fingerprint(pdf)
            else:
                source = book / "原书.pdf"
                shutil.copyfile(pdf, pending / source.name)
                verified = fingerprint(pending / source.name)
            if verified != sha:
                raise ValueError("导入期间来源文件发生变化，请重试")
            data.update(version=1, sha256=sha, source=source.relative_to(vault).as_posix(),
                        claims={}, non_instructional={})
            write_index(pending, data)
            write_entry(pending, book, source, data)
            pending.rename(book)
        finally:
            if pending.exists() and not pending.is_symlink() and pending.resolve().parent == shelf:
                shutil.rmtree(pending)
        return {"book": str(book), "entry": str(book / ENTRY), "created": True}


def note_evidence(book, source, note, count):
    path = inside(book, note)
    if path.suffix.lower() != ".md" or path in (book / ENTRY, book / NOTES) or not path.is_file():
        raise ValueError(f"请指定已有的章节或概念笔记：{note}")
    raw = path.read_text(encoding="utf-8-sig")
    raw = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", raw, count=1, flags=re.S)
    raw = re.sub(r"(?ms)^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", raw)
    raw = re.sub(r"(`+)[^`\n]+\1", "", raw)
    declared = [page_set(part, count) for spec in MARKER.findall(raw) for part in spec.split(",")]
    visible = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    body = MARKDOWN.sub("", WIKI.sub("", visible))
    if not any(re.search(r"\w", line) and not line.lstrip().startswith("#") for line in body.splitlines()):
        raise ValueError("笔记缺少正文，请先写下对本节内容的解释")
    anchors = set()
    links = [(match[1] or match[2], False) for match in MARKDOWN.finditer(visible)]
    links += [(target.split("|", 1)[0], True) for target in WIKI.findall(visible)]
    for target, wiki in links:
        match = re.fullmatch(r"(.+)#page=(\d+)", target)
        if not match:
            continue
        rel = Path(unquote(match[1]))
        roots = [path.parent, book.parent.parent] if wiki else [path.parent]
        if not rel.is_absolute() and any((base / rel).resolve() == source for base in roots):
            anchors.add(int(match[2]))
    supported = set()
    for pages in declared:
        if min(pages) in anchors:
            supported.update(pages)
    return supported


def status(book, data, source):
    covered, stale = set(), []
    for note, spec in data["claims"].items():
        claimed = page_set(spec, data["pages"])
        try:
            supported = note_evidence(book, source, note, data["pages"])
        except (OSError, ValueError) as exc:
            stale.append({"note": note, "pages": spec, "reason": str(exc)})
            continue
        covered.update(claimed & supported)
        if claimed - supported:
            stale.append({"note": note, "pages": ranges(claimed - supported), "reason": "笔记缺少对应页码声明或来源链接"})
    classified = {int(page) for page in data.get("non_instructional", {})}
    return {"book": str(book), "source": data["source"], "pages": data["pages"],
            "covered_count": len(covered), "covered": ranges(covered),
            "non_instructional_count": len(classified), "non_instructional": ranges(classified),
            "pending": ranges(set(range(1, data["pages"] + 1)) - covered - classified),
            "low_text_pages": data["low_text_pages"], "image_pages": data["image_pages"],
            "claims": data["claims"], "stale_claims": stale}


def run(args):
    if args.command == "inspect":
        return inspect_pdf(args.pdf.resolve())
    if args.command == "import":
        return import_book(args.vault.resolve(), args.pdf.resolve(), args.title)
    book = args.book.resolve()
    if book.parent.name != "书籍" or not (book / INDEX).is_file():
        raise ValueError("请将 --book 指向脚本返回的单本书目录")
    if args.command == "status":
        data = read_index(book)
        return status(book, data, source_path(book, data))
    with shelf_lock(book.parent):
        data = read_index(book)
        source = source_path(book, data)
        count = data["pages"]
        wanted = page_set(args.pages, count)
        if args.command == "unmark":
            note = inside(book, args.note).relative_to(book).as_posix()
            old = data["claims"].get(note)
            if old:
                remaining = page_set(old, count) - wanted
                if remaining:
                    data["claims"][note] = ranges(remaining)
                else:
                    del data["claims"][note]
                write_index(book, data)
            return status(book, data, source)
        classified = data.setdefault("non_instructional", {})
        sparse = page_set(data["low_text_pages"], count) if data["low_text_pages"] else set()
        if wanted & sparse and not args.visual_checked:
            raise ValueError(f"页 {ranges(wanted & sparse)} 的可提取文字较少。请先逐页目视核实，再加 --visual-checked")
        if args.command == "classify":
            if not args.reason.strip():
                raise ValueError("请说明分类依据")
            claimed = set()
            for spec in data["claims"].values():
                claimed.update(page_set(spec, count))
            if args.kind != "pending" and wanted & claimed:
                raise ValueError(f"已有教学笔记声明页 {ranges(wanted & claimed)}，不能作为非教学页归档")
            for page in wanted:
                if args.kind == "pending":
                    classified.pop(str(page), None)
                else:
                    classified[str(page)] = {"kind": args.kind, "reason": args.reason.strip()}
            write_index(book, data)
            return status(book, data, source)
        note = inside(book, args.note).relative_to(book).as_posix()
        missing = wanted - note_evidence(book, source, note, count)
        if missing:
            raise ValueError(f"未验证页码 {ranges(missing)}。请在笔记中写 <!-- pdf-pages: 1-3,5 --> 并为每个连续范围的首个物理页插入原书页链接")
        for page in wanted:
            classified.pop(str(page), None)
        old = data["claims"].get(note)
        data["claims"][note] = ranges(wanted | (page_set(old, count) if old else set()))
        link_note(book, note)
        write_index(book, data)
        return status(book, data, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("inspect", help="只读清点物理页、书签和需目视检查的页面")
    scan.add_argument("--pdf", type=Path, required=True)
    add = commands.add_parser("import", help="导入到用户选择的 Obsidian 库")
    add.add_argument("--pdf", type=Path, required=True)
    add.add_argument("--vault", type=Path, required=True)
    add.add_argument("--title", help="首轮导入时指定书名")
    commands.add_parser("status", help="重新核对笔记和来源后报告覆盖").add_argument("--book", type=Path, required=True)
    mark = commands.add_parser("mark", help="登记有笔记解释并链接到原书的物理页")
    mark.add_argument("--book", type=Path, required=True)
    mark.add_argument("--note", required=True, help="相对于单本书目录的现有 .md 路径")
    mark.add_argument("--pages", required=True, help="例如 10-12,15")
    mark.add_argument("--visual-checked", action="store_true", help="已逐页核对低文字量页面")
    undo = commands.add_parser("unmark", help="撤回指定笔记的页码登记，保留笔记和导航")
    undo.add_argument("--book", type=Path, required=True)
    undo.add_argument("--note", required=True)
    undo.add_argument("--pages", required=True)
    classify = commands.add_parser("classify", help="将人工核实的非教学页单列，或恢复为待处理")
    classify.add_argument("--book", type=Path, required=True)
    classify.add_argument("--pages", required=True)
    classify.add_argument("--kind", choices=("frontmatter", "backmatter", "blank", "pending"), required=True)
    classify.add_argument("--reason", required=True)
    classify.add_argument("--visual-checked", action="store_true", help="已逐页核对低文字量页面")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"book_index: {exc}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
