"""Discovery Navmap static site builder.

Single entry point (static site generation):

    python build.py                    # build into docs/ from default game data
    python build.py -data data/vX -out docs

Steps:
  1. Parse game data (gamedata package)
  2. Write docs/data/universe.js   - systems, connections, search index (loaded as plain <script>)
  3. Write docs/data/*.json        - systems-all, infocards, factions, pobs
  4. Copy index.html + static assets (scripts/, styles/, images/, textures/)

No HTML templating involved: templates/index.html is plain static HTML and is
copied verbatim. All data lives in external files under docs/data/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gamedata import GameData, OORP_SYSTEMS, parse_infocard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

POBS_FALLBACK_API_URL = "https://darkstat.dd84ai.com/api/pobs"
DISCOVERYGC_API_URL = "https://discoverygc.com/forums/base_admin.php?action=getjson"

STATIC_DIRS = ["scripts", "styles", "images", "textures"]


# ------------------------------------------------------------------
# PoB fetching (Discovery GC primary, public PoB API fallback)
# ------------------------------------------------------------------

def _fl_hash(nickname: str) -> int:
    """Compute FLHash for a Freelancer nickname string."""
    POLY = 0xA001 << 14  # 0x28004000
    table = [0] * 256
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ POLY
            else:
                crc >>= 1
        table[i] = crc
    crc = 0
    for b in nickname.lower().encode("utf-8"):
        crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
    b0, b1, b2, b3 = (crc >> 24) & 0xFF, (crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF
    rev = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
    return ((rev >> 2) | 0x80000000) & 0xFFFFFFFF


def _list_to_csv(val) -> str:
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v)
    return val or ""


def _fetch_discoverygc(system_nicks: list[str]) -> list[dict]:
    """Fetch full PoB data from the Discovery GC API (has infocard, dock lists)."""
    import urllib.request
    hash_to_nick = {_fl_hash(nick): nick for nick in system_nicks}
    log.info("Fetching POBs from %s ...", DISCOVERYGC_API_URL)
    req = urllib.request.Request(DISCOVERYGC_API_URL, headers={"User-Agent": "DiscoNavmap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pobs = []
    for name, base in data.get("bases", {}).items():
        parts = (base.get("pos") or "0, 0, 0").split(",")
        x = int(float(parts[0].strip())) if parts[0].strip() else 0
        y = int(float(parts[1].strip())) if len(parts) > 1 and parts[1].strip() else 0
        z = int(float(parts[2].strip())) if len(parts) > 2 and parts[2].strip() else 0
        sys_nick = hash_to_nick.get(base.get("system"), "")
        if not sys_nick:
            continue
        pobs.append({
            "name": name,
            "pos": [x, y, z],
            "systemNickname": sys_nick,
            "affiliation": base.get("affiliation"),
            "defenseMode": base.get("defensemode"),
            "infotext": base.get("infocard_paragraphs") or [],
            "hostileTags": _list_to_csv(base.get("hostile_tag_list")),
            "hostileNames": _list_to_csv(base.get("hostile_name_list")),
            "allyTags": _list_to_csv(base.get("ally_tag_list")),
            "allyNames": _list_to_csv(base.get("ally_name_list")),
        })
    log.info("Loaded %d POBs from Discovery GC", len(pobs))
    return pobs


def _fetch_pobs_fallback() -> list[dict]:
    """Fallback: fetch PoB data from the public PoB API (limited fields)."""
    import urllib.request
    import html as htmlmod
    log.info("Fetching POBs from %s ...", POBS_FALLBACK_API_URL)
    req = urllib.request.Request(POBS_FALLBACK_API_URL, headers={"User-Agent": "DiscoNavmap/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    pobs = []
    for pob in raw:
        sys_nick = (pob.get("system_nickname") or "").lower()
        base_pos = pob.get("base_pos")
        if not sys_nick or not base_pos:
            continue
        pobs.append({
            "name": htmlmod.unescape(pob.get("name", "")),
            "pos": [base_pos.get("X", 0), base_pos.get("Y", 0), base_pos.get("Z", 0)],
            "systemNickname": sys_nick,
            "factionName": pob.get("faction_name") or "",
            "defenseMode": pob.get("defense_mode"),
        })
    log.info("Loaded %d POBs from fallback API", len(pobs))
    return pobs


def fetch_pobs(system_nicks: list[str] | None = None) -> list[dict]:
    pobs = None
    try:
        pobs = _fetch_discoverygc(system_nicks or [])
    except Exception as e:
        log.warning("Discovery GC API failed (%s), using fallback PoB API", e)
    if pobs is None:
        try:
            return _fetch_pobs_fallback()
        except Exception as e2:
            log.warning("Fallback PoB API also failed: %s", e2)
            return []
    # Merge faction names from the fallback API into Discovery GC results
    try:
        name_to_faction = {}
        for dp in _fetch_pobs_fallback():
            key = (dp.get("systemNickname", "").lower() + "|" + dp.get("name", "")).lower()
            if dp.get("factionName"):
                name_to_faction[key] = dp["factionName"]
        merged = 0
        for p in pobs:
            key = (p.get("systemNickname", "").lower() + "|" + p.get("name", "")).lower()
            fn = name_to_faction.get(key, "")
            if fn:
                p["factionName"] = fn
                merged += 1
        log.info("Merged %d faction names from fallback API", merged)
    except Exception as e:
        log.warning("Could not merge fallback PoB faction data: %s", e)
    return pobs


# ------------------------------------------------------------------
# Data generation
# ------------------------------------------------------------------

def build_universe_js(gd: GameData) -> str:
    """Universe payload as a plain script defining `serverData` (no inline HTML clutter)."""
    payload = {
        "systems": {k: v.to_dict() for k, v in gd.systems.items()},
        "connections": [c.to_dict() for c in gd.connections],
        "searchItems": [s.to_dict() for s in gd.search_items],
        "oorpSystems": OORP_SYSTEMS,
    }
    return "var serverData = " + json.dumps(payload, ensure_ascii=False) + ";\n"


def build_infocards(gd: GameData) -> dict:
    infocards = {}
    for id_str, text in gd.infocards.items():
        entry = {"text": parse_infocard(text)}
        mapped_id = gd.infocard_map.get(id_str)
        if mapped_id:
            mapped_text = gd.infocards.get(mapped_id)
            if mapped_text:
                entry["mapped"] = parse_infocard(mapped_text)
        infocards[id_str] = entry
    return infocards


def build_factions(gd: GameData) -> dict:
    factions = {}
    for nick, f in gd.factions.items():
        name = f.name
        if not name and f.ids_name:
            name = gd.resolve_name(f.ids_name)
        if name:
            factions[nick] = name
    return factions


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------

def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def copy_dir(src: str, dst: str) -> None:
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def print_summary(out_dir: str) -> None:
    print("\n--- Output file sizes ---")
    for rel in ["index.html"] + sorted(
        os.path.join("data", n) for n in os.listdir(os.path.join(out_dir, "data"))
    ):
        path = os.path.join(out_dir, rel)
        if os.path.isfile(path):
            print(f"  {rel}: {os.path.getsize(path) / 1024:.0f} KB")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Discovery Navmap Static Site Builder")
    parser.add_argument("-data", default="data/v5.3p2h5", help="Path to game data directory")
    parser.add_argument("-out", default="docs", help="Output directory for static site")
    parser.add_argument("--skip-pobs", action="store_true", help="Skip fetching player bases")
    args = parser.parse_args(argv)

    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    log.info("Loading game data from %s...", args.data)
    gd = GameData.load(args.data)
    log.info(
        "Loaded %d systems, %d bases, %d factions, %d commodities, %d infocards",
        len(gd.systems), len(gd.bases), len(gd.factions),
        len(gd.commodities), len(gd.infocards),
    )
    gd.precompute_all_details()
    log.info("Pre-computed %d system details", len(gd.all_system_details))

    data_dir = os.path.join(args.out, "data")
    os.makedirs(data_dir, exist_ok=True)

    log.info("Writing data/universe.js...")
    write_text(os.path.join(data_dir, "universe.js"), build_universe_js(gd))

    log.info("Writing data/systems-all.json...")
    write_json(os.path.join(data_dir, "systems-all.json"), gd.all_system_details)

    log.info("Writing data/infocards.json...")
    write_json(os.path.join(data_dir, "infocards.json"), build_infocards(gd))

    log.info("Writing data/factions.json...")
    write_json(os.path.join(data_dir, "factions.json"), build_factions(gd))

    if args.skip_pobs:
        log.info("Skipping POB fetch (--skip-pobs)")
    else:
        log.info("Writing data/pobs.json...")
        write_json(os.path.join(data_dir, "pobs.json"), fetch_pobs(list(gd.systems.keys())))

    log.info("Copying index.html...")
    with open(os.path.join("templates", "index.html"), encoding="utf-8") as f:
        index_html = f.read()
    # Cache busting: stamp asset URLs with the build time so browsers pick up
    # new script/style/data versions after every build
    build_version = str(int(time.time()))
    index_html = index_html.replace("{BUILD_VERSION}", build_version)
    write_text(os.path.join(args.out, "index.html"), index_html)

    for dir_name in STATIC_DIRS:
        if os.path.isdir(dir_name):
            log.info("Copying %s/ ...", dir_name)
            copy_dir(dir_name, os.path.join(args.out, dir_name))

    # GitHub Pages marker
    with open(os.path.join(args.out, ".nojekyll"), "w"):
        pass

    print_summary(args.out)
    log.info("Static site generated successfully in %s/", args.out)


if __name__ == "__main__":
    main()
