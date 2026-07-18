from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class System:
    nickname: str
    name: str = ""
    cls: str = ""          # li, br, ku, rh, ga, hi, bw, st, ew, iw
    ids_name: str = ""
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    scale_factor: float = 1.0
    oorp: bool = False

    def to_dict(self) -> dict:
        return {
            "nickname": self.nickname,
            "name": self.name,
            "class": self.cls,
            "idsName": self.ids_name,
            "pos": self.pos,
            "scaleFactor": self.scale_factor,
            "oorp": self.oorp,
        }


@dataclass
class Base:
    nickname: str
    name: str = ""
    system_nickname: str = ""
    ids_name: str = ""
    ids_info: str = ""

    def to_dict(self) -> dict:
        return {
            "nickname": self.nickname,
            "name": self.name,
            "systemNickname": self.system_nickname,
            "idsName": self.ids_name,
        }


@dataclass
class SolarArch:
    nickname: str
    type: str = ""
    radius: str = ""
    shape: str = ""
    texture_path: str = ""


@dataclass
class Connection:
    frm: str
    to: str
    jg_only: bool = False
    has_jg: bool = False
    one_way: bool = False

    def to_dict(self) -> dict:
        return {
            "from": self.frm,
            "to": self.to,
            "jgOnly": self.jg_only,
            "hasJG": self.has_jg,
            "oneWay": self.one_way,
        }


@dataclass
class LootInfo:
    commodity: str
    commodity_name: str = ""
    count: str = ""
    difficulty: str = ""

    def to_dict(self) -> dict:
        d = {
            "commodity": self.commodity,
            "commodityName": self.commodity_name,
            "count": self.count,
            "difficulty": self.difficulty,
        }
        return d


@dataclass
class MapZone:
    nickname: str
    name: str = ""
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    size: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    shape: str = ""
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    ids_name: str = ""
    ids_info: str = ""
    fog_color: str = ""
    zone_flags: int = 0
    zone_class: str = ""
    mineable: bool = False
    loot_info: Optional[LootInfo] = None

    def to_dict(self) -> dict:
        d: dict = {
            "nickname": self.nickname,
            "pos": self.pos,
            "size": self.size,
            "shape": self.shape,
            "zoneFlags": self.zone_flags,
            "zoneClass": self.zone_class,
            "mineable": self.mineable,
        }
        if self.name:
            d["name"] = self.name
        if self.rotation != [0.0, 0.0, 0.0]:
            d["rotation"] = self.rotation
        if self.ids_name:
            d["idsName"] = self.ids_name
        if self.ids_info:
            d["idsInfo"] = self.ids_info
        if self.fog_color:
            d["fogColor"] = self.fog_color
        if self.loot_info:
            d["lootInfo"] = self.loot_info.to_dict()
        return d


@dataclass
class MapObject:
    nickname: str
    name: str = ""
    classes: list[str] = field(default_factory=lambda: ["object"])
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    ids_name: str = ""
    ids_info: str = ""
    archetype: str = ""
    jump_dest: str = ""
    reputation: str = ""
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    texture_path: str = ""
    radius: float = 0.0
    atmosphere_range: float = 0.0
    burn_color: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "nickname": self.nickname,
            "name": self.name,
            "classes": self.classes,
            "pos": self.pos,
        }
        if self.ids_name:
            d["idsName"] = self.ids_name
        if self.ids_info:
            d["idsInfo"] = self.ids_info
        if self.archetype:
            d["archetype"] = self.archetype
        if self.jump_dest:
            d["jumpDest"] = self.jump_dest
        if self.reputation:
            d["reputation"] = self.reputation
        if self.rotation != [0.0, 0.0, 0.0]:
            d["rotation"] = self.rotation
        if self.texture_path:
            d["texturePath"] = self.texture_path
        if self.radius > 0:
            d["radius"] = self.radius
        if self.atmosphere_range > 0:
            d["atmosphereRange"] = self.atmosphere_range
        if self.burn_color:
            d["burnColor"] = self.burn_color
        return d


@dataclass
class SystemDetail:
    system: System
    ambient_color: str = ""
    objects: list[MapObject] = field(default_factory=list)
    zones: list[MapZone] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "system": self.system.to_dict(),
            "ambientColor": self.ambient_color,
            "objects": [o.to_dict() for o in self.objects],
            "zones": [z.to_dict() for z in self.zones],
        }
        return d


@dataclass
class Faction:
    nickname: str
    ids_name: str = ""
    name: str = ""


@dataclass
class Commodity:
    nickname: str
    ids_name: str = ""
    name: str = ""


@dataclass
class SearchResult:
    name: str
    system_nickname: str
    type: str  # "system" or "base"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "systemNickname": self.system_nickname,
            "type": self.type,
        }


ZONE_FLAG_MAP: dict[int, str] = {
    0:       "zoneHidden",
    64:      "zoneRockAsteroids",
    65:      "zoneAlphaBigDust",
    66:      "zoneRock",
    74:      "zoneLeedsUraniumAsteroids",
    82:      "zoneDublinGoldField",
    128:     "zoneJerseyDebris",
    129:     "zoneDetroitDebrisNormal",
    130:     "zoneDetroitDebrisHigh",
    132:     "zoneDetroitDebrisLow",
    256:     "zoneIceAsteroidsSmall",
    257:     "zoneIceAsteroidsTau37",
    258:     "zoneIceAsteroids1",
    512:     "zoneLavaRocks",
    513:     "zoneVonRoheBeltLavaRocks",
    514:     "zoneDresdenLavaRocks",
    1024:    "zoneGreenAsteroids",
    1026:    "zoneZetaGreenAsteroids",
    2049:    "zoneIceAsteroids2",
    4096:    "zoneMinefield1",
    4128:    "zoneMinefield2",
    8192:    "zoneAsteroidField",
    8200:    "zoneAsteroids",
    16400:   "zoneIceNebula",
    32768:   "zoneDresdenFog",
    32776:   "zoneLeedsSmog",
    32833:   "zoneChugokuCloud",
    62768:   "zoneNebulaWithFogColour",
    65536:   "zoneExclusion1",
    131072:  "zoneExclusion2",
    196608:  "zoneExclusion3",
}

OORP_SYSTEMS: dict[str, bool] = {
    "br09": True, "br10": True, "bw11": True, "bw14": True, "ca01": True,
    "ev01": True, "ev02": True, "ev03": True, "ew05": True, "ew14": True,
    "ew19": True, "ew20": True, "ew21": True, "ew37": True, "ew63": True,
    "ew85": True, "fp7_system": True, "hi19": True, "hlp1": True, "hlp2": True,
    "iw09": True, "ku17": True, "li06": True, "li07": True, "li08": True,
    "limbo": True, "st02c": True, "st03b": True, "unch01": True, "unch02": True,
    "unch03": True, "unch04": True, "unch04b": True, "unch05": True, "unch06": True,
    "unch07": True, "unch08": True, "unch09": True, "unch10": True, "vr01": True,
}

ARCHETYPE_IGNORE_LIST: dict[str, bool] = {
    "dsy_suprise_secret": True, "suprise_ku_dragon_secret": True,
    "suprise_dsy_gmg_vhf_secret": True, "suprise_dsy_or_hf_secret": True,
    "suprise_bw_elite2_secret": True, "suprise_dsy_bayonet_secret": True,
    "suprise_b_battleship_secret": True, "invisible_base": True,
    "blhazard": True, "li17_suprise_bw_elite2_01": True,
    "suprise_hf_elite2_concealed": True, "suprise_bw_elite2": True,
    "suprise_co_elite2": True,
}

BASE_NICKNAME_IGNORE_LIST: dict[str, bool] = {
    "li04_04_extra_dock": True, "iw01_01_01": True, "iw01_01_02": True,
    "ew06_surprise_marker": True, "st01_azurite_tower_01": True,
    "br05_05_1a": True, "rh02_05_1": True, "li09_08_moor01": True,
    "li09_07_docking_fixture": True, "ga05_02_moor03": True,
    "rh03_docking_fixture_1": True, "li17_suprise_bw_elite2_01": True,
    "iw08_suprise_crypt": True, "st08_03_orbital_terminal_extra": True,
}

ARCHETYPE_SHOW_LIST: dict[str, bool] = {
    "ithaca_station": True, "junction_wreck": True,
    "space_beamx_messina": True, "docking_fixture_horizontal_navmap": True,
}
