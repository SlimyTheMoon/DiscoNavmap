from __future__ import annotations

import gzip
import io
import json
import logging
import os
import sys

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from markupsafe import Markup

from gamedata import GameData, OORP_SYSTEMS, parse_infocard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")

gd: GameData | None = None
all_systems_gzipped: bytes = b""

POBS_API_URL = "https://darkstat.dd84ai.com/api/pobs"
pobs_cache: list[dict] = []
pobs_by_system: dict[str, list[dict]] = {}


def no_escape_json(value):
    """Jinja2 filter that serializes to JSON without escaping HTML."""
    return Markup(json.dumps(value, ensure_ascii=False))


app.jinja_env.filters["noescapejson"] = no_escape_json
app.jinja_env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}


def load_game_data(data_dir: str) -> None:
    global gd, all_systems_gzipped
    if not os.path.isdir(data_dir):
        log.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    log.info("Loading game data from %s...", data_dir)
    gd = GameData.load(data_dir)
    log.info(
        "Loaded %d systems, %d bases, %d factions, %d commodities, %d infocards",
        len(gd.systems), len(gd.bases), len(gd.factions),
        len(gd.commodities), len(gd.infocards),
    )

    log.info("Pre-computing all system details...")
    gd.precompute_all_details()
    log.info("Pre-computed %d system details", len(gd.all_system_details))

    # Pre-serialize and gzip
    raw = json.dumps(gd.all_system_details, ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        gz.write(raw)
    all_systems_gzipped = buf.getvalue()
    log.info("All-systems payload: %d KB raw, %d KB gzipped", len(raw) // 1024, len(all_systems_gzipped) // 1024)


def fetch_pobs() -> None:
    global pobs_cache, pobs_by_system
    import urllib.request
    import html as htmlmod
    try:
        log.info("Fetching POBs from %s ...", POBS_API_URL)
        req = urllib.request.Request(POBS_API_URL, headers={"User-Agent": "DiscoNavmap/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        pobs_cache = []
        pobs_by_system = {}
        for pob in raw:
            sys_nick = (pob.get("system_nickname") or "").lower()
            base_pos = pob.get("base_pos")
            if not sys_nick or not base_pos:
                continue
            name = htmlmod.unescape(pob.get("name", ""))
            entry = {
                "name": name,
                "pos": [base_pos.get("X", 0), base_pos.get("Y", 0), base_pos.get("Z", 0)],
                "systemNickname": sys_nick,
                "factionName": pob.get("faction_name") or "",
                "level": pob.get("level"),
            }
            pobs_cache.append(entry)
            pobs_by_system.setdefault(sys_nick, []).append(entry)
        log.info("Loaded %d POBs across %d systems", len(pobs_cache), len(pobs_by_system))
    except Exception as e:
        log.warning("Failed to fetch POBs: %s", e)


# ------------------------------------------------------------------
# Page routes
# ------------------------------------------------------------------

@app.route("/")
def handle_index():
    assert gd is not None
    return render_template(
        "index.html",
        systems={k: v.to_dict() for k, v in gd.systems.items()},
        connections=[c.to_dict() for c in gd.connections],
        search_items=[s.to_dict() for s in gd.search_items],
        oorp_systems=OORP_SYSTEMS,
    )


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------

@app.route("/api/systems")
def handle_api_systems():
    assert gd is not None
    data = {k: v.to_dict() for k, v in gd.systems.items()}
    return jsonify(data)


@app.route("/api/systems/all")
def handle_api_all_system_details():
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        return Response(
            all_systems_gzipped,
            content_type="application/json",
            headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=3600"},
        )
    # Fallback: decompress
    raw = gzip.decompress(all_systems_gzipped)
    return Response(raw, content_type="application/json", headers={"Cache-Control": "public, max-age=3600"})


@app.route("/api/system/<nick>")
def handle_api_system_detail(nick: str):
    assert gd is not None
    nick = nick.lower().strip()
    if not nick:
        return Response("system nickname required", status=400)
    detail = gd.get_system_detail(nick)
    if not detail:
        return Response(f"system {nick!r} not found", status=404)
    return jsonify(detail.to_dict())


@app.route("/api/connections")
def handle_api_connections():
    assert gd is not None
    data = [c.to_dict() for c in gd.connections]
    return jsonify(data)


@app.route("/api/search")
def handle_api_search():
    assert gd is not None
    query = request.args.get("q", "")
    if len(query) < 2:
        return jsonify([])
    results = gd.search(query)
    return jsonify([r.to_dict() for r in results])


@app.route("/api/infocard/<id>")
def handle_api_infocard(id: str):
    assert gd is not None
    id = id.strip()
    if not id:
        return Response("infocard id required", status=400)
    text = gd.infocards.get(id)
    if text is None:
        return Response("infocard not found", status=404)
    mapped = ""
    mapped_id = gd.infocard_map.get(id)
    if mapped_id:
        mapped_text = gd.infocards.get(mapped_id)
        if mapped_text:
            mapped = parse_infocard(mapped_text)
    return jsonify({"id": id, "text": parse_infocard(text), "mapped": mapped})


@app.route("/api/faction/<nick>")
def handle_api_faction(nick: str):
    assert gd is not None
    nick = nick.lower().strip()
    if not nick:
        return Response("faction nickname required", status=400)
    f = gd.factions.get(nick)
    if f:
        name = f.name
        if not name and f.ids_name:
            name = gd.resolve_name(f.ids_name)
        if name:
            return jsonify({"name": name})
    return Response("faction not found", status=404)


@app.route("/api/pobs")
def handle_api_pobs():
    resp = jsonify(pobs_cache)
    resp.headers["Cache-Control"] = "max-age=3600"
    return resp


@app.route("/api/pobs/system/<nick>")
def handle_api_pobs_by_system(nick: str):
    nick = nick.lower().strip()
    if not nick:
        return Response("system nickname required", status=400)
    resp = jsonify(pobs_by_system.get(nick, []))
    resp.headers["Cache-Control"] = "max-age=3600"
    return resp


# ------------------------------------------------------------------
# Static files
# ------------------------------------------------------------------

@app.route("/styles/<path:filename>")
def serve_styles(filename):
    return send_from_directory("styles", filename)


@app.route("/images/<path:filename>")
def serve_images(filename):
    return send_from_directory("images", filename)


@app.route("/textures/<path:filename>")
def serve_textures(filename):
    resp = send_from_directory("textures", filename)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/scripts/<path:filename>")
def serve_scripts(filename):
    return send_from_directory("scripts", filename)


# ------------------------------------------------------------------
# Data files (served dynamically like static site, needed by app.js)
# ------------------------------------------------------------------

@app.route("/data/systems-all.json")
def serve_systems_all():
    assert gd is not None
    resp = Response(all_systems_gzipped, content_type="application/json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=3600"})
    if "gzip" not in request.headers.get("Accept-Encoding", ""):
        resp = Response(gzip.decompress(all_systems_gzipped), content_type="application/json",
                        headers={"Cache-Control": "public, max-age=3600"})
    return resp


_infocards_cache: bytes | None = None
_factions_cache: bytes | None = None


@app.route("/data/infocards.json")
def serve_infocards():
    global _infocards_cache
    assert gd is not None
    if _infocards_cache is None:
        data = {}
        for id_str, text in gd.infocards.items():
            entry = {"text": parse_infocard(text)}
            mapped_id = gd.infocard_map.get(id_str)
            if mapped_id:
                mapped_text = gd.infocards.get(mapped_id)
                if mapped_text:
                    entry["mapped"] = parse_infocard(mapped_text)
            data[id_str] = entry
        _infocards_cache = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(_infocards_cache, content_type="application/json",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.route("/data/factions.json")
def serve_factions():
    global _factions_cache
    assert gd is not None
    if _factions_cache is None:
        data = {}
        for nick, f in gd.factions.items():
            name = f.name
            if not name and f.ids_name:
                name = gd.resolve_name(f.ids_name)
            if name:
                data[nick] = name
        _factions_cache = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(_factions_cache, content_type="application/json",
                    headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Discovery Navmap HTTP Server")
    parser.add_argument("-data", default="data/v5.3p2h5", help="Path to game data directory")
    parser.add_argument("-addr", default=":8080", help="Listen address (e.g. :8080)")
    args = parser.parse_args()

    addr = args.addr.lstrip(":")
    host = "0.0.0.0"
    port = 8080
    if addr:
        if ":" in addr:
            host_part, port_part = addr.rsplit(":", 1)
            host = host_part or "0.0.0.0"
            port = int(port_part)
        elif addr.isdigit():
            port = int(addr)

    load_game_data(args.data)
    fetch_pobs()
    log.info("Serving on http://localhost:%d", port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
