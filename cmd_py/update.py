from __future__ import annotations

import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# Files/directories to skip when copying
IGNORE_PATTERNS = {"models", "base_interiors", "rooms"}

IGNORE_EXTENSIONS = {".txm", ".cmp", ".3db"}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Discovery Navmap Game Data Importer")
    parser.add_argument("-config", default="update/build.json", help="Path to build.json config file")
    parser.add_argument("-out", required=True, help="Output directory (required)")
    args = parser.parse_args()

    # Load config
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    # Determine FL path
    fl_path = cfg.get("fl_path", "")
    if not fl_path:
        log.info("No FL path set in config, searching for Discovery install...")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        found = find_freelancer_path(local_appdata)
        if not found:
            log.error("Discovery install directory not found, aborting")
            sys.exit(1)
        fl_path = found
    log.info("Freelancer directory: %s", fl_path)

    # Create output directory
    os.makedirs(args.out, exist_ok=True)

    # Prompt user
    print("Run FL Path Generator (in the utils folder) on the FL installation")
    print("Run FLInfocardIE. Save infocards.txt into the 'update' folder")
    input("Press Enter to continue once you're done...")

    # Format infocards
    log.info("Formatting infocards.txt")
    try:
        format_infocards(
            os.path.join("update", "infocards.txt"),
            os.path.join(args.out, "infocards.txt"),
        )
    except Exception as e:
        log.warning("Failed to format infocards: %s", e)

    # Copy directories
    log.info("Copying directories")
    for d in cfg.get("directories", []):
        src = os.path.join(fl_path, d["path"])
        dst = os.path.join(args.out, d["dest"])
        log.info("Copying %s -> %s", src, dst)
        try:
            copy_dir(src, dst)
        except Exception as e:
            log.warning("%s", e)

    # Copy files
    log.info("Copying files")
    for f_entry in cfg.get("files", []):
        src = os.path.join(fl_path, f_entry["path"])
        dst = os.path.join(args.out, f_entry["dest"])
        log.info("Copying %s -> %s", src, dst)
        try:
            copy_file(src, dst)
        except Exception as e:
            log.warning("%s", e)

    # Copy special_systems.txt from update dir
    try:
        copy_file(os.path.join("update", "special_systems.txt"), os.path.join(args.out, "special_systems.txt"))
    except Exception as e:
        log.warning("Failed to copy special_systems.txt: %s", e)

    # Lowercase rename everything in the output directory
    log.info("Lowercasing filenames...")
    lowercase_rename(args.out)

    log.info("Done! Start the server with: python main.py -data %s", args.out)


def find_freelancer_path(search_dir: str) -> str:
    if not search_dir or not os.path.isdir(search_dir):
        return ""
    for dirpath, dirnames, _ in os.walk(search_dir):
        for d in dirnames:
            if d.startswith("Discovery Freelancer"):
                return os.path.join(dirpath, d)
    return ""


def format_infocards(in_path: str, out_path: str) -> None:
    with open(in_path, encoding="utf-8") as f:
        text = f.read()

    # Normalize line endings
    text = text.replace("\r\n", "\n")

    # Split into lines and process entries
    lines = text.split("\n")
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Skip blank lines and NAME/INFOCARD markers
        if not line or line in ("NAME", "INFOCARD"):
            i += 1
            continue
        # This is an ID line (numeric) — the next non-blank, non-marker line is the text
        if line.isdigit():
            entry_id = line
            i += 1
            entry_text = ""
            while i < len(lines):
                candidate = lines[i].strip()
                if candidate and candidate not in ("NAME", "INFOCARD"):
                    entry_text = candidate
                    break
                i += 1
            if entry_id and entry_text:
                output.append(entry_id)
                output.append(entry_text)
            i += 1
            continue
        # Unknown line, skip
        i += 1

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))


def copy_dir(src: str, dst: str) -> None:
    for dirpath, dirnames, filenames in os.walk(src):
        # Check ignore patterns for directories
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in IGNORE_PATTERNS
        ]

        rel = os.path.relpath(dirpath, src)
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in IGNORE_EXTENSIONS:
                continue
            src_file = os.path.join(dirpath, fname)
            # Lowercase the filename
            dst_file = os.path.join(dst, rel, fname.lower())
            _copy_file_inner(src_file, dst_file)


def copy_file(src: str, dst: str) -> None:
    # Lowercase the filename
    dir_part = os.path.dirname(dst)
    base = os.path.basename(dst).lower()
    dst = os.path.join(dir_part, base)
    _copy_file_inner(src, dst)


def _copy_file_inner(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def lowercase_rename(root: str) -> None:
    # Collect all paths first
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath != root:
            paths.append(dirpath)
        for fname in filenames:
            paths.append(os.path.join(dirpath, fname))

    # Process in reverse order (deepest first)
    for path in reversed(paths):
        dir_part = os.path.dirname(path)
        base = os.path.basename(path)
        lower = base.lower()
        if base != lower:
            new_path = os.path.join(dir_part, lower)
            # Handle case-insensitive filesystems where rename might fail
            try:
                os.rename(path, new_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
