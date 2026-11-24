"""Remember the reader's explicitly selected local vault."""

import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


def config_path():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "book-to-tutor" / "vault.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="selected", type=Path, metavar="VAULT")
    parser.add_argument("--config", type=Path, help="Override the settings file for an isolated run.")
    args = parser.parse_args()
    config = args.config or config_path()
    temp = None
    try:
        if args.selected is None:
            if not config.is_file():
                print("尚未选择 Obsidian 库。", file=sys.stderr)
                return 1
            selected = Path(json.loads(config.read_text(encoding="utf-8"))["vault"])
        else:
            selected = args.selected.expanduser().resolve()
        if not selected.is_dir():
            raise ValueError(f"库文件夹不存在：{selected}")
        if args.selected is not None:
            config.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile("w", encoding="utf-8", dir=config.parent, delete=False) as out:
                temp = Path(out.name)
                json.dump({"vault": str(selected)}, out, ensure_ascii=False)
            os.replace(temp, config)
        print(selected)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(error, file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
