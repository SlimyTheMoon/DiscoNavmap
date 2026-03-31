from __future__ import annotations

import json
import logging
import os
import shutil
import sys

# Add parent directory to path so we can import gamedata
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gamedata import GameData, OORP_SYSTEMS, parse_infocard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

POBS_API_URL = "https://darkstat.dd84ai.com/api/pobs"


def fetch_pobs_for_static() -> list[dict]:
    import urllib.request
    import html as htmlmod
    try:
        log.info("Fetching POBs from %s ...", POBS_API_URL)
        req = urllib.request.Request(POBS_API_URL, headers={"User-Agent": "DiscoNavmap/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        pobs = []
        for pob in raw:
            sys_nick = (pob.get("system_nickname") or "").lower()
            base_pos = pob.get("base_pos")
            if not sys_nick or not base_pos:
                continue
            name = htmlmod.unescape(pob.get("name", ""))
            pobs.append({
                "name": name,
                "pos": [base_pos.get("X", 0), base_pos.get("Y", 0), base_pos.get("Z", 0)],
                "systemNickname": sys_nick,
                "factionName": pob.get("faction_name") or "",
                "level": pob.get("level"),
            })
        log.info("Loaded %d POBs", len(pobs))
        return pobs
    except Exception as e:
        log.warning("Failed to fetch POBs: %s", e)
        return []


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Discovery Navmap Static Site Generator")
    parser.add_argument("-data", default="data/v5.3p2h5", help="Path to game data directory")
    parser.add_argument("-out", default="docs", help="Output directory for static site")
    args = parser.parse_args()

    # Load game data
    log.info("Loading game data from %s...", args.data)
    gd = GameData.load(args.data)
    log.info(
        "Loaded %d systems, %d bases, %d factions, %d commodities, %d infocards",
        len(gd.systems), len(gd.bases), len(gd.factions),
        len(gd.commodities), len(gd.infocards),
    )

    gd.precompute_all_details()
    log.info("Pre-computed %d system details", len(gd.all_system_details))

    # Create output directories
    os.makedirs(os.path.join(args.out, "data"), exist_ok=True)

    # 1. Generate data/systems-all.json
    log.info("Generating data/systems-all.json...")
    write_json_file(os.path.join(args.out, "data", "systems-all.json"), gd.all_system_details)

    # 2. Generate data/infocards.json (pre-rendered HTML)
    log.info("Generating data/infocards.json...")
    infocards = {}
    for id_str, text in gd.infocards.items():
        entry = {"text": parse_infocard(text)}
        mapped_id = gd.infocard_map.get(id_str)
        if mapped_id:
            mapped_text = gd.infocards.get(mapped_id)
            if mapped_text:
                entry["mapped"] = parse_infocard(mapped_text)
        infocards[id_str] = entry
    write_json_file(os.path.join(args.out, "data", "infocards.json"), infocards)

    # 3. Generate data/factions.json (nick -> display name)
    log.info("Generating data/factions.json...")
    factions = {}
    for nick, f in gd.factions.items():
        name = f.name
        if not name and f.ids_name:
            name = gd.resolve_name(f.ids_name)
        if name:
            factions[nick] = name
    write_json_file(os.path.join(args.out, "data", "factions.json"), factions)

    # 4. Generate data/pobs.json
    log.info("Generating data/pobs.json...")
    pobs = fetch_pobs_for_static()
    write_json_file(os.path.join(args.out, "data", "pobs.json"), pobs)

    # 5. Generate index.html from template
    log.info("Generating index.html...")
    generate_index_html(gd, pobs, args.out)

    # 5. Copy static assets
    for dir_name in ["styles", "images", "textures", "scripts"]:
        src = dir_name
        dst = os.path.join(args.out, dir_name)
        log.info("Copying %s/ -> %s/...", src, dst)
        if os.path.isdir(src):
            copy_dir(src, dst)

    # 6. Create .nojekyll marker for GitHub Pages
    with open(os.path.join(args.out, ".nojekyll"), "w"):
        pass

    # Print summary
    print_file_sizes(args.out)
    log.info("Static site generated successfully in %s/", args.out)


def generate_index_html(gd: GameData, pobs: list[dict], out_dir: str) -> None:
    # Read the Jinja2 template source
    with open(os.path.join("templates", "index.html"), encoding="utf-8") as f:
        tmpl = f.read()

    # Strip Jinja2 template block markers if present
    tmpl = tmpl.replace("{% block content %}", "").replace("{% endblock %}", "")

    # Serialize data as compact JSON
    systems_json = json.dumps({k: v.to_dict() for k, v in gd.systems.items()}, ensure_ascii=False)
    connections_json = json.dumps([c.to_dict() for c in gd.connections], ensure_ascii=False)
    search_items_json = json.dumps([s.to_dict() for s in gd.search_items], ensure_ascii=False)
    oorp_json = json.dumps(OORP_SYSTEMS, ensure_ascii=False)

    # Replace Jinja2 template expressions with actual JSON data
    # The template uses {{ systems | noescapejson }} etc.
    tmpl = tmpl.replace("{{ systems | noescapejson }}", systems_json)
    tmpl = tmpl.replace("{{ connections | noescapejson }}", connections_json)
    tmpl = tmpl.replace("{{ search_items | noescapejson }}", search_items_json)
    tmpl = tmpl.replace("{{ oorp_systems | noescapejson }}", oorp_json)

    # Convert absolute paths to relative paths for GitHub Pages
    tmpl = tmpl.replace('href="/images/', 'href="images/')
    tmpl = tmpl.replace('href="/styles/', 'href="styles/')
    tmpl = tmpl.replace('src="/scripts/', 'src="scripts/')

    # Remove any remaining Jinja2 syntax
    import re
    tmpl = re.sub(r"\{\{.*?\}\}", "", tmpl)

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(tmpl)


def write_json_file(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def copy_dir(src: str, dst: str) -> None:
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def print_file_sizes(out_dir: str) -> None:
    data_dir = os.path.join(out_dir, "data")
    if not os.path.isdir(data_dir):
        return
    print("\n--- Output file sizes ---")
    for name in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, name)
        if os.path.isfile(path):
            size_mb = os.path.getsize(path) / 1024 / 1024
            print(f"  data/{name}: {size_mb:.2f} MB")
    index_path = os.path.join(out_dir, "index.html")
    if os.path.isfile(index_path):
        size_mb = os.path.getsize(index_path) / 1024 / 1024
        print(f"  index.html: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
