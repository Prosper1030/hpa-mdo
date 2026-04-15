"""Mass budget aggregation, reporting, YAML round-trip, and AVL export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import math

import numpy as np

from hpa_mdo.mass.components import (
    DistributedMass,
    LineMass,
    MassComponent,
    MassRecord,
    PointMass,
)


_STANDARD_MASS_KEYS = (
    "pilot",
    "fuselage_structure",
    "wing_secondary_structure",
    "drivetrain",
    "propeller",
    "empennage",
    "controls",
    "avionics",
    "landing_gear",
    "payload",
    "ballast",
    "miscellaneous",
)


def _component_type(component: MassComponent) -> str:
    if isinstance(component, PointMass):
        return "point"
    if isinstance(component, LineMass):
        return "line"
    if isinstance(component, DistributedMass):
        return "distributed"
    return type(component).__name__.lower()


def _sum_records_mass(records: Sequence[MassRecord]) -> float:
    return float(sum(record.m_kg for record in records))


def _records_cg(records: Sequence[MassRecord]) -> np.ndarray:
    total = _sum_records_mass(records)
    if total <= 0.0:
        return np.zeros(3, dtype=float)
    weighted = np.zeros(3, dtype=float)
    for record in records:
        weighted += record.m_kg * record.xyz_array()
    return weighted / total


def _records_sigma(records: Sequence[MassRecord]) -> float:
    return float(math.sqrt(sum(record.sigma_kg**2 for record in records)))


def _dihedral_z(y_m: np.ndarray, dihedral_deg: np.ndarray) -> np.ndarray:
    z = np.zeros_like(y_m, dtype=float)
    for index in range(1, len(y_m)):
        dy = float(y_m[index] - y_m[index - 1])
        avg_dihedral_deg = 0.5 * float(dihedral_deg[index - 1] + dihedral_deg[index])
        z[index] = z[index - 1] + dy * math.tan(math.radians(avg_dihedral_deg))
    return z


def _interp_xyz_at_y(nodes_m: np.ndarray, y_query_m: float) -> np.ndarray:
    nodes = np.asarray(nodes_m, dtype=float)
    y_nodes = nodes[:, 1]
    x = float(np.interp(y_query_m, y_nodes, nodes[:, 0]))
    z = float(np.interp(y_query_m, y_nodes, nodes[:, 2]))
    return np.array([x, float(y_query_m), z], dtype=float)


def _segment_indices(y_mid_m: np.ndarray, segment_lengths_m: Sequence[float]) -> np.ndarray:
    bounds = np.concatenate(([0.0], np.cumsum(np.asarray(segment_lengths_m, dtype=float))))
    indices = np.searchsorted(bounds[1:], np.asarray(y_mid_m, dtype=float), side="right")
    return np.clip(indices, 0, len(bounds) - 2)


def _aircraft_geometry(cfg):
    from hpa_mdo.core import Aircraft

    return Aircraft.from_config(cfg)


def _material_db():
    from hpa_mdo.core import MaterialDB

    return MaterialDB()


def _spar_nodes_right(cfg, result, aircraft, spar_name: str) -> np.ndarray:
    if spar_name == "main_spar":
        nodes = np.asarray(getattr(result, "nodes", None), dtype=float)
        if nodes.ndim == 2 and nodes.shape[1] == 3 and nodes.shape[0] >= 2:
            return nodes.copy()

    if aircraft is None:
        aircraft = _aircraft_geometry(cfg)

    wing = aircraft.wing
    y = np.asarray(wing.y, dtype=float)
    z = _dihedral_z(y, np.asarray(wing.dihedral_deg, dtype=float))
    if spar_name == "main_spar":
        x = np.asarray(wing.main_spar_xc * wing.chord, dtype=float)
    elif spar_name == "rear_spar":
        x = np.asarray(wing.rear_spar_xc * wing.chord, dtype=float)
        z = z + np.asarray(wing.rear_spar_z_camber, dtype=float)
    else:
        raise ValueError(f"Unknown spar_name {spar_name!r}.")
    return np.column_stack((x, y, z))


def _spar_segment_geometry_mm(result, spar_name: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    if spar_name == "main_spar":
        return (
            None if getattr(result, "main_r_seg_mm", None) is None else np.asarray(result.main_r_seg_mm, dtype=float),
            None if getattr(result, "main_t_seg_mm", None) is None else np.asarray(result.main_t_seg_mm, dtype=float),
        )
    if spar_name == "rear_spar":
        return (
            None if getattr(result, "rear_r_seg_mm", None) is None else np.asarray(result.rear_r_seg_mm, dtype=float),
            None if getattr(result, "rear_t_seg_mm", None) is None else np.asarray(result.rear_t_seg_mm, dtype=float),
        )
    raise ValueError(f"Unknown spar_name {spar_name!r}.")


def _spar_distributed_components(
    cfg,
    result,
    *,
    spar_name: str,
    aircraft=None,
    materials_db=None,
) -> list[DistributedMass]:
    outer_mm, thickness_mm = _spar_segment_geometry_mm(result, spar_name)
    if outer_mm is None or thickness_mm is None:
        return []

    spar_cfg = getattr(cfg, spar_name)
    nodes_right = _spar_nodes_right(cfg, result, aircraft, spar_name)
    if nodes_right.shape[0] < 2:
        return []

    if materials_db is None:
        materials_db = _material_db()
    material = materials_db.get(spar_cfg.material)
    density_kgpm3 = float(material.density)

    y_mid = 0.5 * (nodes_right[:-1, 1] + nodes_right[1:, 1])
    seg_lengths = cfg.spar_segment_lengths(spar_cfg)
    seg_index = _segment_indices(y_mid, seg_lengths)
    r_outer_m = outer_mm[seg_index] / 1000.0
    wall_m = thickness_mm[seg_index] / 1000.0
    r_inner_m = np.maximum(r_outer_m - wall_m, 0.0)
    linear_density = math.pi * (r_outer_m**2 - r_inner_m**2) * density_kgpm3

    nodes_left = nodes_right.copy()
    nodes_left[:, 1] *= -1.0

    notes = f"{spar_name} auto-derived from optimizer result"
    return [
        DistributedMass.from_samples(
            name=f"{spar_name}_right",
            nodes_m=nodes_right,
            linear_kg_per_m=linear_density,
            notes=notes,
            source="from_optimization",
            segment_r_outer_m=r_outer_m,
            segment_r_inner_m=r_inner_m,
        ),
        DistributedMass.from_samples(
            name=f"{spar_name}_left",
            nodes_m=nodes_left,
            linear_kg_per_m=linear_density,
            notes=notes,
            source="from_optimization",
            segment_r_outer_m=r_outer_m,
            segment_r_inner_m=r_inner_m,
        ),
    ]


def _spar_joint_components(cfg, result, *, spar_name: str, aircraft=None) -> list[PointMass]:
    spar_cfg = getattr(cfg, spar_name)
    joint_mass_kg = float(getattr(spar_cfg, "joint_mass_kg", 0.0))
    if joint_mass_kg <= 0.0:
        return []

    joint_y_m = list(cfg.joint_positions(cfg.spar_segment_lengths(spar_cfg)))
    if not joint_y_m:
        return []

    right_nodes = _spar_nodes_right(cfg, result, aircraft, spar_name)
    components: list[PointMass] = []
    for index, y_joint_m in enumerate(joint_y_m, start=1):
        right_xyz = _interp_xyz_at_y(right_nodes, float(y_joint_m))
        left_xyz = right_xyz.copy()
        left_xyz[1] *= -1.0
        notes = f"{spar_name} joint hardware"
        components.append(
            PointMass(
                name=f"{spar_name}_joint_right_{index}",
                m_kg=joint_mass_kg,
                xyz_m=tuple(float(value) for value in right_xyz),
                notes=notes,
                source="from_optimization",
            )
        )
        components.append(
            PointMass(
                name=f"{spar_name}_joint_left_{index}",
                m_kg=joint_mass_kg,
                xyz_m=tuple(float(value) for value in left_xyz),
                notes=notes,
                source="from_optimization",
            )
        )
    return components


def _lift_wire_components(cfg, result, *, aircraft=None, materials_db=None) -> list[LineMass]:
    lift_cfg = cfg.lift_wires
    if not (lift_cfg.enabled and lift_cfg.attachments):
        return []

    if materials_db is None:
        materials_db = _material_db()
    wire_material = materials_db.get(lift_cfg.cable_material)
    cable_radius_m = 0.5 * float(lift_cfg.cable_diameter)
    cable_area_m2 = math.pi * cable_radius_m**2
    linear_density = cable_area_m2 * float(wire_material.density)

    right_nodes = _spar_nodes_right(cfg, result, aircraft, "main_spar")
    lines: list[LineMass] = []
    for index, attachment in enumerate(lift_cfg.attachments, start=1):
        attach_right = _interp_xyz_at_y(right_nodes, float(attachment.y))
        anchor = np.array(
            [float(attach_right[0]), 0.0, float(attachment.fuselage_z)],
            dtype=float,
        )

        attach_left = attach_right.copy()
        attach_left[1] *= -1.0
        lines.append(
            LineMass(
                name=f"lift_wire_right_{index}",
                linear_kg_per_m=linear_density,
                xyz_start_m=tuple(float(value) for value in anchor),
                xyz_end_m=tuple(float(value) for value in attach_right),
                r_outer_m=cable_radius_m,
                r_inner_m=0.0,
                notes="auto-derived from lift-wire geometry",
                source="from_geometry",
            )
        )
        lines.append(
            LineMass(
                name=f"lift_wire_left_{index}",
                linear_kg_per_m=linear_density,
                xyz_start_m=tuple(float(value) for value in anchor),
                xyz_end_m=tuple(float(value) for value in attach_left),
                r_outer_m=cable_radius_m,
                r_inner_m=0.0,
                notes="auto-derived from lift-wire geometry",
                source="from_geometry",
            )
        )
    return lines


def _point_mass_from_config(name: str, item_cfg) -> PointMass:
    return PointMass(
        name=name,
        m_kg=float(getattr(item_cfg, "m_kg", 0.0)),
        xyz_m=tuple(float(value) for value in getattr(item_cfg, "xyz_m", (0.0, 0.0, 0.0))),
        sigma_kg=float(getattr(item_cfg, "sigma_kg", 0.0)),
        principal_inertia_kgm2=(
            None
            if getattr(item_cfg, "principal_inertia_kgm2", None) is None
            else tuple(float(value) for value in item_cfg.principal_inertia_kgm2)
        ),
        notes=str(getattr(item_cfg, "notes", "")),
        source=str(getattr(item_cfg, "source", "config")),
    )


@dataclass
class MassBudget:
    components: list[MassComponent] = field(default_factory=list)
    reference_point_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    target_total_mass_kg: float | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        ref = np.asarray(self.reference_point_m, dtype=float).reshape(-1)
        if ref.shape != (3,):
            raise ValueError(f"reference_point_m must be length 3, got {ref.shape}.")
        self.reference_point_m = tuple(float(value) for value in ref)

    def add(self, component: MassComponent) -> None:
        self.components.append(component)

    def extend(self, components: Iterable[MassComponent]) -> None:
        for component in components:
            self.add(component)

    def records(self, *, include_zero_mass: bool = True) -> list[MassRecord]:
        records: list[MassRecord] = []
        for component in self.components:
            for record in component.records():
                if include_zero_mass or record.m_kg > 0.0:
                    records.append(record)
        return records

    def component_summaries(self) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        for component in self.components:
            records = component.records()
            component_mass_kg = _sum_records_mass(records)
            xyz = _records_cg(records)
            if component_mass_kg <= 0.0 and records:
                xyz = records[0].xyz_array()
            summaries.append(
                {
                    "name": getattr(component, "name", type(component).__name__),
                    "type": _component_type(component),
                    "mass_kg": component_mass_kg,
                    "sigma_kg": _records_sigma(records),
                    "xyz_m": xyz,
                    "notes": str(getattr(component, "notes", "")),
                    "source": str(getattr(component, "source", "derived")),
                }
            )
        return summaries

    def total_mass(self) -> float:
        return _sum_records_mass(self.records(include_zero_mass=False))

    def total_mass_kg(self) -> float:
        return self.total_mass()

    def total_sigma(self) -> float:
        return _records_sigma(self.records(include_zero_mass=False))

    def total_sigma_kg(self) -> float:
        return self.total_sigma()

    def center_of_gravity(self) -> np.ndarray:
        return _records_cg(self.records(include_zero_mass=False))

    def center_of_gravity_m(self) -> np.ndarray:
        return self.center_of_gravity()

    def cg_sigma(self) -> np.ndarray:
        active_records = self.records(include_zero_mass=False)
        total_mass_kg = self.total_mass()
        if total_mass_kg <= 0.0:
            return np.zeros(3, dtype=float)
        cg = self.center_of_gravity()
        variance = np.zeros(3, dtype=float)
        for record in active_records:
            if record.sigma_kg <= 0.0:
                continue
            sensitivity = (record.xyz_array() - cg) / total_mass_kg
            variance += (record.sigma_kg * sensitivity) ** 2
        return np.sqrt(variance)

    def cg_sigma_m(self) -> np.ndarray:
        return self.cg_sigma()

    def inertia_tensor(self, about: str | Sequence[float] = "cg") -> np.ndarray:
        if isinstance(about, str):
            token = about.strip().lower()
            if token == "cg":
                reference = self.center_of_gravity()
            elif token in {"reference", "origin"}:
                reference = np.asarray(self.reference_point_m, dtype=float)
            else:
                raise ValueError(f"Unsupported inertia reference {about!r}.")
        else:
            reference = np.asarray(about, dtype=float).reshape(-1)
            if reference.shape != (3,):
                raise ValueError(f"Explicit inertia reference must be length 3, got {reference.shape}.")

        tensor = np.zeros((3, 3), dtype=float)
        for record in self.records(include_zero_mass=False):
            tensor += record.inertia_tensor_about(reference)
        return tensor

    def inertia_tensor_about_cg(self) -> np.ndarray:
        return self.inertia_tensor(about="cg")

    def inertia_sigma_tensor(self, about: str | Sequence[float] = "cg") -> np.ndarray:
        if isinstance(about, str):
            reference = self.center_of_gravity() if about == "cg" else np.asarray(self.reference_point_m, dtype=float)
        else:
            reference = np.asarray(about, dtype=float).reshape(3)

        variance = np.zeros((3, 3), dtype=float)
        for record in self.records(include_zero_mass=False):
            if record.sigma_kg <= 0.0 or record.m_kg <= 0.0:
                continue
            contribution = record.inertia_tensor_about(reference)
            sensitivity = contribution / record.m_kg
            variance += (record.sigma_kg * sensitivity) ** 2
        return np.sqrt(variance)

    def sanity_check(
        self,
        *,
        target_total_mass_kg: float | None = None,
        tolerance: float = 0.05,
    ) -> dict[str, object]:
        target = self.target_total_mass_kg if target_total_mass_kg is None else target_total_mass_kg
        total = self.total_mass()
        if target is None or target <= 0.0:
            return {
                "passed": True,
                "total_mass_kg": total,
                "target_total_mass_kg": None,
                "delta_kg": None,
                "delta_fraction": None,
            }
        delta = total - float(target)
        fraction = delta / float(target)
        return {
            "passed": abs(fraction) <= tolerance,
            "total_mass_kg": total,
            "target_total_mass_kg": float(target),
            "delta_kg": float(delta),
            "delta_fraction": float(fraction),
        }

    def mtow_gate(self) -> dict[str, object]:
        return self.sanity_check()

    def to_dict(self) -> dict:
        return {
            "reference_point_m": list(self.reference_point_m),
            "target_total_mass_kg": self.target_total_mass_kg,
            "warnings": list(self.warnings),
            "components": [self._component_to_dict(component) for component in self.components],
        }

    @staticmethod
    def _component_to_dict(component: MassComponent) -> dict:
        return component.to_dict()

    @classmethod
    def from_dict(cls, payload: dict) -> MassBudget:
        components: list[MassComponent] = []
        for component_payload in payload.get("components", []) or []:
            component_type = str(component_payload.get("type", "")).strip().lower()
            if component_type == "point":
                components.append(PointMass.from_dict(component_payload))
            elif component_type == "line":
                components.append(LineMass.from_dict(component_payload))
            elif component_type == "distributed":
                components.append(DistributedMass.from_dict(component_payload))
            else:
                raise ValueError(f"Unsupported component type {component_type!r}.")
        return cls(
            components=components,
            reference_point_m=tuple(payload.get("reference_point_m", (0.0, 0.0, 0.0))),
            target_total_mass_kg=payload.get("target_total_mass_kg"),
            warnings=[str(item) for item in payload.get("warnings", []) or []],
        )

    def to_yaml(self, path: str | Path) -> Path:
        import yaml

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return out_path

    write_yaml = to_yaml

    @classmethod
    def from_yaml(cls, path: str | Path) -> MassBudget:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    read_yaml = from_yaml

    def report_text(self) -> str:
        total_mass_kg = self.total_mass()
        total_sigma_kg = self.total_sigma()
        cg = self.center_of_gravity()
        cg_sigma = self.cg_sigma()
        inertia = self.inertia_tensor(about="cg")
        inertia_sigma = self.inertia_sigma_tensor(about="cg")
        sanity = self.sanity_check()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# Mass Budget Report",
            "",
            f"_Generated: {timestamp}_",
            "",
            "Coordinate frame: +X aft (toward tail), +Y right wing, +Z down; "
            f"origin at `{list(self.reference_point_m)}` m.",
            "",
            "## Totals",
            "",
            f"- Total mass: **{total_mass_kg:.3f} kg**",
            f"- Total sigma: **{total_sigma_kg:.3f} kg**",
            (
                "- Center of gravity: "
                f"**[{cg[0]:+.3f}, {cg[1]:+.3f}, {cg[2]:+.3f}] m**"
            ),
            (
                "- CG sigma propagation: "
                f"**[{cg_sigma[0]:.4f}, {cg_sigma[1]:.4f}, {cg_sigma[2]:.4f}] m**"
            ),
        ]
        if sanity["target_total_mass_kg"] is not None:
            status = "PASS" if sanity["passed"] else "WARN"
            lines.append(
                "- Sanity check against operating mass: "
                f"**{status}** (target {float(sanity['target_total_mass_kg']):.3f} kg, "
                f"delta {float(sanity['delta_kg']):+.3f} kg, "
                f"{100.0 * float(sanity['delta_fraction']):+.2f}%)"
            )
        lines.append("")

        lines.extend(
            [
                "## Inertia About CG",
                "",
                "| Tensor | xx | yy | zz | xy | xz | yz |",
                "|---|---:|---:|---:|---:|---:|---:|",
                (
                    f"| Value [kg·m²] | {inertia[0, 0]:.6f} | {inertia[1, 1]:.6f} | "
                    f"{inertia[2, 2]:.6f} | {inertia[0, 1]:.6f} | "
                    f"{inertia[0, 2]:.6f} | {inertia[1, 2]:.6f} |"
                ),
                (
                    f"| Sigma [kg·m²] | {inertia_sigma[0, 0]:.6f} | {inertia_sigma[1, 1]:.6f} | "
                    f"{inertia_sigma[2, 2]:.6f} | {inertia_sigma[0, 1]:.6f} | "
                    f"{inertia_sigma[0, 2]:.6f} | {inertia_sigma[1, 2]:.6f} |"
                ),
                "",
            ]
        )

        if sanity["target_total_mass_kg"] is not None and not sanity["passed"]:
            lines.extend(
                [
                    "## Sanity Difference",
                    "",
                    "| Quantity | Mass [kg] |",
                    "|---|---:|",
                    f"| Mass budget total | {float(sanity['total_mass_kg']):.3f} |",
                    f"| Config operating mass target | {float(sanity['target_total_mass_kg']):.3f} |",
                    f"| Delta | {float(sanity['delta_kg']):+.3f} |",
                    "",
                ]
            )

        if self.warnings:
            lines.extend(["## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        lines.extend(
            [
                "## Components",
                "",
                "| Name | Type | Mass [kg] | Sigma [kg] | CG [m] | Source | Notes |",
                "|---|---|---:|---:|---|---|---|",
            ]
        )
        for summary in self.component_summaries():
            xyz = np.asarray(summary["xyz_m"], dtype=float)
            lines.append(
                f"| {summary['name']} | {summary['type']} | {float(summary['mass_kg']):.3f} | "
                f"{float(summary['sigma_kg']):.3f} | "
                f"[{xyz[0]:+.3f}, {xyz[1]:+.3f}, {xyz[2]:+.3f}] | "
                f"{summary['source']} | {summary['notes']} |"
            )
        lines.append("")
        return "\n".join(lines)

    format_report = report_text

    def write_report(self, path: str | Path) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.report_text(), encoding="utf-8")
        return out_path

    def avl_mass_text(
        self,
        *,
        Lunit: str = "m",
        Munit: str = "kg",
        Tunit: str = "s",
        g: float = 9.81,
        rho: float = 1.225,
    ) -> str:
        lines = [
            "# HPA-MDO AVL .mass file",
            "# Data rows: mass x y z Ixx Iyy Izz Ixy Ixz Iyz",
            f"Lunit = 1.0 {Lunit}",
            f"Munit = 1.0 {Munit}",
            f"Tunit = 1.0 {Tunit}",
            f"g = {float(g):.6f}",
            f"rho = {float(rho):.6f}",
            "#",
            "# mass x y z Ixx Iyy Izz Ixy Ixz Iyz",
            "*   1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0",
            "+   0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0",
        ]
        for record in self.records(include_zero_mass=False):
            inertia = record.inertia_tensor_cg_kgm2
            x, y, z = record.xyz_m
            lines.append(
                f"{record.m_kg:12.6f} {x:12.6f} {y:12.6f} {z:12.6f} "
                f"{inertia[0, 0]:12.6f} {inertia[1, 1]:12.6f} {inertia[2, 2]:12.6f} "
                f"{inertia[0, 1]:12.6f} {inertia[0, 2]:12.6f} {inertia[1, 2]:12.6f} "
                f"! {record.name}"
            )
        cg = self.center_of_gravity()
        inertia_cg = self.inertia_tensor(about="cg")
        lines.extend(
            [
                "",
                (
                    "! Mbody "
                    f"{self.total_mass():.6f} "
                    f"{inertia_cg[0, 0]:.6f} {inertia_cg[1, 1]:.6f} {inertia_cg[2, 2]:.6f} "
                    f"{inertia_cg[0, 1]:.6f} {inertia_cg[0, 2]:.6f} {inertia_cg[1, 2]:.6f} "
                    f"{cg[0]:.6f} {cg[1]:.6f} {cg[2]:.6f}"
                )
            ]
        )
        return "\n".join(lines) + "\n"

    format_avl_mass = avl_mass_text

    def to_avl_mass(
        self,
        path: str | Path,
        *,
        Lunit: str = "m",
        Munit: str = "kg",
        Tunit: str = "s",
        g: float = 9.81,
        rho: float = 1.225,
    ) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            self.avl_mass_text(Lunit=Lunit, Munit=Munit, Tunit=Tunit, g=g, rho=rho),
            encoding="utf-8",
        )
        return out_path

    write_avl_mass = to_avl_mass


def build_mass_budget_from_config(
    cfg,
    result=None,
    *,
    aircraft=None,
    materials_db=None,
) -> MassBudget:
    target_total_mass_kg = getattr(cfg.mass_budget, "target_total_mass_kg", None)
    if target_total_mass_kg is None:
        target_total_mass_kg = float(cfg.weight.operating_kg)

    budget = MassBudget(
        components=[],
        reference_point_m=tuple(float(value) for value in cfg.mass_budget.reference_point_m),
        target_total_mass_kg=float(target_total_mass_kg),
    )

    for key in _STANDARD_MASS_KEYS:
        item_cfg = getattr(cfg.mass_budget, key, None)
        if item_cfg is None:
            budget.warnings.append(f"WARN: mass_budget.{key} missing; using 0 kg placeholder.")
            budget.add(
                PointMass(
                    name=key,
                    m_kg=0.0,
                    xyz_m=(0.0, 0.0, 0.0),
                    notes="placeholder inserted because the config entry is missing",
                    source="placeholder",
                )
            )
            continue
        if not bool(getattr(item_cfg, "enabled", True)):
            continue
        budget.add(_point_mass_from_config(key, item_cfg))

    for name, item_cfg in sorted(getattr(cfg.mass_budget, "extra_items", {}).items()):
        if not bool(getattr(item_cfg, "enabled", True)):
            continue
        budget.add(_point_mass_from_config(name, item_cfg))

    if result is None:
        if getattr(cfg.mass_budget, "include_spar_from_optimization", True):
            budget.warnings.append(
                "WARN: no optimization result provided; skipped auto-derived spar masses."
            )
    elif getattr(cfg.mass_budget, "include_spar_from_optimization", True):
        if materials_db is None:
            materials_db = _material_db()
        if aircraft is None and getattr(cfg.rear_spar, "enabled", False):
            aircraft = _aircraft_geometry(cfg)

        budget.extend(
            _spar_distributed_components(
                cfg,
                result,
                spar_name="main_spar",
                aircraft=aircraft,
                materials_db=materials_db,
            )
        )
        budget.extend(
            _spar_joint_components(
                cfg,
                result,
                spar_name="main_spar",
                aircraft=aircraft,
            )
        )

        if getattr(cfg.rear_spar, "enabled", False):
            budget.extend(
                _spar_distributed_components(
                    cfg,
                    result,
                    spar_name="rear_spar",
                    aircraft=aircraft,
                    materials_db=materials_db,
                )
            )
            budget.extend(
                _spar_joint_components(
                    cfg,
                    result,
                    spar_name="rear_spar",
                    aircraft=aircraft,
                )
            )

    if getattr(cfg.mass_budget, "include_lift_wires_from_geometry", True):
        budget.extend(
            _lift_wire_components(
                cfg,
                result,
                aircraft=aircraft,
                materials_db=materials_db,
            )
        )

    return budget
