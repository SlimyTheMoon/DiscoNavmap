from __future__ import annotations

import errno
import fnmatch
import json
import os
import shutil
import sys
from pathlib import Path

# NOTE:
# - Updated for modern Python (3.12+ / 3.14+): removed deprecated distutils usage.
# - Fixed file-copy behavior when the destination is a directory.
# - Added safer directory creation and a __main__ guard.

build = {
    # this is unused, it merely explains how build.json is structured
    # since JSON doesn't allow comments.

    # files to copy into the output folder
    "files": [
        {"path": "DATA/MISSIONS/mbases.ini", "dest": "mbases.ini"},
        {"path": "DATA/INTERFACE/infocardmap.ini", "dest": "infocardmap.ini"},
        {"path": "DATA/SOLAR/solararch.ini", "dest": "solararch.ini"},
        {"path": "DATA/UNIVERSE/universe.ini", "dest": "universe/universe.ini"},
        {"path": "DATA/UNIVERSE/multiuniverse.ini", "dest": "universe/multiuniverse.ini"},
        {"path": "DATA/UNIVERSE/shortest_illegal_path.ini", "dest": "universe/shortest_illegal_path.ini"},
        {"path": "DATA/UNIVERSE/shortest_legal_path.ini", "dest": "universe/shortest_legal_path.ini"},
        {"path": "DATA/UNIVERSE/systems_shortest_path.ini", "dest": "universe/systems_shortest_path.ini"},
    ],
    # directories to copy into the output folder
    "directories": [
        {"path": "IONCROSS", "dest": ""},
        {"path": "DATA/SOLAR/ASTEROIDS", "dest": "solar/asteroids"},
        {"path": "DATA/UNIVERSE/SYSTEMS", "dest": "universe/systems"},
    ],
}

build_input_dir = Path("update")


def get_freelancer_path(search_dir: str | os.PathLike[str] | None) -> str:
    if not search_dir:
        return ""
    output_path = ""
    for root, dirs, _files in os.walk(search_dir):
        for dirname in fnmatch.filter(dirs, "Discovery Freelancer*"):
            output_path = os.path.join(root, dirname)
    return output_path


def copy_file(src: str, dst: str, **kwargs) -> str:
    """Copy src -> dst, lowercasing only the destination filename.

    shutil.copytree() calls copy_function(src, dst) where dst is a full path including
    the filename. Elsewhere in this script we may pass a directory as dst; handle both.
    """
    src_path = Path(src)
    dst_path = Path(dst)

    # If dst is a directory, copy into it using the source filename.
    if dst_path.exists() and dst_path.is_dir():
        dst_path = dst_path / src_path.name
    elif dst_path.suffix == "" and dst_path.name and not dst_path.name.lower().endswith(src_path.suffix.lower()):
        # Heuristic: if dst looks like a directory path (no suffix), treat as directory.
        # This also covers non-existent directories.
        dst_path = dst_path / src_path.name

    dst_path = dst_path.with_name(dst_path.name.lower())
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src_path, dst_path, **kwargs)
    return str(dst_path)


def lowercase_rename(root_dir: str | os.PathLike[str]) -> None:
    """Renames all subfolders/files of root_dir to lowercase (not including root_dir itself)."""

    def rename_all(root: str, items: list[str]) -> None:
        for name in items:
            src = os.path.join(root, name)
            dst = os.path.join(root, name.lower())
            if src == dst:
                continue
            try:
                os.rename(src, dst)
            except OSError:
                # Ignore collisions (e.g. case-insensitive FS) and other rename issues.
                pass

    # Start from the bottom so paths further up remain valid after renaming
    for root, dirs, files in os.walk(root_dir, topdown=False):
        rename_all(root, dirs)
        rename_all(root, files)


def copy_into_existing_dir(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    src = str(src)
    dst = str(dst)
    os.makedirs(dst, exist_ok=True)

    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            copy_into_existing_dir(s, d)
        else:
            # Only copy if destination is missing or the source is (meaningfully) newer.
            try:
                src_mtime = os.stat(s).st_mtime
                dst_mtime = os.stat(d).st_mtime if os.path.exists(d) else -1
            except OSError:
                src_mtime, dst_mtime = 0, -1

            if (not os.path.exists(d)) or (src_mtime - dst_mtime > 1):
                Path(d).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)


def copy(src: str | os.PathLike[str], dest: str | os.PathLike[str]) -> None:
    src_path = Path(src)
    dest_path = Path(dest)

    if src_path.is_dir():
        try:
            shutil.copytree(
                src_path,
                dest_path,
                ignore=shutil.ignore_patterns("BASES", "BASE_INTERIORS", "MODELS", "*.txm"),
                copy_function=copy_file,
                dirs_exist_ok=False,
            )
        except OSError as e:
            if e.errno == errno.EEXIST:
                copy_into_existing_dir(src_path, dest_path)
            else:
                print(f"Directory not copied. Error: {e}")
    elif src_path.is_file():
        copy_file(str(src_path), str(dest_path))
    else:
        print(f"Could not copy {src_path} to {dest_path}!")


def format_infocards(out_dir: Path) -> None:
    print("Formatting infocards.txt")

    input_name = build_input_dir / "infocards.txt"
    out_name = out_dir / "infocards.txt"

    # Preserve CRLF usage for downstream tools that expect Windows line endings.
    with open(input_name, "r", encoding="utf-8", newline="") as in_file, open(
        out_name, "w", encoding="utf-8", newline=""
    ) as out_file:
        out_text = "".join(in_file.readlines()[1:])
        out_text = out_text.replace("\r\n\r\n", "\r\n")
        out_text = out_text.replace("\r\nNAME\r\n", "\r\n")
        out_text = out_text.replace("\r\nINFOCARD\r\n", "\r\n")
        out_file.write(out_text)


def build_update() -> None:
    config = build

    with open(build_input_dir / "build.json", "r", encoding="utf-8") as json_file:
        config = json.load(json_file)

    fl_path = Path("C:/Users/inudn/AppData/Local/Discovery Freelancer 5.00.8")
    if config.get("fl_path", "") == "":
        print('No FL path set in "update/build.json", looking for Discovery install...')
        found_fl_path = get_freelancer_path(os.getenv("LOCALAPPDATA"))
        if found_fl_path == "":
            print("Discovery install directory not found, aborting")
            sys.exit(1)
        fl_path = Path(found_fl_path)
    else:
        fl_path = Path(config["fl_path"])

    print(f'Freelancer directory set to "{fl_path}"')

    out_dir_raw = input("Set output directory: ").strip()
    if not out_dir_raw:
        print("No output directory provided, aborting")
        sys.exit(1)

    out_dir = Path(out_dir_raw)
    out_dir.mkdir(parents=True, exist_ok=False)

    print(
        f'Run FL Path Generator (in the utils folder) on the FL installation in the "{fl_path}" folder'
    )
    print(f'Run FLInfocardIE. Save infocards.txt into the "{build_input_dir}" folder')
    input("Press Enter to continue once you're done...")

    format_infocards(out_dir)

    print("Copying directories")
    for directory in config.get("directories", []):
        src_path = fl_path / directory["path"]
        out_path = out_dir / directory["dest"]
        print(f"Copying {src_path} to {out_path}")
        copy(src_path, out_path)

    print("Copying files")
    for file_item in config.get("files", []):
        src_path = fl_path / file_item["path"]
        out_path = out_dir
        if file_item.get("dest", "") != "":
            out_path = out_dir / file_item["dest"]
        print(f"Copying {src_path} to {out_path}")
        copy(src_path, out_path)

    copy(build_input_dir / "special_systems.txt", out_dir)

    lowercase_rename(out_dir)

    print(f'Done! Now open index.html and set the dataRootPath variable to the "{out_dir}" folder')


if __name__ == "__main__":
    build_update()
