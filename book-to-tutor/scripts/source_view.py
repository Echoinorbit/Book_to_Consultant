"""Make a small offline source viewer for a specific figure, passage or code listing."""

import argparse
from base64 import b64encode
from hashlib import sha256
from html import escape
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import quote

import pymupdf


def pdf_href(pdf, directory):
    try:
        relative = Path(os.path.relpath(pdf, directory)).as_posix()
        return quote(relative, safe="/")
    except ValueError:  # Source and viewer on different Windows volumes
        return pdf.as_uri()


def render(pdf, start, end, title, directory):
    with pymupdf.open(pdf) as document:
        if not document.is_pdf or document.needs_pass:
            raise ValueError("请选择可读取的 PDF。")
        if not 1 <= start <= end <= len(document):
            raise ValueError(f"PDF 页序应为 1 至 {len(document)}，且起始页不大于结束页。")
        source = escape(pdf_href(pdf, directory), quote=True)
        figures = []
        for number in range(start, end + 1):
            pixmap = document[number - 1].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
            data = b64encode(pixmap.tobytes("png")).decode("ascii")
            figures.append(
                f'<figure id="p{number}"><figcaption>PDF 第 {number} 页 · '
                f'<a href="{source}#page={number}">打开原始 PDF</a></figcaption>'
                f'<img width="{pixmap.width}" height="{pixmap.height}" '
                f'alt="原书 PDF 第 {number} 页" src="data:image/png;base64,{data}"></figure>'
            )
    heading = escape(title or pdf.stem)
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading} · 原书</title>
<style>
:root {{ color-scheme: light; font: 16px/1.5 system-ui,sans-serif; color: #222; background: #f3f2ee }}
body {{ margin: auto; max-width: 62rem; padding: 1rem }}
h1 {{ font-size: 1.4rem; overflow-wrap: anywhere }}
figure {{ margin: 1rem 0 2rem }} figcaption {{ padding: .45rem 0 }} a {{ color: #174c82 }}
img {{ display: block; max-width: 100%; height: auto; background: white }}
</style><main><h1>{heading}</h1>{''.join(figures)}</main></html>
""".encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True, help="First physical PDF page, starting at 1")
    parser.add_argument("--end", type=int, help="Last physical PDF page, inclusive")
    parser.add_argument("--out-dir", type=Path, required=True, help="Local materials directory")
    parser.add_argument("--title", help="Label such as 图 5.9 · 代码与图注")
    args = parser.parse_args()
    temp = None
    try:
        directory = args.out_dir.resolve()
        end = args.start if args.end is None else args.end
        content = render(args.pdf.resolve(strict=True), args.start, end, args.title, directory)
        digest = sha256(content).hexdigest()[:16]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"source-p{args.start}-{end}-{digest}.html"
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError(f"已有同名文件的内容有改动：{target}")
        else:
            with NamedTemporaryFile(dir=directory, delete=False) as out:
                temp = Path(out.name)
                out.write(content)
            os.replace(temp, target)
        print(target)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
