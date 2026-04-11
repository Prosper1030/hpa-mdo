"""STEP export helpers for HPA-MDO spar geometry."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np


@dataclass(frozen=True)
class TubeProfile:
    x_mm: float
    y_mm: float
    z_mm: float
    outer_radius_mm: float
    inner_radius_mm: float


@dataclass(frozen=True)
class TubePath:
    name: str
    profiles: List[TubeProfile]


def load_tube_paths(csv_file: str | Path) -> List[TubePath]:
    """Load spar tube geometry from either legacy or dual-spar CSV."""
    csv_path = Path(csv_file)
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"No rows found in {csv_path}")

    headers = set(rows[0].keys())
    if "Main_Outer_Radius_m" in headers:
        return _load_dual_spar_rows(rows)
    if "Outer_Diameter_m" in headers:
        return _load_legacy_rows(rows)

    raise ValueError(
        f"Unsupported CSV format in {csv_path}. "
        "Expected dual-spar or legacy spar_data.csv columns."
    )


def export_step_from_csv(
    csv_file: str | Path,
    step_file: str | Path,
    engine: str = "auto",
    deformed_nodes: np.ndarray | None = None,
) -> str:
    """Export STEP geometry from spar CSV and return the engine used."""
    tube_paths = load_tube_paths(csv_file)
    if deformed_nodes is not None:
        tube_paths = _apply_deformed_nodes(tube_paths, deformed_nodes)
    step_path = Path(step_file)
    step_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_engine = _resolve_engine(engine)
    if resolved_engine == "cadquery":
        _export_with_cadquery(tube_paths, step_path)
    else:
        _export_with_build123d(tube_paths, step_path)
    return resolved_engine


def compute_deformed_nodes(result) -> np.ndarray:
    """Compute deformed node positions from an OptimizationResult-like object."""
    nodes = getattr(result, "nodes", None)
    disp = getattr(result, "disp", None)
    if nodes is None or disp is None:
        raise ValueError("Result must provide both 'nodes' and 'disp' for deformed export.")

    nodes_arr = np.asarray(nodes, dtype=float)
    disp_arr = np.asarray(disp, dtype=float)
    if nodes_arr.ndim != 2 or nodes_arr.shape[1] != 3:
        raise ValueError(f"nodes must have shape (n_nodes, 3), got {nodes_arr.shape}.")
    if disp_arr.ndim != 2 or disp_arr.shape[0] != nodes_arr.shape[0] or disp_arr.shape[1] < 3:
        raise ValueError(
            "disp must have shape (n_nodes, >=3) and match nodes length; "
            f"got {disp_arr.shape} for nodes {nodes_arr.shape}."
        )

    return nodes_arr + disp_arr[:, :3]


def _apply_deformed_nodes(
    tube_paths: List[TubePath],
    deformed_nodes: np.ndarray,
) -> List[TubePath]:
    """Shift tube profiles by nodal translation implied by deformed beam nodes."""
    if not tube_paths:
        raise ValueError("No tube paths available for deformed export.")

    deformed = np.asarray(deformed_nodes, dtype=float)
    if deformed.ndim != 2 or deformed.shape[1] != 3:
        raise ValueError(
            f"deformed_nodes must have shape (n_nodes, 3), got {deformed.shape}."
        )

    reference_path = next((path for path in tube_paths if path.name == "main_spar"), tube_paths[0])
    n_profiles = len(reference_path.profiles)
    if n_profiles == 0:
        raise ValueError("Reference tube path has no profiles.")
    if deformed.shape[0] != n_profiles:
        raise ValueError(
            "deformed_nodes length must match profile count. "
            f"Expected {n_profiles}, got {deformed.shape[0]}."
        )

    reference_xyz_mm = np.array(
        [[p.x_mm, p.y_mm, p.z_mm] for p in reference_path.profiles],
        dtype=float,
    )
    deltas_mm = deformed * 1000.0 - reference_xyz_mm

    transformed_paths: List[TubePath] = []
    for path in tube_paths:
        if len(path.profiles) != n_profiles:
            raise ValueError(
                f"All tube paths must have {n_profiles} profiles for deformed export; "
                f"path '{path.name}' has {len(path.profiles)}."
            )
        transformed_profiles: List[TubeProfile] = []
        for i, profile in enumerate(path.profiles):
            dx_mm, dy_mm, dz_mm = deltas_mm[i]
            transformed_profiles.append(
                TubeProfile(
                    x_mm=profile.x_mm + float(dx_mm),
                    y_mm=profile.y_mm + float(dy_mm),
                    z_mm=profile.z_mm + float(dz_mm),
                    outer_radius_mm=profile.outer_radius_mm,
                    inner_radius_mm=profile.inner_radius_mm,
                )
            )
        transformed_paths.append(TubePath(name=path.name, profiles=transformed_profiles))

    return transformed_paths


def _load_dual_spar_rows(rows: List[dict]) -> List[TubePath]:
    main_profiles: List[TubeProfile] = []
    rear_profiles: List[TubeProfile] = []

    for row in rows:
        y_mm = float(row["Y_Position_m"]) * 1000.0
        main_outer = float(row["Main_Outer_Radius_m"]) * 1000.0
        main_inner = max(
            main_outer - float(row["Main_Wall_Thickness_m"]) * 1000.0,
            0.0,
        )
        rear_outer = float(row["Rear_Outer_Radius_m"]) * 1000.0
        rear_inner = max(
            rear_outer - float(row["Rear_Wall_Thickness_m"]) * 1000.0,
            0.0,
        )

        main_profiles.append(
            TubeProfile(
                x_mm=float(row["Main_X_m"]) * 1000.0,
                y_mm=y_mm,
                z_mm=float(row["Main_Z_m"]) * 1000.0,
                outer_radius_mm=main_outer,
                inner_radius_mm=main_inner,
            )
        )
        rear_profiles.append(
            TubeProfile(
                x_mm=float(row["Rear_X_m"]) * 1000.0,
                y_mm=y_mm,
                z_mm=float(row["Rear_Z_m"]) * 1000.0,
                outer_radius_mm=rear_outer,
                inner_radius_mm=rear_inner,
            )
        )

    return [
        TubePath("main_spar", main_profiles),
        TubePath("rear_spar", rear_profiles),
    ]


def _load_legacy_rows(rows: List[dict]) -> List[TubePath]:
    profiles: List[TubeProfile] = []
    for row in rows:
        od_mm = float(row["Outer_Diameter_m"]) * 1000.0
        id_mm = float(row["Inner_Diameter_m"]) * 1000.0
        profiles.append(
            TubeProfile(
                x_mm=0.0,
                y_mm=float(row["Y_Position_m"]) * 1000.0,
                z_mm=0.0,
                outer_radius_mm=od_mm / 2.0,
                inner_radius_mm=max(id_mm / 2.0, 0.0),
            )
        )
    return [TubePath("spar", profiles)]


def _resolve_engine(engine: str) -> str:
    if engine not in {"auto", "cadquery", "build123d"}:
        raise ValueError(f"Unsupported CAD engine: {engine}")

    if engine == "auto":
        try:
            import cadquery  # noqa: F401

            return "cadquery"
        except ImportError:
            try:
                import build123d  # noqa: F401

                return "build123d"
            except ImportError as exc:
                raise RuntimeError(
                    "Neither cadquery nor build123d is installed."
                ) from exc

    if engine == "cadquery":
        import cadquery  # noqa: F401
        return engine

    import build123d  # noqa: F401
    return engine


def _export_with_cadquery(tube_paths: List[TubePath], step_path: Path) -> None:
    import cadquery as cq

    model = None
    for tube_path in tube_paths:
        outer_sections = [
            _cadquery_circle(profile, profile.outer_radius_mm) for profile in tube_path.profiles
        ]
        outer_solid = cq.Solid.makeLoft(outer_sections, True)

        inner_profiles = [
            profile for profile in tube_path.profiles if profile.inner_radius_mm > 0.0
        ]
        if len(inner_profiles) == len(tube_path.profiles):
            inner_sections = [
                _cadquery_circle(profile, profile.inner_radius_mm) for profile in inner_profiles
            ]
            inner_solid = cq.Solid.makeLoft(inner_sections, True)
            tube_solid = outer_solid.cut(inner_solid)
        else:
            tube_solid = outer_solid

        model = tube_solid if model is None else model.fuse(tube_solid)

    if model is None:
        raise ValueError("No geometry generated for STEP export.")

    _export_cadquery_step_model(model, step_path)


def _export_cadquery_step_model(model, step_path: Path) -> None:
    """Export a cadquery model as STEP regardless of .step/.stp suffix."""
    import cadquery as cq

    cq.exporters.export(model, str(step_path), exportType="STEP")


def _cadquery_circle(profile: TubeProfile, radius_mm: float):
    import cadquery as cq

    plane = cq.Plane(
        origin=(profile.x_mm, profile.y_mm, profile.z_mm),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, 1.0, 0.0),
    )
    return cq.Workplane(plane).circle(radius_mm).val()


def _export_with_build123d(tube_paths: List[TubePath], step_path: Path) -> None:
    from build123d import BuildPart, BuildSketch, Circle, export_step, loft

    model = None
    for tube_path in tube_paths:
        with BuildPart() as outer_part:
            for profile in tube_path.profiles:
                with BuildSketch(_build123d_plane(profile)):
                    Circle(profile.outer_radius_mm)
            loft(ruled=True)
        tube_solid = outer_part.part

        inner_profiles = [
            profile for profile in tube_path.profiles if profile.inner_radius_mm > 0.0
        ]
        if len(inner_profiles) == len(tube_path.profiles):
            with BuildPart() as inner_part:
                for profile in inner_profiles:
                    with BuildSketch(_build123d_plane(profile)):
                        Circle(profile.inner_radius_mm)
                loft(ruled=True)
            tube_solid = tube_solid - inner_part.part

        model = tube_solid if model is None else model + tube_solid

    if model is None:
        raise ValueError("No geometry generated for STEP export.")

    export_step(model, str(step_path))


def _build123d_plane(profile: TubeProfile):
    from build123d import Plane

    return Plane(
        origin=(profile.x_mm, profile.y_mm, profile.z_mm),
        z_dir=(0.0, 1.0, 0.0),
    )
