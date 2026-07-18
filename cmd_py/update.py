from __future__ import annotations

import json
import logging
import os
import shutil
import struct
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
    if not fl_path or not os.path.isdir(fl_path):
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

    # Extract names + infocards directly from the game's resource DLLs
    # (replaces the manual FLInfocardIE step)
    log.info("Extracting infocards from resource DLLs...")
    count = extract_infocards(fl_path, os.path.join(args.out, "infocards.txt"))
    log.info("Extracted %d strings/infocards", count)

    # Copy directories (BINI files are decoded to plain text transparently)
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


# ------------------------------------------------------------------
# BINI decoding (Freelancer compiled INI format)
# ------------------------------------------------------------------

def is_bini(data: bytes) -> bool:
    return data[:4] == b"BINI"


def bini_decode(data: bytes) -> str:
    """Decode a compiled BINI file to INI text (pure Python)."""
    magic, version, str_offset = struct.unpack_from("<4sII", data, 0)
    if magic != b"BINI" or version != 1:
        raise ValueError("not a BINI v1 file")

    def get_str(off: int) -> str:
        end = data.find(b"\0", str_offset + off)
        return data[str_offset + off:end].decode("windows-1252", errors="replace")

    out: list[str] = []
    pos = 12
    while pos < str_offset:
        sec_off, entry_count = struct.unpack_from("<HH", data, pos)
        pos += 4
        out.append(f"[{get_str(sec_off)}]")
        for _ in range(entry_count):
            name_off, value_count = struct.unpack_from("<HB", data, pos)
            pos += 3
            vals: list[str] = []
            for _ in range(value_count):
                vtype = data[pos]
                pos += 1
                if vtype == 1:    # integer
                    vals.append(str(struct.unpack_from("<i", data, pos)[0]))
                elif vtype == 2:  # float
                    f = struct.unpack_from("<f", data, pos)[0]
                    vals.append(f"{f:.6f}".rstrip("0").rstrip(".") if f % 1 else str(int(f)))
                else:             # string
                    vals.append(get_str(struct.unpack_from("<I", data, pos)[0]))
                pos += 4
            name = get_str(name_off)
            out.append(f"{name} = {', '.join(vals)}" if vals else name)
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------
# PE resource extraction (names + infocards straight from the DLLs,
# replacing FLInfocardIE)
# ------------------------------------------------------------------

RT_STRING = 6
RT_HTML = 23


def _pe_resources(path: str) -> dict[int, dict[int, bytes]]:
    """Return {resource_type: {resource_id: raw_bytes}} for a PE file."""
    with open(path, "rb") as f:
        data = f.read()

    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError(f"{path}: not a PE file")
    num_sections, = struct.unpack_from("<H", data, e_lfanew + 6)
    opt_size, = struct.unpack_from("<H", data, e_lfanew + 20)
    opt_off = e_lfanew + 24
    magic, = struct.unpack_from("<H", data, opt_off)
    ddir_off = opt_off + (96 if magic == 0x10B else 112)  # PE32 / PE32+
    rsrc_rva, rsrc_size = struct.unpack_from("<II", data, ddir_off + 2 * 8)
    if not rsrc_rva:
        return {}

    # Section table: map RVA -> file offset
    sections = []
    sec_off = opt_off + opt_size
    for i in range(num_sections):
        off = sec_off + i * 40
        va, raw_size, raw_ptr = struct.unpack_from("<III", data, off + 12)
        virt_size = struct.unpack_from("<I", data, off + 8)[0]
        sections.append((va, max(virt_size, raw_size), raw_ptr))

    def rva_to_off(rva: int) -> int:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + (rva - va)
        raise ValueError("bad RVA")

    rsrc_base = rva_to_off(rsrc_rva)

    def read_dir(dir_off: int) -> list[tuple[int, int, bool]]:
        """Yield (id, offset, is_subdir) entries of a resource directory."""
        n_named, n_id = struct.unpack_from("<HH", data, rsrc_base + dir_off + 12)
        entries = []
        for i in range(n_named + n_id):
            name, off = struct.unpack_from("<II", data, rsrc_base + dir_off + 16 + i * 8)
            entries.append((name & 0x7FFFFFFF, off & 0x7FFFFFFF, bool(off & 0x80000000)))
        return entries

    result: dict[int, dict[int, bytes]] = {}
    for rtype, t_off, t_sub in read_dir(0):
        if rtype not in (RT_STRING, RT_HTML) or not t_sub:
            continue
        bucket = result.setdefault(rtype, {})
        for rid, id_off, id_sub in read_dir(t_off):
            if not id_sub:
                continue
            # First language entry
            langs = read_dir(id_off)
            if not langs:
                continue
            _, leaf_off, leaf_sub = langs[0]
            if leaf_sub:
                continue
            data_rva, size = struct.unpack_from("<II", data, rsrc_base + leaf_off)
            bucket[rid] = data[rva_to_off(data_rva):rva_to_off(data_rva) + size]
    return result


def _decode_html_resource(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            text = raw.decode("windows-1252", errors="replace")
    return text.replace("\ufeff", "").replace("\r", " ").replace("\n", " ").strip()


def extract_infocards(fl_path: str, out_path: str) -> int:
    """Extract all names (string tables) and infocards (HTML resources) from the
    game's resource DLLs into infocards.txt (id/text line pairs)."""
    exe_dir = os.path.join(fl_path, "EXE")
    fl_ini_path = os.path.join(exe_dir, "freelancer.ini")
    with open(fl_ini_path, "rb") as f:
        raw = f.read()
    ini_text = bini_decode(raw) if is_bini(raw) else raw.decode("windows-1252", errors="replace")

    # [Resources] DLL list; index 0 is resources.dll, listed DLLs start at 65536
    dlls = ["resources.dll"]
    in_resources = False
    for line in ini_text.splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            in_resources = line.lower() == "[resources]"
            continue
        if in_resources and "=" in line:
            key, val = line.split("=", 1)
            if key.strip().lower() == "dll":
                dlls.append(val.strip())

    entries: dict[int, str] = {}
    for idx, dll in enumerate(dlls):
        dll_path = os.path.join(exe_dir, dll)
        if not os.path.isfile(dll_path):
            log.warning("Missing resource DLL: %s", dll)
            continue
        try:
            resources = _pe_resources(dll_path)
        except Exception as e:
            log.warning("Failed to parse %s: %s", dll, e)
            continue
        base = idx * 65536
        # String tables: block id N holds 16 strings (N-1)*16 .. (N-1)*16+15
        for block_id, raw_block in resources.get(RT_STRING, {}).items():
            pos = 0
            for j in range(16):
                if pos + 2 > len(raw_block):
                    break
                length = struct.unpack_from("<H", raw_block, pos)[0]
                pos += 2
                if length:
                    s = raw_block[pos:pos + length * 2].decode("utf-16-le", errors="replace")
                    s = s.replace("\r", " ").replace("\n", " ").strip()
                    if s:
                        entries[base + (block_id - 1) * 16 + j] = s
                    pos += length * 2
        # HTML resources: XML infocards
        for rid, raw_res in resources.get(RT_HTML, {}).items():
            text = _decode_html_resource(raw_res)
            if text:
                entries[base + rid] = text

    if not entries:
        raise ValueError("no strings extracted - is this a Freelancer install?")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ids in sorted(entries):
            text = entries[ids]
            # The id/text line-pair format cannot represent the reserved
            # marker words used by the legacy FLInfocardIE format
            if text in ("NAME", "INFOCARD"):
                continue
            f.write(f"{ids}\n{text}\n")
    return len(entries)


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
    # Decode compiled BINI INIs to plain text transparently
    if os.path.splitext(src)[1].lower() == ".ini":
        with open(src, "rb") as f:
            data = f.read()
        if is_bini(data):
            with open(dst, "w", encoding="utf-8") as f:
                f.write(bini_decode(data))
            return
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
