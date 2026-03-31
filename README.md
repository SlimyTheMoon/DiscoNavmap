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

| Endpoint | Description |
|----------|-------------|
| `GET /api/systems` | All systems (lightweight) |
| `GET /api/systems/all` | All system details (pre-gzipped) |
| `GET /api/system/{nick}` | Single system detail by nickname |
| `GET /api/connections` | Jump gate/hole connections |
| `GET /api/search?q=...` | Search items for autocomplete |
| `GET /api/infocard/{id}` | Infocard text by ID |
| `GET /api/faction/{nick}` | Faction info by nickname |
| `GET /api/pobs` | Player Owned Stations (proxied from darkstat) |
| `GET /data/systems-all.json` | Pre-computed system details (used by frontend) |
| `GET /data/infocards.json` | Parsed infocards with HTML (used by frontend) |
| `GET /data/factions.json` | Faction name lookup (used by frontend) |

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
- POB infocards fetched from darkstat API (`POST /api/infocards`)

## Texture & Icon Data

Textures are extracted using [UTF Image Exporter](https://github.com/AudunVN/Navmap/tree/gh-pages/utils/UTFImageExporter), then bulk converted from txm to jpg using IrFanView, and afterwards recursively renamed counting up from `01.jpg` using Metamorphose2 to ensure that there's at least one texture available from each `.txm` file (the navmap expects a file named `01.jpg` inside each txm folder).

Icons are converted from TGA after being exported using ImageMagick or similar:
```bash
mogrify -flip -path png -format png *.tga
```

## Map Features

- Interactive universe map with pan & zoom
- System detail view with bases, planets, zones, wrecks, and jump connections
- Mineable zone labels showing commodity names (e.g. Iridium Ore, Gold Ore)
- Nomad gate connections with distinct purple styling
- Unstable connections with red styling
- Player Owned Stations (POBs) with live infocards from [darkstat](https://darkstat.dd84ai.com)
- Faction infocards
- Search across systems and bases
- Configurable display: connections, OORP systems, zones, wrecks, labels
- Works in both server and static (GitHub Pages) modes
