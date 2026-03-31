# Navmap <img height="40" align="left" src="https://github.com/AudunVN/Navmap/blob/gh-pages/favicon.png">

A browser-based map viewer for the Freelancer mod [Discovery](https://discoverygc.com/). Displays accurately the full universe map with system details, bases, zones, connections, infocards, Player Owned Stations, and more.

## Credits & History

- Originally made by **Error** via [this repo](https://github.com/AudunVN/Navmap)
- Forked from **fifthbarrier**
- Sigma coloring rework and server-rules alignment by **Cherry Blossom**
- Refactored into **Go** with static site generation (published 25.03.2026)
- Rewritten into **Python** (Flask) (published 31.03.2026)

A complete change and issue log from before this project was moved to GitHub may be found in [this DiscoveryGC forum thread](http://discoverygc.com/forums/showthread.php?tid=132266&pid=1700007#pid1700007).

## Requirements

- Python 3.11+
- Flask 3.0+ (`pip install -r requirements.txt`)
- A Discovery Freelancer installation (for data updates only)

## Quick Start

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run as HTTP server

```bash
python main.py -data data/v5.3p2h5 -addr :8080
```

Then open `http://localhost:8080`.

| Flag | Default | Description |
|------|---------|-------------|
| `-data` | `data/v5.3p2h5` | Path to game data directory |
| `-addr` | `:8080` | Listen address |

### Build static site (for GitHub Pages)

```bash
python -m cmd_py.static -data data/v5.3p2h5 -out docs
```

Generates a self-contained static site in `docs/` with all JSON data inlined/pre-built. The `docs/` folder contains the current deployed build.

| Flag | Default | Description |
|------|---------|-------------|
| `-data` | `data/v5.3p2h5` | Path to game data directory |
| `-out` | `dist` | Output directory for static site |

### Docker

Generate a Dockerfile for either serving mode:

```bash
python generate_dockerfile.py flask    # Full Flask app
python generate_dockerfile.py static   # Static site via nginx
```

Then build and run:

```bash
docker build -t disconavmap .
docker run -p 8080:8080 disconavmap        # flask mode
docker run -p 80:80 disconavmap            # static mode
```

## Updating Game Data

Import data from a Discovery Freelancer installation:

```bash
python -m cmd_py.update -out data/v5.3p2h5
```

| Flag | Default | Description |
|------|---------|-------------|
| `-config` | `update/build.json` | Path to build.json config file |
| `-out` | *(required)* | Output directory |

This will auto-discover your FL install via `LOCALAPPDATA`, copy and format the required game files, and lowercase all filenames. You'll be prompted to run **FL Path Generator** and **FLInfocardIE** first.

## Project Structure

| Path | Purpose |
|------|---------|
| `main.py` | Flask HTTP server entry point |
| `gamedata/` | Core data package |
| `gamedata/types.py` | Data classes — System, Base, Faction, Connection, etc. |
| `gamedata/parser.py` | INI parser, system detail loader, infocard renderer |
| `cmd_py/static.py` | Static site generator |
| `cmd_py/update.py` | Game data importer from FL install |
| `generate_dockerfile.py` | Generates a Dockerfile for flask or static serving |
| `data/v5.3p2h5/` | Parsed Discovery game data (current version) |
| `templates/` | Jinja2 HTML template for the map UI |
| `scripts/` | Frontend JS (`app.js` — map rendering & UI, `panzoom.min.js`) |
| `styles/` | CSS |
| `images/` | Icons and map background images |
| `textures/` | Planet/star textures (`.txm` subdirs) |
| `docs/` | GitHub Pages deployment (pre-built static site) |
| `archive/` | Legacy versions |
| `requirements.txt` | Python dependencies |
| `pyproject.toml` | Project metadata |

## API Endpoints (server mode)

All endpoints are served by the Flask server (`main.py`) running on the configured port (default 8080). Data is loaded from the game data directory at startup.

| Endpoint | Description |
|----------|-------------|
| `GET /api/systems` | Returns a dictionary of all systems with lightweight data (nickname, name, class, position, scale, OORP flag). Parsed from `universe/universe.ini` at startup. |
| `GET /api/systems/all` | Returns all system details as a single JSON blob (zones, objects, bases, asteroids, etc.). Pre-computed at startup and served gzip-compressed when the client sends `Accept-Encoding: gzip`. |
| `GET /api/system/{nick}` | Returns full detail for a single system by nickname (e.g. `br01`). Parsed on-the-fly from the per-system `.ini` file in `universe/systems/`. Returns 404 if not found. |
| `GET /api/connections` | Returns all jump gate/hole connections as a JSON array. Built at startup from `systems_shortest_path.ini` (all connections) and `shortest_legal_path.ini` (nomad gate connections, marked with `jgOnly`). |
| `GET /api/search?q=...` | Returns matching systems and bases for autocomplete queries (minimum 2 characters). Searches pre-built `search_items` list loaded from universe and base data at startup. |
| `GET /api/infocard/{id}` | Returns a parsed infocard by its numeric ID from `infocards.txt`. Response includes `text` (parsed HTML) and optionally `mapped` (linked infocard from `infocardmap.ini`). Returns 404 if ID not found. |
| `GET /api/faction/{nick}` | Returns faction name by nickname (e.g. `fc_outriders`). Loaded from `initialworld.ini` at startup with names resolved from `infocards.txt`. Returns 404 if not found. |
| `GET /api/pobs` | Returns all Player Owned Stations as a JSON array. Fetched live from `https://discoverygc.com/forums/base_admin.php?action=getjson` with full infocard, affiliation, defense mode, and dock lists. Cached in memory at startup. |
| `GET /api/pobs/system/{nick}` | Returns POBs filtered by system nickname (e.g. `rh01`). Uses the same cached data as `/api/pobs`. Returns empty array if no POBs in that system. |
| `GET /data/systems-all.json` | Pre-computed system details JSON, served gzip-compressed. This is the main data file fetched by `app.js` on page load to render all system views client-side. |
| `GET /data/infocards.json` | All parsed infocards as a `{id: {text, mapped}}` dictionary. Infocard XML is converted to HTML at startup via `parse_infocard()`. Used by the frontend for base/object infocard popups. |
| `GET /data/factions.json` | Faction nickname-to-name lookup dictionary. Built at startup from `initialworld.ini` with names resolved from infocards. Used by the frontend for faction labels. |

## How It Works

### Data loading

The `gamedata.parser.GameData.load()` method reads game data files in this order:

1. `special_systems.txt` — maps system nicknames to display names and two-letter class codes (li, br, ku, etc.)
2. `infocards.txt` — pairs of ID / text for names and descriptions
3. `infocardmap.ini` — maps infocard IDs to alternate infocard IDs
4. `solararch.ini` — solar archetype definitions (planets, stars, textures, radii)
5. `multiuniverse.ini` — identifies "Lost Sector" (sector03) systems to exclude
6. `universe/universe.ini` — systems and bases with positions
7. `initialworld.ini` — faction definitions
8. `select_equip.ini` — commodity definitions
9. Connection path files — `systems_shortest_path.ini` (all connections) and `shortest_legal_path.ini` (jump gate only)

### System detail loading

When viewing a system, `GameData.get_system_detail()` reads the per-system `.ini` file (e.g. `universe/systems/br01/br01.ini`) and parses:

- **Ambient color** from `[Ambient]` sections
- **Zones** from `[Zone]` sections (position, size, shape, rotation, fog, flags, mineable loot)
- **Objects** from `[Object]` sections (bases, planets, stars, jump gates/holes, wrecks, tradelanes)
- **Asteroid data** from referenced asteroid `.ini` files for mineable zone info

Objects are classified into CSS classes (`planet`, `base`, `star`, `jump`, `gate`, `hole`, `wreck`, `tradelane`, etc.) based on the presence of specific keys in the section.

### Frontend

The frontend (`scripts/app.js`) handles all rendering client-side:

- Universe map: plots systems as colored dots using positions from the server
- System map: renders zones and objects as positioned divs with textures
- Pan & zoom via `panzoom.min.js`
- Search autocomplete, infocard modals, configurable display options
- All system details are pre-fetched from `/data/systems-all.json` on page load
- POB infocards fetched live from [Discovery GC API](https://discoverygc.com) with hourly auto-refresh

## Texture & Icon Data

Textures are extracted using [UTF Image Exporter](https://github.com/AudunVN/Navmap/tree/gh-pages/utils/UTFImageExporter), then bulk converted from txm to jpg using IrFanView, and afterwards recursively renamed counting up from `01.jpg` using Metamorphose2 to ensure that there's at least one texture available from each `.txm` file (the navmap expects a file named `01.jpg` inside each txm folder).

Icons are converted from TGA after being exported using ImageMagick or similar:
```bash
mogrify -flip -path png -format png *.tga
```

## Map Features

- Interactive universe map with pan & zoom
- System detail view with bases, planets, zones, wrecks, and jump connections
- Mineable zone labels showing commodity names (e.g. Osmium Ore, Gold Ore)
- Dynamic anti-label overlap: labels automatically spread apart on both axes to stay readable, and re-resolve on zoom/pan
- Nomad gate connections with distinct purple styling
- Unstable connections with red styling
- Player Owned Stations (POBs) with live infocards from [Discovery GC API](https://discoverygc.com), refreshed hourly — shows affiliation, defense mode, dock access lists, and infocard text
- Faction infocards with affiliation display on POBs (both live and static modes)
- Search across systems, bases, player stations, and mining zones
- Right-click any object to copy a `/wp X Y Z` waypoint command
- In-map Help button with a quick-start tutorial and link to [GitHub Issues](https://github.com/SlimyTheMoon/DiscoNavmap/issues)
- Configurable display: connections, OORP systems, zones, wrecks, labels, player stations
- Works in both server and static (GitHub Pages) modes
