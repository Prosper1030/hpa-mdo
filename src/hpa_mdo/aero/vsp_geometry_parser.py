"""Parse OpenVSP .vsp3 XML files into a simple geometry model."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Iterable
import xml.etree.ElementTree as ET


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", maxsplit=1)[-1]
    return tag


@dataclass(frozen=True)
class VSPSection:
    x_le: float
    y_le: float
    z_le: float
    chord: float
    twist: float
    airfoil: str


@dataclass(frozen=True)
class VSPSurface:
    name: str
    surface_type: str
    origin: tuple[float, float, float]
    rotation: tuple[float, float, float]
    symmetry: str
    sections: list[VSPSection]


@dataclass(frozen=True)
class VSPGeometryModel:
    surfaces: list[VSPSurface]

    def get_wing(self) -> VSPSurface | None:
        for surface in self.surfaces:
            if surface.surface_type == "wing":
                return surface
        return None

    def get_h_stab(self) -> VSPSurface | None:
        for surface in self.surfaces:
            if surface.surface_type == "h_stab":
                return surface
        return None

    def get_v_fin(self) -> VSPSurface | None:
        for surface in self.surfaces:
            if surface.surface_type == "v_fin":
                return surface
        return None


class VSPGeometryParser:
    """Parse OpenVSP .vsp3 XML files to extract all surface geometry."""

    def __init__(self, vsp3_path: Path):
        self.vsp3_path = Path(vsp3_path).expanduser().resolve()

    def parse(self) -> VSPGeometryModel:
        if not self.vsp3_path.exists():
            raise FileNotFoundError(f"VSP3 file not found: {self.vsp3_path}")

        root = ET.parse(self.vsp3_path).getroot()
        surfaces: list[VSPSurface] = []
        seen_names: set[str] = set()
        for geom_node in self._iter_geom_nodes(root):
            surface = self._parse_surface(geom_node)
            if surface is None:
                continue
            dedupe_key = _norm_key(surface.name)
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            surfaces.append(surface)

        if not surfaces:
            raise ValueError(f"No wing-like surfaces found in VSP3: {self.vsp3_path}")
        return VSPGeometryModel(surfaces=surfaces)

    def _iter_geom_nodes(self, root: ET.Element) -> Iterable[ET.Element]:
        for node in root.iter():
            tag = _clean_tag(node.tag).lower()
            if "geom" not in tag:
                continue
            if self._find_name(node) is None:
                continue
            if not self._find_xsec_nodes(node):
                continue
            yield node

    def _parse_surface(self, geom_node: ET.Element) -> VSPSurface | None:
        name = self._find_name(geom_node)
        if name is None:
            return None

        x_loc = self._find_float(
            geom_node,
            ("xlocation", "xloc", "x_location"),
            default=0.0,
        )
        y_loc = self._find_float(
            geom_node,
            ("ylocation", "yloc", "y_location"),
            default=0.0,
        )
        z_loc = self._find_float(
            geom_node,
            ("zlocation", "zloc", "z_location"),
            default=0.0,
        )
        x_rot = self._find_float(
            geom_node,
            ("xrotation", "xrot", "x_rotation"),
            default=0.0,
        )
        y_rot = self._find_float(
            geom_node,
            ("yrotation", "yrot", "y_rotation"),
            default=0.0,
        )
        z_rot = self._find_float(
            geom_node,
            ("zrotation", "zrot", "z_rotation"),
            default=0.0,
        )
        symmetry_flag = int(
            round(
                self._find_float(
                    geom_node,
                    ("symplanarflag", "sym_planar_flag"),
                    default=0.0,
                )
            )
        )
        symmetry = "xz" if symmetry_flag == 2 else "none"
        origin = (x_loc, y_loc, z_loc)
        rotation = (x_rot, y_rot, z_rot)
        sections = self._parse_sections(geom_node, origin=origin, rotation=rotation)
        if not sections:
            return None
        return VSPSurface(
            name=name,
            surface_type=self._infer_surface_type(name=name, rotation=rotation),
            origin=origin,
            rotation=rotation,
            symmetry=symmetry,
            sections=sections,
        )

    def _parse_sections(
        self,
        geom_node: ET.Element,
        *,
        origin: tuple[float, float, float],
        rotation: tuple[float, float, float],
    ) -> list[VSPSection]:
        xsecs = self._find_xsec_nodes(geom_node)
        if not xsecs:
            return []

        sections: list[VSPSection] = []
        prev_local = (0.0, 0.0, 0.0)
        prev_chord = 0.0
        for idx, xsec in enumerate(xsecs):
            x_le = self._find_float(xsec, ("xle", "x_le", "xlocation", "xloc"), default=None)
            y_le = self._find_float(xsec, ("yle", "y_le", "ylocation", "yloc"), default=None)
            z_le = self._find_float(xsec, ("zle", "z_le", "zlocation", "zloc"), default=None)
            chord = self._find_float(
                xsec,
                ("chord", "tipchord", "rootchord", "tip_chord", "root_chord"),
                default=prev_chord,
            )
            twist = self._find_float(
                xsec,
                ("twist", "twistdeg", "twist_deg", "incidence", "ainc"),
                default=0.0,
            )
            if x_le is None or y_le is None or z_le is None:
                span = self._find_float(
                    xsec,
                    ("span", "sectspan", "spanlen", "span_len"),
                    default=0.0,
                )
                sweep_deg = self._find_float(
                    xsec,
                    ("sweep", "sweepdeg", "sweep_deg"),
                    default=0.0,
                )
                dihedral_deg = self._find_float(
                    xsec,
                    ("dihedral", "dihedraldeg", "dihedral_deg"),
                    default=0.0,
                )
                if idx == 0:
                    local = (
                        0.0 if x_le is None else float(x_le),
                        0.0 if y_le is None else float(y_le),
                        0.0 if z_le is None else float(z_le),
                    )
                else:
                    dx = float(span) * math.tan(math.radians(float(sweep_deg)))
                    dy = float(span)
                    dz = float(span) * math.tan(math.radians(float(dihedral_deg)))
                    local = (
                        prev_local[0] + dx if x_le is None else float(x_le),
                        prev_local[1] + dy if y_le is None else float(y_le),
                        prev_local[2] + dz if z_le is None else float(z_le),
                    )
            else:
                local = (float(x_le), float(y_le), float(z_le))

            rotated = self._rotate_point(local, rotation)
            global_xyz = (
                origin[0] + rotated[0],
                origin[1] + rotated[1],
                origin[2] + rotated[2],
            )
            airfoil = self._find_airfoil_name(xsec)
            sections.append(
                VSPSection(
                    x_le=float(global_xyz[0]),
                    y_le=float(global_xyz[1]),
                    z_le=float(global_xyz[2]),
                    chord=float(chord),
                    twist=float(twist),
                    airfoil=airfoil,
                )
            )
            prev_local = local
            prev_chord = float(chord)
        return sections

    def _find_xsec_nodes(self, node: ET.Element) -> list[ET.Element]:
        xsecs = [child for child in node.findall(".//XSec")]
        if xsecs:
            return xsecs
        fallback: list[ET.Element] = []
        for child in node.iter():
            if _clean_tag(child.tag).lower().endswith("xsec"):
                fallback.append(child)
        return fallback

    def _find_name(self, node: ET.Element) -> str | None:
        candidates = (
            node.findtext("./Name"),
            node.findtext("./ParmContainer/Name"),
            node.findtext(".//ParmContainer/Name"),
            node.findtext(".//Name"),
        )
        for candidate in candidates:
            if candidate is not None and candidate.strip():
                return candidate.strip()
        return None

    def _find_float(
        self,
        node: ET.Element,
        names: tuple[str, ...],
        *,
        default: float | None,
    ) -> float | None:
        key_set = {_norm_key(name) for name in names}
        for element in node.iter():
            tag_key = _norm_key(_clean_tag(element.tag))
            if tag_key in key_set:
                value = _parse_float(element.text)
                if value is not None:
                    return value

        for element in node.iter():
            name_text = element.findtext("Name")
            if name_text is None:
                continue
            if _norm_key(name_text) not in key_set:
                continue
            for value_tag in ("Value", "Val"):
                value = _parse_float(element.findtext(value_tag))
                if value is not None:
                    return value
            value = _parse_float(element.text)
            if value is not None:
                return value
        return default

    def _find_airfoil_name(self, node: ET.Element) -> str:
        for candidate_name in (
            "Airfoil",
            "AirfoilName",
            "airfoil",
            "airfoil_name",
            "NACA",
            "naca",
        ):
            text = node.findtext(f".//{candidate_name}")
            if text is None:
                continue
            text = text.strip()
            if text:
                return text

        for element in node.iter():
            text = (element.text or "").strip()
            if not text:
                continue
            match = re.search(r"NACA\s*([0-9]{4,5})", text, flags=re.IGNORECASE)
            if match is not None:
                return f"NACA {match.group(1)}"
        return "NACA 0012"

    def _infer_surface_type(
        self,
        *,
        name: str,
        rotation: tuple[float, float, float],
    ) -> str:
        label = name.lower()
        if "fin" in label or "rudder" in label or "vertical" in label:
            return "v_fin"
        if abs(float(rotation[0])) >= 60.0:
            return "v_fin"
        if "elevator" in label or "stab" in label or "tail" in label:
            return "h_stab"
        return "wing"

    @staticmethod
    def _rotate_point(
        point: tuple[float, float, float],
        rotation_deg: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        x, y, z = point
        rx, ry, rz = (math.radians(float(value)) for value in rotation_deg)

        y, z = (
            y * math.cos(rx) - z * math.sin(rx),
            y * math.sin(rx) + z * math.cos(rx),
        )
        x, z = (
            x * math.cos(ry) + z * math.sin(ry),
            -x * math.sin(ry) + z * math.cos(ry),
        )
        x, y = (
            x * math.cos(rz) - y * math.sin(rz),
            x * math.sin(rz) + y * math.cos(rz),
        )
        return float(x), float(y), float(z)
