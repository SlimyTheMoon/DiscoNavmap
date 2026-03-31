# Navmap <img height="40" align="left" src="https://github.com/AudunVN/Navmap/blob/gh-pages/favicon.png">

A browser-based map viewer for the Freelancer mod [Discovery](https://discoverygc.com/). Displays accuratly the full universe map with system details, bases, zones, connections, infocards, and more.

## Credits & History

- Originally made by **Error** via [this repo](https://github.com/AudunVN/Navmap)
- Forked from **fifthbarrier**
- Sigma coloring rework and server-rules alignment by **Cherry Blossom**
- Refactored into **Go** with static site generation (published 25.03.2026)

A complete change and issue log from before this project was moved to GitHub may be found in [this DiscoveryGC forum thread](http://discoverygc.com/forums/showthread.php?tid=132266&pid=1700007#pid1700007).

## Requirements

- Go 1.25.5+
- A Discovery Freelancer installation (for data updates)

## Quick Start

### Run as HTTP server

```bash
go run main.go -data data/v5.3p2h4 -addr :8080
```

Then open `http://localhost:8080`.

| Flag | Default | Description |
|------|---------|-------------|
| `-data` | `data/v5.3p2h4` | Path to game data directory |
| `-addr` | `:8080` | Listen address |

### Build static site (for GitHub Pages)

```bash
go run cmd/static/main.go -data data/v5.3p2h4 -out dist
```

Generates a self-contained static site in `dist/` with all JSON data inlined/pre-built. The `docs/` folder contains the current deployed build.

## Updating Game Data

Import data from a Discovery Freelancer installation:

```bash
go run cmd/update/main.go -out data/v5.3p2h4
```

This will auto-discover your FL install via `LOCALAPPDATA`, copy and format the required game files, and lowercase all filenames. You'll be prompted to run **FL Path Generator** and **FLInfocardIE** first.

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `main.go` | HTTP server entry point |
| `cmd/static/` | Static site generator |
| `cmd/update/` | Game data importer |
| `pkg/gamedata/` | Core data parser — systems, bases, factions, connections, infocards, solar archetypes |
| `data/v5.3p2h4/` | Parsed Discovery game data (current version) |
| `templates/` | HTML template for the map UI |
| `scripts/` | Frontend JS (`app.js` — map rendering & UI, `panzoom.min.js`) |
| `styles/` | CSS |
| `images/` | Icons and map background images |
| `textures/` | Planet/star textures (`.txm` subdirs) |
| `docs/` | GitHub Pages deployment (pre-built static site) |
| `archive/` | Legacy Python-based version |

## API Endpoints (server mode)

| Endpoint | Description |
|----------|-------------|
| `GET /api/systems` | All systems (lightweight) |
| `GET /api/systems/all` | All system details (pre-gzipped) |
| `GET /api/system/{nick}` | Single system detail by nickname |
| `GET /api/connections` | Jump gate/hole connections |
| `GET /api/search` | Search items for autocomplete |
| `GET /api/infocard/{id}` | Infocard text by ID |
| `GET /api/faction/{nick}` | Faction info by nickname |

## Texture & Icon Data

Textures are extracted using [UTF Image Exporter](https://github.com/AudunVN/Navmap/tree/gh-pages/utils/UTFImageExporter), then bulk converted from txm to jpg using IrFanView, and afterwards recursively renamed counting up from `01.jpg` using Metamorphose2 to ensure that there's at least one texture available from each `.txm` file (the navmap expects a file named `01.jpg` inside each txm folder).

Icons are converted from TGA after being exported using ImageMagick or similar:
```bash
mogrify -flip -path png -format png *.tga
```

## Map Features

- Interactive universe map with pan & zoom
- System detail view with bases, planets, zones, wrecks, and jump connections
- Mineable zone info with commodity details
- Faction infocards
- Search across systems and bases
- Configurable display: connections, OORP systems, zones, wrecks, labels
- Works in both server and static (GitHub Pages) modes