"""Merge one attributed Markdown contribution into a UTF-8 Obsidian concept note."""

import argparse
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys


class Conflict(Exception):
    """The original note must be kept for review or a retry."""


def note_target(vault, name):
    root = vault.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Vault must be an existing directory.")
    relative = PureWindowsPath(name)
    if relative.anchor or relative.suffix.lower() != ".md":
        raise ValueError("Use a vault-relative note path ending in .md.")
    reserved = {".git", ".obsidian", ".trash"}
    for part in relative.parts:
        if (part.casefold() in reserved or part.endswith((" ", ".")) or
                re.search(r'[<>:"|?*\x00-\x1f]', part) or
                re.match(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(\.|$)", part, re.I)):
            raise ValueError("Unsafe vault-relative note path.")
    target = root.joinpath(*relative.parts).resolve()
    try:
        resolved_parts = target.relative_to(root).parts
    except ValueError:
        raise ValueError("Note resolves outside the vault.") from None
    if target.suffix.lower() != ".md" or any(p.casefold() in reserved for p in resolved_parts):
        raise ValueError("Note resolves to a reserved path or a non-Markdown file.")
    return target


def merge(original, source_key, markdown):
    original.decode("utf-8-sig")  # Refuse to mix encodings in an existing note.
    if not source_key.strip() or source_key != source_key.strip() or len(source_key.splitlines()) != 1:
        raise ValueError("Source key must be a nonempty, single-line identifier.")
    prefix = b"<!-- book-to-tutor:"
    if not markdown.strip() or prefix.decode() in markdown:
        raise ValueError("Supply nonempty Markdown without reserved book-to-tutor markers.")

    key = hashlib.sha256(source_key.encode("utf-8")).hexdigest().encode("ascii")
    begin = prefix + b"begin " + key + b" "
    end = prefix + b"end " + key + b" -->"
    newline = b"\r\n" if original.partition(b"\n")[0].endswith(b"\r") else b"\n"
    body = markdown.encode("utf-8").replace(b"\n", newline)
    if not body.endswith(newline):
        body += newline
    digest = hashlib.sha256(body).hexdigest().encode("ascii")
    block = begin + digest + b" -->" + newline + body + end

    marker_lines = [line for line in original.splitlines() if prefix in line and key in line]
    if not marker_lines:
        separator = b"" if not original else newline if original.endswith(b"\n") else newline * 2
        return original + separator + block + newline, "appended"

    pattern = (b"^" + re.escape(begin) + rb"([0-9a-f]{64}) -->\r?\n(.*?)^" +
               re.escape(end) + rb"(?=\r?$)")
    match = re.search(pattern, original, re.M | re.S)
    if len(marker_lines) != 2 or not match:
        raise Conflict("Contribution markers changed or are duplicated. Review the note.")
    if hashlib.sha256(match[2]).hexdigest().encode("ascii") != match[1]:
        raise Conflict("This contribution contains local edits. Present the proposed change for review.")
    if match[0] == block:
        return original, "unchanged"
    return original[:match.start()] + block + original[match.end():], "updated"


def read_note(target):
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None


def import_contribution(target, source_key, markdown):
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation serializes imports. The same file stages complete note bytes.
    staging = target.with_name("." + target.name + ".book-to-tutor.pending")
    try:
        writer = staging.open("xb")
    except FileExistsError:
        raise Conflict("Another import is in progress or left a pending file: " + str(staging)) from None
    moved = False
    try:
        with writer:
            before = read_note(target)
            after, status = merge(before or b"", source_key, markdown)
            if status == "unchanged":
                return status
            writer.write(after)
            writer.flush()
            os.fsync(writer.fileno())
        if before is None:
            try:
                if os.name == "nt":
                    os.rename(staging, target)  # Fails if another program just created the note.
                    moved = True
                else:
                    os.link(staging, target)
            except FileExistsError:
                raise Conflict("The note was just created by another writer. Retry the import.") from None
            return "created"
        if os.name != "nt":
            shutil.copymode(target, staging)
        if read_note(target) != before:
            raise Conflict("The note changed during import. Retry using the latest note.")
        os.replace(staging, target)
        moved = True
        return status
    finally:
        if not moved:
            staging.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True, help="existing vault directory")
    parser.add_argument("--note", required=True, help="vault-relative Markdown note path")
    parser.add_argument("--source-key", required=True, help="stable book/claim identifier across imports")
    parser.add_argument("--input", type=Path, required=True, help="UTF-8 Markdown with visible source attribution")
    args = parser.parse_args()
    try:
        target = note_target(args.vault, args.note)
        if args.input.resolve(strict=True) == target:
            raise ValueError("The contribution input must be separate from the target note.")
        markdown = args.input.read_text(encoding="utf-8-sig")
        print(import_contribution(target, args.source_key, markdown))
        return 0
    except Conflict as error:
        print("conflict:", error, file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError) as error:
        print("error:", error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
