"""Mass-budget component dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from hpa_mdo.mass.inertia import parallel_axis, rotate_inertia_tensor, tube_inertia


def _as_xyz_tuple(values: Sequence[float]) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.shape != (3,):
        raise ValueError(f"Expected xyz shape (3,), got {arr.shape}.")
    return tuple(float(value) for value in arr)


def _as_nodes_array(values: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"Expected nodes with shape (n, 3), got {arr.shape}.")
    if arr.shape[0] < 2:
        raise ValueError("DistributedMass requires at least two nodes.")
    return arr.copy()


def _optional_tensor(
    principal_inertia_kgm2: Sequence[float] | None,
    inertia_tensor_kgm2: Sequence[Sequence[float]] | np.ndarray | None,
) -> np.ndarray:
    if inertia_tensor_kgm2 is not None:
        arr = np.asarray(inertia_tensor_kgm2, dtype=float)
        if arr.shape != (3, 3):
            raise ValueError(f"inertia_tensor_kgm2 must be (3, 3), got {arr.shape}.")
        return arr.copy()
    if principal_inertia_kgm2 is not None:
        diag = np.asarray(principal_inertia_kgm2, dtype=float).reshape(-1)
        if diag.shape != (3,):
            raise ValueError(
                f"principal_inertia_kgm2 must be length 3, got {diag.shape}."
            )
        return np.diag(diag)
    return np.zeros((3, 3), dtype=float)


def _split_sigma_by_mass(total_sigma_kg: float, masses_kg: np.ndarray) -> np.ndarray:
    if total_sigma_kg <= 0.0:
        return np.zeros_like(masses_kg, dtype=float)
    masses = np.asarray(masses_kg, dtype=float)
    if masses.size == 0 or np.all(masses <= 0.0):
        return np.zeros_like(masses, dtype=float)
    norm = float(np.linalg.norm(masses))
    if norm <= 0.0:
        return np.zeros_like(masses, dtype=float)
    return float(total_sigma_kg) * masses / norm


@dataclass
class MassRecord:
    """Flattened mass contribution used for aggregation and AVL export."""

    name: str
    component_type: str
    m_kg: float
    xyz_m: tuple[float, float, float]
    sigma_kg: float = 0.0
    inertia_tensor_cg_kgm2: np.ndarray = field(
        default_factory=lambda: np.zeros((3, 3), dtype=float)
    )
    notes: str = ""
    source: str = "derived"

    def __post_init__(self) -> None:
        if self.m_kg < 0.0:
            raise ValueError(f"{self.name}: m_kg must be >= 0.")
        if self.sigma_kg < 0.0:
            raise ValueError(f"{self.name}: sigma_kg must be >= 0.")
        self.xyz_m = _as_xyz_tuple(self.xyz_m)
        self.inertia_tensor_cg_kgm2 = _optional_tensor(
            None,
            self.inertia_tensor_cg_kgm2,
        )

    def xyz_array(self) -> np.ndarray:
        return np.asarray(self.xyz_m, dtype=float)

    def inertia_tensor_about(self, about_xyz_m: Sequence[float]) -> np.ndarray:
        ref = np.asarray(about_xyz_m, dtype=float).reshape(3)
        offset = self.xyz_array() - ref
        return parallel_axis(self.inertia_tensor_cg_kgm2, self.m_kg, offset)


@dataclass
class PointMass:
    name: str
    m_kg: float
    xyz_m: tuple[float, float, float]
    sigma_kg: float = 0.0
    principal_inertia_kgm2: tuple[float, float, float] | None = None
    inertia_tensor_kgm2: np.ndarray | None = None
    notes: str = ""
    source: str = "config"

    def __post_init__(self) -> None:
        if self.m_kg < 0.0:
            raise ValueError(f"{self.name}: m_kg must be >= 0.")
        if self.sigma_kg < 0.0:
            raise ValueError(f"{self.name}: sigma_kg must be >= 0.")
        self.xyz_m = _as_xyz_tuple(self.xyz_m)
        if self.principal_inertia_kgm2 is not None:
            diag = np.asarray(self.principal_inertia_kgm2, dtype=float).reshape(-1)
            if diag.shape != (3,):
                raise ValueError(
                    f"{self.name}: principal_inertia_kgm2 must be length 3."
                )
            self.principal_inertia_kgm2 = tuple(float(value) for value in diag)
        if self.inertia_tensor_kgm2 is not None:
            self.inertia_tensor_kgm2 = _optional_tensor(None, self.inertia_tensor_kgm2)

    def own_inertia_tensor(self) -> np.ndarray:
        return _optional_tensor(self.principal_inertia_kgm2, self.inertia_tensor_kgm2)

    def records(self) -> list[MassRecord]:
        return [
            MassRecord(
                name=self.name,
                component_type="point",
                m_kg=float(self.m_kg),
                xyz_m=self.xyz_m,
                sigma_kg=float(self.sigma_kg),
                inertia_tensor_cg_kgm2=self.own_inertia_tensor(),
                notes=self.notes,
                source=self.source,
            )
        ]

    def to_dict(self) -> dict:
        payload = {
            "type": "point",
            "name": self.name,
            "m_kg": float(self.m_kg),
            "xyz_m": list(self.xyz_m),
            "sigma_kg": float(self.sigma_kg),
            "notes": self.notes,
            "source": self.source,
        }
        if self.principal_inertia_kgm2 is not None:
            payload["principal_inertia_kgm2"] = list(self.principal_inertia_kgm2)
        if self.inertia_tensor_kgm2 is not None:
            payload["inertia_tensor_kgm2"] = self.inertia_tensor_kgm2.tolist()
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> PointMass:
        return cls(
            name=str(payload["name"]),
            m_kg=float(payload.get("m_kg", 0.0)),
            xyz_m=tuple(float(value) for value in payload.get("xyz_m", (0.0, 0.0, 0.0))),
            sigma_kg=float(payload.get("sigma_kg", 0.0)),
            principal_inertia_kgm2=(
                None
                if payload.get("principal_inertia_kgm2") is None
                else tuple(float(value) for value in payload["principal_inertia_kgm2"])
            ),
            inertia_tensor_kgm2=payload.get("inertia_tensor_kgm2"),
            notes=str(payload.get("notes", "")),
            source=str(payload.get("source", "config")),
        )


@dataclass
class LineMass:
    name: str
    linear_kg_per_m: float
    xyz_start_m: tuple[float, float, float]
    xyz_end_m: tuple[float, float, float]
    sigma_kg: float = 0.0
    r_outer_m: float = 0.0
    r_inner_m: float = 0.0
    notes: str = ""
    source: str = "derived"

    def __post_init__(self) -> None:
        if self.linear_kg_per_m < 0.0:
            raise ValueError(f"{self.name}: linear_kg_per_m must be >= 0.")
        if self.sigma_kg < 0.0:
            raise ValueError(f"{self.name}: sigma_kg must be >= 0.")
        if self.r_outer_m < 0.0 or self.r_inner_m < 0.0:
            raise ValueError(f"{self.name}: radii must be >= 0.")
        if self.r_inner_m > self.r_outer_m:
            raise ValueError(f"{self.name}: r_inner_m must not exceed r_outer_m.")
        self.xyz_start_m = _as_xyz_tuple(self.xyz_start_m)
        self.xyz_end_m = _as_xyz_tuple(self.xyz_end_m)

    def start_array(self) -> np.ndarray:
        return np.asarray(self.xyz_start_m, dtype=float)

    def end_array(self) -> np.ndarray:
        return np.asarray(self.xyz_end_m, dtype=float)

    def direction_vector(self) -> np.ndarray:
        return self.end_array() - self.start_array()

    def length_m(self) -> float:
        return float(np.linalg.norm(self.direction_vector()))

    def mass_kg(self) -> float:
        return float(self.linear_kg_per_m) * self.length_m()

    def center_of_gravity(self) -> np.ndarray:
        return 0.5 * (self.start_array() + self.end_array())

    def own_inertia_tensor(self) -> np.ndarray:
        mass = self.mass_kg()
        length = self.length_m()
        if mass <= 0.0 or length <= 0.0:
            return np.zeros((3, 3), dtype=float)
        local = tube_inertia(
            mass,
            length,
            float(self.r_outer_m),
            float(self.r_inner_m),
            axis="x",
        )
        return rotate_inertia_tensor(local, self.direction_vector(), axis="x")

    def records(self) -> list[MassRecord]:
        return [
            MassRecord(
                name=self.name,
                component_type="line",
                m_kg=self.mass_kg(),
                xyz_m=tuple(float(value) for value in self.center_of_gravity()),
                sigma_kg=float(self.sigma_kg),
                inertia_tensor_cg_kgm2=self.own_inertia_tensor(),
                notes=self.notes,
                source=self.source,
            )
        ]

    def to_dict(self) -> dict:
        return {
            "type": "line",
            "name": self.name,
            "linear_kg_per_m": float(self.linear_kg_per_m),
            "xyz_start_m": list(self.xyz_start_m),
            "xyz_end_m": list(self.xyz_end_m),
            "sigma_kg": float(self.sigma_kg),
            "r_outer_m": float(self.r_outer_m),
            "r_inner_m": float(self.r_inner_m),
            "notes": self.notes,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> LineMass:
        return cls(
            name=str(payload["name"]),
            linear_kg_per_m=float(payload.get("linear_kg_per_m", 0.0)),
            xyz_start_m=tuple(float(value) for value in payload.get("xyz_start_m", (0.0, 0.0, 0.0))),
            xyz_end_m=tuple(float(value) for value in payload.get("xyz_end_m", (0.0, 0.0, 0.0))),
            sigma_kg=float(payload.get("sigma_kg", 0.0)),
            r_outer_m=float(payload.get("r_outer_m", 0.0)),
            r_inner_m=float(payload.get("r_inner_m", 0.0)),
            notes=str(payload.get("notes", "")),
            source=str(payload.get("source", "derived")),
        )


@dataclass
class DistributedMass:
    name: str
    mass_fn: Callable[[np.ndarray], np.ndarray]
    nodes_m: np.ndarray
    sigma_kg: float = 0.0
    notes: str = ""
    source: str = "derived"
    segment_r_outer_m: np.ndarray | None = field(default=None, repr=False)
    segment_r_inner_m: np.ndarray | None = field(default=None, repr=False)
    _sampled_linear_kg_per_m: np.ndarray | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.sigma_kg < 0.0:
            raise ValueError(f"{self.name}: sigma_kg must be >= 0.")
        self.nodes_m = _as_nodes_array(self.nodes_m)
        n_segments = self.nodes_m.shape[0] - 1
        if self.segment_r_outer_m is not None:
            outer = np.asarray(self.segment_r_outer_m, dtype=float).reshape(-1)
            if outer.shape != (n_segments,):
                raise ValueError(
                    f"{self.name}: segment_r_outer_m must be length {n_segments}."
                )
            self.segment_r_outer_m = outer
        if self.segment_r_inner_m is not None:
            inner = np.asarray(self.segment_r_inner_m, dtype=float).reshape(-1)
            if inner.shape != (n_segments,):
                raise ValueError(
                    f"{self.name}: segment_r_inner_m must be length {n_segments}."
                )
            self.segment_r_inner_m = inner
        if self.segment_r_outer_m is not None and self.segment_r_inner_m is not None:
            if np.any(self.segment_r_inner_m > self.segment_r_outer_m):
                raise ValueError(
                    f"{self.name}: segment_r_inner_m must not exceed segment_r_outer_m."
                )
        if self._sampled_linear_kg_per_m is not None:
            sampled = np.asarray(self._sampled_linear_kg_per_m, dtype=float).reshape(-1)
            if sampled.shape != (n_segments,):
                raise ValueError(
                    f"{self.name}: sampled linear density must be length {n_segments}."
                )
            if np.any(sampled < 0.0):
                raise ValueError(f"{self.name}: sampled linear density must be >= 0.")
            self._sampled_linear_kg_per_m = sampled

    @classmethod
    def from_samples(
        cls,
        name: str,
        nodes_m: Sequence[Sequence[float]] | np.ndarray,
        linear_kg_per_m: Sequence[float] | np.ndarray,
        *,
        sigma_kg: float = 0.0,
        notes: str = "",
        source: str = "derived",
        segment_r_outer_m: Sequence[float] | np.ndarray | None = None,
        segment_r_inner_m: Sequence[float] | np.ndarray | None = None,
    ) -> DistributedMass:
        nodes_arr = _as_nodes_array(nodes_m)
        sampled = np.asarray(linear_kg_per_m, dtype=float).reshape(-1)
        n_segments = nodes_arr.shape[0] - 1
        if sampled.shape != (n_segments,):
            raise ValueError(
                f"{name}: linear_kg_per_m samples must be length {n_segments}."
            )
        if np.any(sampled < 0.0):
            raise ValueError(f"{name}: linear_kg_per_m samples must be >= 0.")

        def _mass_fn(_: np.ndarray, sampled_values: np.ndarray = sampled) -> np.ndarray:
            return sampled_values.copy()

        return cls(
            name=name,
            mass_fn=_mass_fn,
            nodes_m=nodes_arr,
            sigma_kg=float(sigma_kg),
            notes=notes,
            source=source,
            segment_r_outer_m=(
                None
                if segment_r_outer_m is None
                else np.asarray(segment_r_outer_m, dtype=float).reshape(-1)
            ),
            segment_r_inner_m=(
                None
                if segment_r_inner_m is None
                else np.asarray(segment_r_inner_m, dtype=float).reshape(-1)
            ),
            _sampled_linear_kg_per_m=sampled,
        )

    def linear_density_per_segment(self) -> np.ndarray:
        if self._sampled_linear_kg_per_m is not None:
            return self._sampled_linear_kg_per_m.copy()
        values = np.asarray(self.mass_fn(self.nodes_m.copy()), dtype=float).reshape(-1)
        n_nodes = self.nodes_m.shape[0]
        if values.shape == (n_nodes - 1,):
            rho = values
        elif values.shape == (n_nodes,):
            rho = 0.5 * (values[:-1] + values[1:])
        else:
            raise ValueError(
                f"{self.name}: mass_fn must return shape {(n_nodes - 1,)} or {(n_nodes,)}, "
                f"got {values.shape}."
            )
        if np.any(rho < 0.0):
            raise ValueError(f"{self.name}: mass_fn returned negative linear density.")
        return rho

    def line_components(self) -> list[LineMass]:
        rho = self.linear_density_per_segment()
        segment_vectors = self.nodes_m[1:] - self.nodes_m[:-1]
        lengths = np.linalg.norm(segment_vectors, axis=1)
        masses = rho * lengths
        sigmas = _split_sigma_by_mass(float(self.sigma_kg), masses)
        line_components: list[LineMass] = []
        for index in range(self.nodes_m.shape[0] - 1):
            outer = 0.0 if self.segment_r_outer_m is None else float(self.segment_r_outer_m[index])
            inner = 0.0 if self.segment_r_inner_m is None else float(self.segment_r_inner_m[index])
            line_components.append(
                LineMass(
                    name=f"{self.name}_seg{index + 1}",
                    linear_kg_per_m=float(rho[index]),
                    xyz_start_m=tuple(float(value) for value in self.nodes_m[index]),
                    xyz_end_m=tuple(float(value) for value in self.nodes_m[index + 1]),
                    sigma_kg=float(sigmas[index]),
                    r_outer_m=outer,
                    r_inner_m=inner,
                    notes=self.notes,
                    source=self.source,
                )
            )
        return line_components

    def records(self) -> list[MassRecord]:
        records: list[MassRecord] = []
        for component in self.line_components():
            records.extend(component.records())
        return records

    def to_dict(self) -> dict:
        payload = {
            "type": "distributed",
            "name": self.name,
            "nodes_m": self.nodes_m.tolist(),
            "linear_kg_per_m": self.linear_density_per_segment().tolist(),
            "sigma_kg": float(self.sigma_kg),
            "notes": self.notes,
            "source": self.source,
        }
        if self.segment_r_outer_m is not None:
            payload["segment_r_outer_m"] = self.segment_r_outer_m.tolist()
        if self.segment_r_inner_m is not None:
            payload["segment_r_inner_m"] = self.segment_r_inner_m.tolist()
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> DistributedMass:
        return cls.from_samples(
            name=str(payload["name"]),
            nodes_m=payload["nodes_m"],
            linear_kg_per_m=payload["linear_kg_per_m"],
            sigma_kg=float(payload.get("sigma_kg", 0.0)),
            notes=str(payload.get("notes", "")),
            source=str(payload.get("source", "derived")),
            segment_r_outer_m=payload.get("segment_r_outer_m"),
            segment_r_inner_m=payload.get("segment_r_inner_m"),
        )


MassComponent = PointMass | LineMass | DistributedMass
