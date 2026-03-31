from __future__ import annotations

import os
import re
from typing import Optional

from .types import (
    ARCHETYPE_IGNORE_LIST,
    BASE_NICKNAME_IGNORE_LIST,
    OORP_SYSTEMS,
    ZONE_FLAG_MAP,
    Base,
    Commodity,
    Connection,
    Faction,
    LootInfo,
    MapObject,
    MapZone,
    SearchResult,
    SolarArch,
    System,
    SystemDetail,
)


class GameData:
    def __init__(self, data_root: str):
        self.data_root = data_root

        self.systems: dict[str, System] = {}
        self.bases: dict[str, Base] = {}
        self.solar_archs: dict[str, SolarArch] = {}
        self.factions: dict[str, Faction] = {}
        self.commodities: dict[str, Commodity] = {}
        self.infocards: dict[str, str] = {}
        self.infocard_map: dict[str, str] = {}
        self.connections: list[Connection] = []
        self.search_items: list[SearchResult] = []

        self._system_names: dict[str, str] = {}
        self._system_classes: dict[str, str] = {}
        self._excluded_systems: dict[str, bool] = {}

        self.all_system_details: dict[str, dict] = {}

    @classmethod
    def load(cls, data_root: str) -> "GameData":
        gd = cls(data_root)
        gd._load_special_systems()
        gd._load_infocards()
        gd._load_infocard_map()
        gd._load_solar_arch()
        gd._load_multi_universe()
        gd._load_universe()
        gd._load_initial_world()
        gd._load_commodities()
        gd._load_connections()
        gd._build_search_index()
        return gd

    def resolve_name(self, ids_name: str) -> str:
        return self.infocards.get(ids_name, "")

    # ------------------------------------------------------------------
    # Loading methods
    # ------------------------------------------------------------------

    def _load_special_systems(self) -> None:
        path = os.path.join(self.data_root, "special_systems.txt")
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                parts = line.split(" = ", 1)
                if len(parts) != 2:
                    continue
                nick = parts[0].strip().lower()
                name = parts[1].strip()
                self._system_names[nick] = name
                if len(name) >= 2:
                    self._system_classes[nick] = name[:2].lower()

    def _load_infocards(self) -> None:
        path = os.path.join(self.data_root, "infocards.txt")
        with open(path, encoding="utf-8") as f:
            content = f.read().replace("\r\n", "\n")
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            id_str = lines[i].strip()
            if not id_str:
                i += 1
                continue
            i += 1
            if i >= len(lines):
                break
            text = lines[i].strip()
            # Handle unformatted infocards (has NAME/INFOCARD markers)
            if text in ("NAME", "INFOCARD"):
                i += 1
                if i < len(lines):
                    text = lines[i].strip()
                else:
                    text = ""
            if id_str and text:
                self.infocards[id_str] = text
            i += 1

    def _load_infocard_map(self) -> None:
        path = os.path.join(self.data_root, "infocardmap.ini")
        with open(path, encoding="utf-8") as f:
            content = _strip_comments(f.read())
        for m in re.finditer(r"(?i)[^;]Map\s*=\s*([^;\n\r]+)", content):
            parts = m.group(1).replace(" ", "").split(",")
            if len(parts) >= 2:
                self.infocard_map[parts[0].lower()] = parts[1]

    def _load_solar_arch(self) -> None:
        path = os.path.join(self.data_root, "solararch.ini")
        with open(path, encoding="utf-8") as f:
            content = _strip_comments(f.read())
        sections = _parse_sections(content, "Solar")
        for sec in sections:
            nick = _extract_value(sec, "nickname")
            if not nick:
                continue
            nick = nick.lower()
            sa = SolarArch(nickname=nick)
            t = _extract_value(sec, "type")
            if t:
                sa.type = t.lower()
            r = _extract_value(sec, "solar_radius")
            if r:
                sa.radius = r
            s = _extract_value(sec, "solar_shape")
            if s:
                sa.shape = s.lower()
            ml = _extract_value(sec, "material_library")
            if ml and "planet_" in nick:
                ml_lower = ml.lower().replace("\\", "/")
                idx = ml_lower.find("solar/planets/")
                if idx != -1:
                    rest = ml_lower[idx + len("solar/planets/"):]
                    slash_idx = rest.find("/")
                    if slash_idx != -1:
                        rest = rest[:slash_idx]
                    if rest.endswith(".txm"):
                        candidate = os.path.join("textures", "planets", rest, "01.jpg")
                        if os.path.isfile(candidate):
                            sa.texture_path = "textures/planets/" + rest + "/01.jpg"
            self.solar_archs[nick] = sa

    def _load_multi_universe(self) -> None:
        path = os.path.join(self.data_root, "universe", "multiuniverse.ini")
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as f:
            lines = f.read().replace("\r\n", "\n").split("\n")
        in_sector03 = False
        for line in lines:
            trimmed = line.strip()
            # Strip inline comments
            semi = trimmed.find(";")
            if semi >= 0:
                trimmed = trimmed[:semi].strip()
            if not trimmed:
                continue
            if trimmed.startswith("["):
                in_sector03 = False
                continue
            if trimmed.lower().startswith("mapping = sector03"):
                in_sector03 = True
                continue
            if trimmed.lower().startswith("mapping ="):
                in_sector03 = False
                continue
            if in_sector03 and trimmed.lower().startswith("system ="):
                val = trimmed[len("system ="):].strip()
                parts = val.split(",")
                if parts:
                    sys_nick = parts[0].strip().lower()
                    if sys_nick:
                        self._excluded_systems[sys_nick] = True

    def _load_universe(self) -> None:
        path = os.path.join(self.data_root, "universe", "universe.ini")
        with open(path, encoding="utf-8") as f:
            content = _strip_comments(f.read())

        # Parse [System] sections
        for sec in _parse_sections(content, "System"):
            nick = _extract_value(sec, "nickname").lower()
            if not nick or "sector" in nick:
                continue
            if self._excluded_systems.get(nick):
                continue
            sys = System(nickname=nick)
            ids_name = _extract_value(sec, "strid_name")
            if ids_name:
                sys.ids_name = ids_name
                sys.name = self.resolve_name(ids_name)
            pos_str = _extract_value(sec, "pos")
            if pos_str:
                parts = pos_str.replace(" ", "").split(",")
                if len(parts) >= 2:
                    try:
                        sys.pos = [float(parts[0]), float(parts[1])]
                    except ValueError:
                        pass
            scale_str = _extract_value(sec, "navmapscale")
            if scale_str:
                try:
                    sys.scale_factor = float(scale_str.strip())
                except ValueError:
                    pass
            sys.cls = self._system_classes.get(nick, "")
            if OORP_SYSTEMS.get(nick):
                sys.oorp = True
            if not sys.name and sys.ids_name:
                sys.name = self.resolve_name(sys.ids_name)
            self.systems[nick] = sys

        # Hardcoded position override
        if "li09" in self.systems:
            self.systems["li09"].pos = [7.0, 9.25]

        # Parse [Base] sections
        for sec in _parse_sections(content, "Base"):
            nick = _extract_value(sec, "nickname").lower()
            sys_nick = _extract_value(sec, "system").lower()
            if self._excluded_systems.get(sys_nick):
                continue
            ids_name = _extract_value(sec, "strid_name")
            if not nick or "proxy_base" in nick:
                continue
            if "miners" in nick:
                continue
            if BASE_NICKNAME_IGNORE_LIST.get(nick):
                continue
            base = Base(nickname=nick, system_nickname=sys_nick, ids_name=ids_name)
            if ids_name:
                base.name = self.resolve_name(ids_name)
            self.bases[nick] = base

    def _load_initial_world(self) -> None:
        path = os.path.join(self.data_root, "initialworld.ini")
        with open(path, encoding="utf-8") as f:
            content = _strip_comments(f.read())
        for sec in _parse_sections(content, "Group"):
            nick = _extract_value(sec, "nickname").strip().lower()
            ids_name = _extract_value(sec, "ids_name").strip()
            if not nick or not ids_name:
                continue
            name = self.resolve_name(ids_name)
            self.factions[nick] = Faction(nickname=nick, ids_name=ids_name, name=name)

    def _load_commodities(self) -> None:
        path = os.path.join(self.data_root, "select_equip.ini")
        with open(path, encoding="utf-8") as f:
            content = _strip_comments(f.read())
        for sec in _parse_sections(content, "Commodity"):
            nick = _extract_value(sec, "nickname").strip().lower()
            ids_name = _extract_value(sec, "ids_name").strip()
            if not nick or not ids_name:
                continue
            name = self.resolve_name(ids_name)
            self.commodities[nick] = Commodity(nickname=nick, ids_name=ids_name, name=name)

    def _load_connections(self) -> None:
        conn_map: dict[str, dict[str, bool]] = {}
        jg_conn_map: dict[str, dict[str, bool]] = {}

        self._parse_path_file(
            os.path.join(self.data_root, "universe", "systems_shortest_path.ini"), conn_map
        )
        self._parse_path_file(
            os.path.join(self.data_root, "universe", "shortest_legal_path.ini"), jg_conn_map
        )

        seen: set[str] = set()
        for frm, dests in conn_map.items():
            if self._excluded_systems.get(frm):
                continue
            for to in dests:
                if self._excluded_systems.get(to):
                    continue
                key = _conn_key(frm, to)
                if key in seen:
                    continue
                seen.add(key)
                conn = Connection(frm=frm, to=to)
                if frm not in conn_map.get(to, {}):
                    conn.one_way = True
                self.connections.append(conn)

        # Mark JG connections
        for frm, dests in jg_conn_map.items():
            if self._excluded_systems.get(frm):
                continue
            for to in dests:
                if self._excluded_systems.get(to):
                    continue
                key = _conn_key(frm, to)
                if key not in seen:
                    seen.add(key)
                    self.connections.append(Connection(frm=frm, to=to, jg_only=True, has_jg=True))
                else:
                    for c in self.connections:
                        if _conn_key(c.frm, c.to) == key:
                            c.has_jg = True
                            break

    def _parse_path_file(self, path: str, conn_map: dict[str, dict[str, bool]]) -> None:
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "Path =" not in line:
                    continue
                idx = line.index("Path =")
                path_str = line[idx + 6:].strip()
                parts = path_str.replace(" ", "").split(",")
                if len(parts) < 4:
                    continue
                frm = parts[0].strip().lower()
                to = parts[3].strip().lower()
                if frm not in conn_map:
                    conn_map[frm] = {}
                conn_map[frm][to] = True

    def _build_search_index(self) -> None:
        for nick, sys in self.systems.items():
            if "sector" in nick:
                continue
            name = sys.name
            if not name and sys.ids_name:
                name = self.resolve_name(sys.ids_name)
            if not name:
                continue
            self.search_items.append(SearchResult(name=name, system_nickname=nick, type="system"))

        for base in self.bases.values():
            if not base.name:
                continue
            self.search_items.append(SearchResult(name=base.name, system_nickname=base.system_nickname, type="base"))

        extras = {
            "Omicron Major": "st03",
            "Livadia Shipyard": "ew06",
        }
        for name, sys_nick in extras.items():
            self.search_items.append(SearchResult(name=name, system_nickname=sys_nick, type="base"))

    # ------------------------------------------------------------------
    # Pre-computation
    # ------------------------------------------------------------------

    def precompute_all_details(self) -> None:
        self.all_system_details = {}
        for nick in self.systems:
            if "sector" in nick:
                continue
            if self._excluded_systems.get(nick):
                continue
            detail = self.get_system_detail(nick)
            if detail:
                self.all_system_details[nick] = detail.to_dict()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[SearchResult]:
        query = query.lower()
        return [item for item in self.search_items if query in item.name.lower()]

    # ------------------------------------------------------------------
    # System detail
    # ------------------------------------------------------------------

    def get_system_detail(self, system_nickname: str) -> Optional[SystemDetail]:
        system_nickname = system_nickname.lower()
        sys = self.systems.get(system_nickname)
        if not sys:
            return None

        # Determine system file path
        if system_nickname == "fp7_system":
            sys_file_path = os.path.join(self.data_root, "universe", "systems", "fp7", "fp7_system.ini")
        else:
            sys_file_path = os.path.join(self.data_root, "universe", "systems", system_nickname, system_nickname + ".ini")

        if not os.path.isfile(sys_file_path):
            return None

        with open(sys_file_path, encoding="utf-8") as f:
            content = _strip_comments(f.read())

        scale_factor = sys.scale_factor
        detail = SystemDetail(system=sys)

        # Parse ambient color
        for sec in _parse_sections(content, "Ambient"):
            color_str = _extract_value(sec, "color")
            if color_str:
                parts = color_str.replace(" ", "").split(",")
                if len(parts) >= 3:
                    r = int(float(parts[0]) * 0.3)
                    g = int(float(parts[1]) * 0.3)
                    b = int(float(parts[2]) * 0.3)
                    detail.ambient_color = f"rgb({r},{g},{b})"

        # Parse lootable zones from asteroid files
        lootable_zones, asteroid_zones = self._parse_asteroid_files(content, system_nickname)

        # Parse zones
        for sec in _parse_sections(content, "Zone"):
            zone = self._parse_zone(sec, scale_factor, lootable_zones, asteroid_zones)
            if zone:
                detail.zones.append(zone)

        # Parse objects
        for sec in _parse_sections(content, "Object"):
            obj = self._parse_object(sec, scale_factor)
            if obj:
                detail.objects.append(obj)

        return detail

    def _parse_asteroid_files(
        self, sys_content: str, system_nickname: str
    ) -> tuple[dict[str, LootInfo], dict[str, bool]]:
        lootable_zones: dict[str, LootInfo] = {}
        asteroid_zones: dict[str, bool] = {}

        for m in re.finditer(r"(?i)\[Asteroids\]\s*\r?\n([^\[]*?)(?:\n\[|\Z)", sys_content):
            block = m.group(1)
            lines = block.split("\n")
            file_uri = ""
            zone_nick = ""
            for line in lines:
                line = line.strip()
                if line.lower().startswith("file = "):
                    file_uri = line[7:].strip()
                if line.lower().startswith("zone = "):
                    zone_nick = line[7:].strip().lower()
            if not file_uri or not zone_nick:
                continue
            asteroid_zones[zone_nick] = True
            file_path = os.path.join(self.data_root, file_uri.lower().replace("\\", os.sep))
            if not os.path.isfile(file_path):
                continue
            with open(file_path, encoding="utf-8") as f:
                ast_content = _strip_comments(f.read())
            for lz_sec in _parse_sections(ast_content, "LootableZone"):
                lz_zone = _extract_value(lz_sec, "zone").strip().lower()
                if not lz_zone:
                    lz_zone = zone_nick
                dyn_comm = _extract_value(lz_sec, "dynamic_loot_commodity")
                dyn_count = _extract_value(lz_sec, "dynamic_loot_count")
                dyn_diff = _extract_value(lz_sec, "dynamic_loot_difficulty")
                ast_comm = _extract_value(lz_sec, "asteroid_loot_commodity")
                ast_count = _extract_value(lz_sec, "asteroid_loot_count")
                ast_diff = _extract_value(lz_sec, "asteroid_loot_difficulty")

                commodity = ""
                count = ""
                difficulty = ""
                if dyn_comm:
                    commodity = dyn_comm
                    count = dyn_count
                    difficulty = dyn_diff
                elif ast_comm:
                    commodity = ast_comm
                    count = ast_count
                    difficulty = ast_diff
                if commodity:
                    comm_name = commodity
                    c = self.commodities.get(commodity.lower())
                    if c and c.name:
                        comm_name = c.name
                    lootable_zones[lz_zone] = LootInfo(
                        commodity=commodity, commodity_name=comm_name,
                        count=count, difficulty=difficulty,
                    )
        return lootable_zones, asteroid_zones

    def _parse_zone(
        self,
        sec: str,
        scale_factor: float,
        lootable_zones: dict[str, LootInfo],
        asteroid_zones: dict[str, bool],
    ) -> Optional[MapZone]:
        nick = _extract_value(sec, "nickname").strip().lower()
        if not nick:
            return None
        pos_str = _extract_value(sec, "pos")
        if not pos_str:
            return None
        # Skip zones with flag 66170 unless they have an asteroid file
        if "66170" in sec and not asteroid_zones.get(nick):
            return None

        zone = MapZone(nickname=nick)
        ids_name = _extract_value(sec, "ids_name")
        if ids_name:
            zone.ids_name = ids_name
            zone.name = self.resolve_name(ids_name)
        ids_info = _extract_value(sec, "ids_info")
        if ids_info:
            zone.ids_info = ids_info

        # Parse position
        pos_parts = pos_str.replace(" ", "").split(",")
        if len(pos_parts) >= 3:
            try:
                zone.pos = [float(pos_parts[0]), float(pos_parts[1]), float(pos_parts[2])]
            except ValueError:
                pass

        # Parse size
        size_str = _extract_value(sec, "size")
        if size_str:
            size_parts = size_str.replace(" ", "").split(",")
            try:
                if len(size_parts) >= 3:
                    zone.size = [float(size_parts[0]), float(size_parts[1]), float(size_parts[2])]
                elif len(size_parts) == 2:
                    v0, v1 = float(size_parts[0]), float(size_parts[1])
                    zone.size = [v0, v1, v1]
                elif len(size_parts) == 1:
                    v = float(size_parts[0])
                    zone.size = [v, v, v]
            except ValueError:
                pass

        # Parse rotation
        rot_str = _extract_value(sec, "rotate")
        if rot_str:
            rot_parts = rot_str.replace(" ", "").split(",")
            if len(rot_parts) >= 3:
                try:
                    zone.rotation = [float(rot_parts[0]), float(rot_parts[1]), float(rot_parts[2])]
                except ValueError:
                    pass

        # Determine shape
        sec_lower = sec.lower()
        if "ellipsoid" in sec_lower:
            zone.shape = "ellipsoid"
        elif "sphere" in sec_lower:
            zone.shape = "sphere"
        elif "cylinder" in sec_lower:
            zone.shape = "cylinder"
        elif "box" in sec_lower:
            zone.shape = "box"

        # Parse fog color
        fog_str = _extract_value(sec, "property_fog_color")
        if fog_str:
            parts = fog_str.replace(" ", "").split(",")
            if len(parts) >= 3:
                zone.fog_color = f"rgba({parts[0]},{parts[1]},{parts[2]},0.45)"

        # Parse zone flags
        flag_str = _extract_value(sec, "property_flags")
        if flag_str:
            try:
                zone.zone_flags = int(flag_str.strip())
                zone.zone_class = ZONE_FLAG_MAP.get(zone.zone_flags, "")
            except ValueError:
                pass

        # Check for lootable zone data
        loot = lootable_zones.get(nick)
        if loot:
            zone.mineable = True
            zone.loot_info = loot

        if nick == "zone_st08_alexandria_interior":
            return None

        return zone

    def _parse_object(self, sec: str, scale_factor: float) -> Optional[MapObject]:
        nick = _extract_value(sec, "nickname").strip().lower()
        if not nick:
            return None
        archetype = _extract_value(sec, "archetype").strip().lower()
        if ARCHETYPE_IGNORE_LIST.get(archetype):
            return None
        if BASE_NICKNAME_IGNORE_LIST.get(nick):
            return None
        base_val = _extract_value(sec, "base").strip().lower()
        if base_val == "no_hidden_bases":
            return None

        obj = MapObject(nickname=nick, archetype=archetype)

        ids_name = _extract_value(sec, "ids_name")
        if ids_name:
            obj.ids_name = ids_name
            obj.name = self.resolve_name(ids_name)
        ids_info = _extract_value(sec, "ids_info")
        if ids_info:
            obj.ids_info = ids_info

        # Parse position
        pos_str = _extract_value(sec, "pos")
        if pos_str:
            parts = pos_str.replace(" ", "").split(",")
            if len(parts) >= 3:
                try:
                    obj.pos = [float(parts[0]), float(parts[1]), float(parts[2])]
                except ValueError:
                    pass

        # Parse rotation
        rot_str = _extract_value(sec, "rotate")
        if rot_str:
            parts = rot_str.replace(" ", "").split(",")
            if len(parts) >= 3:
                try:
                    obj.rotation = [float(parts[0]), float(parts[1]), float(parts[2])]
                except ValueError:
                    pass

        # Parse reputation
        m = re.search(r"(?i)reputation\s*=\s*([^;\r\n]+)", sec)
        if m:
            obj.reputation = m.group(1).strip().lower()

        # Determine classes
        obj.classes = self._get_object_classes(sec, nick)

        # Solar arch lookups
        sa = self.solar_archs.get(archetype)
        if sa:
            if sa.texture_path:
                obj.texture_path = sa.texture_path
            if sa.radius:
                try:
                    obj.radius = float(sa.radius)
                except ValueError:
                    pass

        # Atmosphere range
        atm = _extract_value(sec, "atmosphere_range")
        if atm:
            try:
                obj.atmosphere_range = float(atm.strip())
            except ValueError:
                pass

        # Burn color
        bc = _extract_value(sec, "burn_color")
        if bc:
            parts = bc.replace(" ", "").split(",")
            if len(parts) >= 3:
                obj.burn_color = f"rgb({parts[0]},{parts[1]},{parts[2]})"

        # Jump destination
        m = re.search(r"(?i)[^;\r\n]*goto\s*=\s*([^;\r\n]*)", sec)
        if m:
            goto_parts = m.group(1).replace(" ", "").split(",")
            if goto_parts:
                obj.jump_dest = goto_parts[0].strip().lower()

        # Determine name for unnamed objects
        if not obj.name:
            obj.name = self._find_object_name(nick, obj.classes)

        return obj

    def _get_object_classes(self, sec: str, nick: str) -> list[str]:
        classes = ["object"]
        sec_lower = sec.lower()
        nick_lower = nick.lower()

        has_atmosphere = "atmosphere_range =" in sec_lower
        has_star = "star =" in sec_lower
        has_base = "base =" in sec_lower or "base=" in sec_lower
        has_dock = "dock_with =" in sec_lower or "dock_with=" in sec_lower
        has_loadout = "loadout =" in sec_lower or "loadout=" in sec_lower
        has_ids_name = "ids_name" in sec_lower
        has_rep = "reputation =" in sec_lower or "reputation=" in sec_lower

        if has_atmosphere and not has_star:
            classes.append("planet")
        elif has_base or has_dock:
            classes.append("base")

        if has_base:
            classes.append("dockable")

        if ("trade_lane" in nick_lower or "dsy_ga_lane" in sec_lower
                or "trade_lane_ring" in sec_lower or "next_ring =" in sec_lower):
            classes.append("tradelane")

        if has_loadout and ("wplatform" in nick_lower or "261164" in sec_lower):
            classes.append("wPlatform")

        if has_loadout and not has_rep and "archetype = jumphole" not in sec_lower:
            if has_ids_name:
                classes.append("wreck")

        if "proxy_base" in nick_lower:
            classes.append("proxyBase")

        if "_to_" in nick_lower or "nomad_gate" in nick_lower:
            classes.append("jump")
            if ("_hole" in nick_lower or "_jumphole" in nick_lower
                    or "archetype = jumphole" in sec_lower):
                classes.append("hole")
            else:
                classes.append("gate")
            goto_match = re.search(r"(?i)[^;\r\n]*goto\s*=\s*([^;\r\n]*)", sec)
            if not goto_match or "505262" in sec or "st03_to_fp7_jumphole_recv" in nick_lower:
                classes.append("unusableJump")

        if has_star and has_atmosphere:
            classes.append("star")

        if "_dock_ring" in sec_lower:
            classes.append("dockingRing")

        if "docking_fixture" in sec_lower:
            classes.append("mooringFixture")
            if "docking_fixture_horizontal_navmap" in sec_lower:
                classes.append("dockable")

        if len(classes) == 1:
            classes.append("unclassified")

        return classes

    def _find_object_name(self, nick: str, classes: list[str]) -> str:
        class_set = set(classes)
        if "jump" in class_set:
            if "hole" in class_set:
                return "Jump Hole"
            return "Jump Gate"
        if "mooringFixture" in class_set:
            if "docking_fixture" in nick.lower():
                return "Mooring Fixture"
            return nick + " (int)"
        return nick + " (int)"


# ------------------------------------------------------------------
# Infocard parsing
# ------------------------------------------------------------------

def parse_infocard(text: str) -> str:
    if "<text>" not in text.lower():
        return text
    matches = re.findall(
        r"(?i)(<(?:text|TEXT)>.+?</(?:text|TEXT)>|<(?:para|PARA)\s*/>)", text
    )
    parts: list[str] = []
    for m in matches:
        m_lower = m.lower()
        if "<para" in m_lower:
            parts.append("<br class='infocardBreak'>")
        else:
            inner = re.sub(r"(?i)<text>", "", m)
            inner = re.sub(r"(?i)</text>", "", inner)
            parts.append("<span class='infocardText'>" + inner + "</span>")
    return "".join(parts)


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _strip_comments(content: str) -> str:
    return re.sub(r"[\n\r]+;+.*", "", content)


def _parse_sections(content: str, section_name: str) -> list[str]:
    target = "[" + section_name.lower() + "]"
    lines = content.split("\n")
    sections: list[str] = []
    cur: list[str] = []
    in_target = False
    for line in lines:
        stripped = line.strip()
        if stripped and stripped[0] == "[":
            if in_target and cur:
                sections.append("\n".join(cur))
            if stripped.lower() == target:
                in_target = True
                cur = [line]
            else:
                in_target = False
                cur = []
            continue
        if in_target:
            cur.append(line)
    if in_target and cur:
        sections.append("\n".join(cur))
    return sections


def _extract_value(section: str, key: str) -> str:
    pattern = rf"(?im)^\s*{re.escape(key)}\s*=\s*([^;\r\n]*)"
    m = re.search(pattern, section)
    if m:
        return m.group(1).strip()
    return ""


def _conn_key(a: str, b: str) -> str:
    if a < b:
        return a + "|" + b
    return b + "|" + a
