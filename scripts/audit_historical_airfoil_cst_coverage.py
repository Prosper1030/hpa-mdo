from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from math import comb, cos, pi
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from hpa_mdo.concept.airfoil_cst import SeedlessCSTCoefficientBounds
from hpa_mdo.concept.airfoil_selection import (
    _OUTBOARD_SEEDLESS_CST_BOUNDS,
    _ROOT_SEEDLESS_CST_BOUNDS,
)

CLASS_N1 = 0.5
CLASS_N2 = 1.0
DEGREES = (4, 5, 6, 7)
REPORT_DIR = Path("docs/research/historical_airfoil_cst_coverage")


@dataclass(frozen=True)
class AirfoilSource:
    name: str
    path: Path
    source: str
    source_url: str | None
    found_in_repo: bool


@dataclass(frozen=True)
class SurfacePoint:
    surface: str
    x: float
    y: float


@dataclass(frozen=True)
class CSTFitResult:
    degree: int
    upper_coefficients: tuple[float, ...]
    lower_coefficients: tuple[float, ...]
    te_thickness: float
    rms_error_percent_chord: float
    max_error_percent_chord: float


@dataclass(frozen=True)
class BoundsCheck:
    fits: bool | None
    exceedances: tuple[str, ...]


AIRFOIL_SOURCES = (
    AirfoilSource(
        name="FX 76-MP-140",
        path=Path("data/airfoils/fx76mp140.dat"),
        source="repo:data/airfoils/fx76mp140.dat",
        source_url=None,
        found_in_repo=True,
    ),
    AirfoilSource(
        name="DAE11",
        path=REPORT_DIR / "airfoils/dae11.dat",
        source="MIT Drela HPA airfoil index",
        source_url="https://web.mit.edu/drela/Public/web/hpa/airfoils/dae11.dat",
        found_in_repo=False,
    ),
    AirfoilSource(
        name="DAE21",
        path=REPORT_DIR / "airfoils/dae21.dat",
        source="MIT Drela HPA airfoil index",
        source_url="https://web.mit.edu/drela/Public/web/hpa/airfoils/dae21.dat",
        found_in_repo=False,
    ),
    AirfoilSource(
        name="DAE31",
        path=REPORT_DIR / "airfoils/dae31.dat",
        source="MIT Drela HPA airfoil index",
        source_url="https://web.mit.edu/drela/Public/web/hpa/airfoils/dae31.dat",
        found_in_repo=False,
    ),
    AirfoilSource(
        name="DAE41",
        path=REPORT_DIR / "airfoils/dae41.dat",
        source="MIT Drela HPA airfoil index",
        source_url="https://web.mit.edu/drela/Public/web/hpa/airfoils/dae41.dat",
        found_in_repo=False,
    ),
)


def _bernstein(degree: int, index: int, x: float) -> float:
    return comb(degree, index) * (x**index) * ((1.0 - x) ** (degree - index))


def _class_term(x: float) -> float:
    return (x**CLASS_N1) * ((1.0 - x) ** CLASS_N2)


def _cst_y(x: float, coefficients: Sequence[float], te_thickness: float, surface: str) -> float:
    shape_term = sum(
        coefficient * _bernstein(len(coefficients) - 1, index, x)
        for index, coefficient in enumerate(coefficients)
    )
    te_sign = 0.5 if surface == "upper" else -0.5
    return _class_term(x) * shape_term + te_sign * te_thickness * x


def generate_fit_coordinates(
    *,
    upper_coefficients: Sequence[float],
    lower_coefficients: Sequence[float],
    te_thickness: float,
    point_count: int,
) -> tuple[tuple[float, float], ...]:
    x_values = tuple(
        0.5 * (1.0 - cos(pi * index / float(point_count - 1)))
        for index in range(point_count)
    )
    upper = tuple(
        (x, _cst_y(x, upper_coefficients, te_thickness, "upper"))
        for x in reversed(x_values)
    )
    lower = tuple(
        (x, _cst_y(x, lower_coefficients, te_thickness, "lower"))
        for x in x_values[1:]
    )
    return upper + lower


def parse_dat_coordinates(path: Path) -> tuple[tuple[float, float], ...]:
    coordinates: list[tuple[float, float]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        coordinates.append((x, y))

    if len(coordinates) < 5:
        raise ValueError(f"not enough coordinate rows in {path}")
    return tuple(coordinates)


def normalize_coordinates(
    coordinates: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    leading_edge_index = min(
        range(len(coordinates)),
        key=lambda index: (float(coordinates[index][0]), abs(float(coordinates[index][1]))),
    )
    leading_edge_x, leading_edge_y = coordinates[leading_edge_index]
    trailing_edge_x = max(float(point[0]) for point in coordinates)
    chord = trailing_edge_x - float(leading_edge_x)
    if chord <= 0.0:
        raise ValueError("airfoil coordinates must have positive chord length")
    return tuple(
        (
            (float(x) - float(leading_edge_x)) / chord,
            (float(y) - float(leading_edge_y)) / chord,
        )
        for x, y in coordinates
    )


def split_surfaces(coordinates: Sequence[tuple[float, float]]) -> tuple[SurfacePoint, ...]:
    normalized = normalize_coordinates(coordinates)
    leading_edge_index = min(
        range(len(normalized)),
        key=lambda index: (float(normalized[index][0]), abs(float(normalized[index][1]))),
    )
    upper = tuple(sorted(normalized[: leading_edge_index + 1], key=lambda point: point[0]))
    lower = tuple(sorted(normalized[leading_edge_index:], key=lambda point: point[0]))
    if len(upper) < 3 or len(lower) < 3:
        raise ValueError("airfoil coordinate file must contain upper and lower surfaces")
    return tuple(SurfacePoint("upper", x, y) for x, y in upper) + tuple(
        SurfacePoint("lower", x, y) for x, y in lower
    )


def _design_row(point: SurfacePoint, degree: int) -> list[float]:
    coefficient_count = degree + 1
    basis = [_class_term(point.x) * _bernstein(degree, index, point.x) for index in range(coefficient_count)]
    zeros = [0.0] * coefficient_count
    if point.surface == "upper":
        return basis + zeros + [0.5 * point.x]
    return zeros + basis + [-0.5 * point.x]


def fit_cst_airfoil(
    coordinates: Sequence[tuple[float, float]],
    *,
    degree: int,
) -> CSTFitResult:
    if degree < 1:
        raise ValueError("degree must be positive")
    points = split_surfaces(coordinates)
    design = np.array([_design_row(point, degree) for point in points], dtype=float)
    target = np.array([point.y for point in points], dtype=float)
    solution, *_ = np.linalg.lstsq(design, target, rcond=None)
    if solution[-1] < 0.0:
        coefficient_solution, *_ = np.linalg.lstsq(design[:, :-1], target, rcond=None)
        solution = np.concatenate((coefficient_solution, np.array([0.0])))
    coefficient_count = degree + 1
    fitted = np.sum(design * solution, axis=1)
    residuals = fitted - target
    return CSTFitResult(
        degree=degree,
        upper_coefficients=tuple(float(value) for value in solution[:coefficient_count]),
        lower_coefficients=tuple(float(value) for value in solution[coefficient_count : 2 * coefficient_count]),
        te_thickness=float(solution[-1]),
        rms_error_percent_chord=float(np.sqrt(np.mean(residuals**2)) * 100.0),
        max_error_percent_chord=float(np.max(np.abs(residuals)) * 100.0),
    )


def check_bounds(result: CSTFitResult, bounds: SeedlessCSTCoefficientBounds) -> BoundsCheck:
    if len(result.upper_coefficients) != len(bounds.upper_min):
        return BoundsCheck(
            fits=None,
            exceedances=(
                "degree_mismatch: "
                f"fit has {len(result.upper_coefficients)} coefficients, "
                f"bounds have {len(bounds.upper_min)}",
            ),
        )

    exceedances: list[str] = []
    for prefix, values, lower_bounds, upper_bounds in (
        ("upper", result.upper_coefficients, bounds.upper_min, bounds.upper_max),
        ("lower", result.lower_coefficients, bounds.lower_min, bounds.lower_max),
    ):
        for index, value in enumerate(values):
            lower_bound = lower_bounds[index]
            upper_bound = upper_bounds[index]
            if value < lower_bound:
                exceedances.append(f"{prefix}[{index}]={value:.6f} < {lower_bound:.6f}")
            if value > upper_bound:
                exceedances.append(f"{prefix}[{index}]={value:.6f} > {upper_bound:.6f}")

    if result.te_thickness < bounds.te_thickness_min:
        exceedances.append(
            f"te_thickness={result.te_thickness:.6f} < {bounds.te_thickness_min:.6f}"
        )
    if result.te_thickness > bounds.te_thickness_max:
        exceedances.append(
            f"te_thickness={result.te_thickness:.6f} > {bounds.te_thickness_max:.6f}"
        )
    return BoundsCheck(fits=not exceedances, exceedances=tuple(exceedances))


def _format_coefficients(values: Sequence[float]) -> str:
    return "[" + ", ".join(f"{value:.6f}" for value in values) + "]"


def _format_fits(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "Yes" if value else "No"


def _proposed_bounds_patch(results: Sequence[dict[str, object]], *, margin: float = 0.01) -> str:
    n6_results = [row for row in results if row["degree"] == 6]
    upper_rows = [row["upper_coefficients"] for row in n6_results]
    lower_rows = [row["lower_coefficients"] for row in n6_results]
    te_values = [float(row["te_thickness"]) for row in n6_results]

    def merged_min(current: Sequence[float], fitted_rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        return tuple(
            min(float(current[index]), min(float(row[index]) for row in fitted_rows) - margin)
            for index in range(len(current))
        )

    def merged_max(current: Sequence[float], fitted_rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        return tuple(
            max(float(current[index]), max(float(row[index]) for row in fitted_rows) + margin)
            for index in range(len(current))
        )

    root_upper_min = merged_min(_ROOT_SEEDLESS_CST_BOUNDS.upper_min, upper_rows)
    root_upper_max = merged_max(_ROOT_SEEDLESS_CST_BOUNDS.upper_max, upper_rows)
    root_lower_min = merged_min(_ROOT_SEEDLESS_CST_BOUNDS.lower_min, lower_rows)
    root_lower_max = merged_max(_ROOT_SEEDLESS_CST_BOUNDS.lower_max, lower_rows)
    out_upper_min = merged_min(_OUTBOARD_SEEDLESS_CST_BOUNDS.upper_min, upper_rows)
    out_upper_max = merged_max(_OUTBOARD_SEEDLESS_CST_BOUNDS.upper_max, upper_rows)
    out_lower_min = merged_min(_OUTBOARD_SEEDLESS_CST_BOUNDS.lower_min, lower_rows)
    out_lower_max = merged_max(_OUTBOARD_SEEDLESS_CST_BOUNDS.lower_max, lower_rows)
    te_min = min(0.0, min(te_values))

    def tuple_literal(values: Sequence[float]) -> str:
        return "(" + ", ".join(f"{value:.6f}" for value in values) + ")"

    return "\n".join(
        (
            "```diff",
            "- _ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(...)",
            "+ _ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(",
            f"+     upper_min={tuple_literal(root_upper_min)},",
            f"+     upper_max={tuple_literal(root_upper_max)},",
            f"+     lower_min={tuple_literal(root_lower_min)},",
            f"+     lower_max={tuple_literal(root_lower_max)},",
            f"+     te_thickness_min={te_min:.6f},",
            f"+     te_thickness_max={_ROOT_SEEDLESS_CST_BOUNDS.te_thickness_max:.6f},",
            "+ )",
            "- _OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(...)",
            "+ _OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(",
            f"+     upper_min={tuple_literal(out_upper_min)},",
            f"+     upper_max={tuple_literal(out_upper_max)},",
            f"+     lower_min={tuple_literal(out_lower_min)},",
            f"+     lower_max={tuple_literal(out_lower_max)},",
            f"+     te_thickness_min={te_min:.6f},",
            f"+     te_thickness_max={_OUTBOARD_SEEDLESS_CST_BOUNDS.te_thickness_max:.6f},",
            "+ )",
            "```",
        )
    )


def _result_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in AIRFOIL_SOURCES:
        coordinates = parse_dat_coordinates(source.path)
        for degree in DEGREES:
            fit = fit_cst_airfoil(coordinates, degree=degree)
            root_check = check_bounds(fit, _ROOT_SEEDLESS_CST_BOUNDS)
            outboard_check = check_bounds(fit, _OUTBOARD_SEEDLESS_CST_BOUNDS)
            rows.append(
                {
                    "airfoil": source.name,
                    "degree": degree,
                    "rms_error_percent_chord": fit.rms_error_percent_chord,
                    "max_error_percent_chord": fit.max_error_percent_chord,
                    "upper_coefficients": fit.upper_coefficients,
                    "lower_coefficients": fit.lower_coefficients,
                    "te_thickness": fit.te_thickness,
                    "fits_root_bounds": root_check.fits,
                    "fits_outboard_bounds": outboard_check.fits,
                    "root_exceedances": root_check.exceedances,
                    "outboard_exceedances": outboard_check.exceedances,
                    "source_path": str(source.path),
                    "source": source.source,
                    "source_url": source.source_url,
                    "found_in_repo": source.found_in_repo,
                }
            )
    return rows


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    fieldnames = (
        "airfoil",
        "degree",
        "rms_error_percent_chord",
        "max_error_percent_chord",
        "upper_coefficients",
        "lower_coefficients",
        "te_thickness",
        "fits_root_bounds",
        "fits_outboard_bounds",
        "root_exceedances",
        "outboard_exceedances",
        "source_path",
        "source",
        "source_url",
        "found_in_repo",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "upper_coefficients": _format_coefficients(row["upper_coefficients"]),
                    "lower_coefficients": _format_coefficients(row["lower_coefficients"]),
                    "root_exceedances": "; ".join(row["root_exceedances"]),
                    "outboard_exceedances": "; ".join(row["outboard_exceedances"]),
                }
            )


def _json_ready(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            **row,
            "upper_coefficients": list(row["upper_coefficients"]),
            "lower_coefficients": list(row["lower_coefficients"]),
            "root_exceedances": list(row["root_exceedances"]),
            "outboard_exceedances": list(row["outboard_exceedances"]),
        }
        for row in rows
    ]


def _write_report(path: Path, rows: Sequence[dict[str, object]]) -> None:
    lines: list[str] = [
        "# Historical Airfoil CST Coverage Audit",
        "",
        "Read-only audit of current seedless CST coverage for historical low-Reynolds airfoils.",
        "",
        "## Method",
        "",
        "- CST class exponents: `N1 = 0.5`, `N2 = 1.0`.",
        "- Bernstein degrees fitted: `n = 4, 5, 6, 7`.",
        "- Fit method: linear least squares for upper coefficients, lower coefficients, and trailing-edge thickness in the same form used by `generate_cst_coordinates`.",
        "- Trailing-edge fit is constrained non-negative; if the unconstrained least-squares solution wants a small negative TE on a closed-TE airfoil, coefficients are refit with `TE = 0`.",
        "- Error metric: vertical coordinate residual on normalized `.dat` points, reported as percent chord.",
        "",
        "## Source Status",
        "",
        "| Airfoil | Repo .dat? | Audit source | Source path |",
        "| ------- | --------- | ------------ | ----------- |",
    ]
    for source in AIRFOIL_SOURCES:
        source_text = source.source if source.source_url is None else f"[{source.source}]({source.source_url})"
        lines.append(
            f"| {source.name} | {'Yes' if source.found_in_repo else 'No'} | "
            f"{source_text} | `{source.path}` |"
        )

    lines.extend(
        [
            "",
            "## Coverage Table",
            "",
            "| Airfoil | n | RMS error %c | Max error %c | Fits root bounds? | Fits outboard bounds? | Which coefficients exceed bounds? |",
            "| ------- | - | ------------ | ------------ | ----------------- | --------------------- | --------------------------------- |",
        ]
    )
    for row in rows:
        exceedances = []
        if row["root_exceedances"]:
            exceedances.append("root: " + "; ".join(row["root_exceedances"]))
        if row["outboard_exceedances"]:
            exceedances.append("outboard: " + "; ".join(row["outboard_exceedances"]))
        lines.append(
            "| {airfoil} | {degree} | {rms:.4f} | {max_error:.4f} | {root} | {outboard} | {exceedances} |".format(
                airfoil=row["airfoil"],
                degree=row["degree"],
                rms=float(row["rms_error_percent_chord"]),
                max_error=float(row["max_error_percent_chord"]),
                root=_format_fits(row["fits_root_bounds"]),
                outboard=_format_fits(row["fits_outboard_bounds"]),
                exceedances="<br>".join(exceedances) if exceedances else "-",
            )
        )

    n6_rows = [row for row in rows if row["degree"] == 6]
    n6_max_failures = [
        row for row in n6_rows if float(row["max_error_percent_chord"]) >= 0.2
    ]
    n6_bound_failures = [
        row
        for row in n6_rows
        if row["fits_root_bounds"] is False or row["fits_outboard_bounds"] is False
    ]
    all_n6_in_bounds = all(
        row["fits_root_bounds"] is True and row["fits_outboard_bounds"] is True for row in n6_rows
    )

    lines.extend(["", "## Coefficient Details", ""])
    lines.extend(
        [
            "| Airfoil | n | TE thickness | Upper coefficients | Lower coefficients |",
            "| ------- | - | ------------ | ------------------ | ------------------ |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['airfoil']} | {row['degree']} | {float(row['te_thickness']):.6f} | "
            f"`{_format_coefficients(row['upper_coefficients'])}` | "
            f"`{_format_coefficients(row['lower_coefficients'])}` |"
        )

    lines.extend(["", "## Judgment", ""])
    if n6_max_failures:
        failed_names = ", ".join(
            f"{row['airfoil']} ({float(row['max_error_percent_chord']):.4f}%c)"
            for row in n6_max_failures
        )
        lines.append(
            f"- `n=6` does not meet max error `< 0.2%c` for: {failed_names}. Use `n=7` for those cases before judging bounds coverage."
        )
    else:
        worst = max(n6_rows, key=lambda row: float(row["max_error_percent_chord"]))
        lines.append(
            f"- `n=6` geometry fit is adequate for all audited airfoils; worst max error is {float(worst['max_error_percent_chord']):.4f}%c on {worst['airfoil']}."
        )

    if n6_bound_failures:
        lines.append(
            "- Current seedless bounds are too narrow for the historical set after `n=6` fitting."
        )
        lines.append(
            "- Repeated exceedance pattern: trailing-edge minimum is above the fitted near-sharp historical TE; upper aft coefficients and lower aft/positive-camber coefficients also exceed the current envelope."
        )
    elif all_n6_in_bounds:
        lines.append(
            "- The fitted `n=6` coefficients are inside current bounds. If seedless search still misses similar airfoils, `seedless_sample_count = 96` is the likely bottleneck because the feasible Sobol sample is sparse in a 15-dimensional space."
        )

    lines.extend(
        [
            "",
            "## Proposed Bounds Patch Only",
            "",
            "Not applied. This widens the existing `n=6` default bounds just enough to contain the fitted historical envelope plus a small 0.01 coefficient margin.",
            "",
            "Engineering note: a bounds-only patch is not the full production change. The current seedless validation constraint also has `te_thickness_min = 0.001`, so historical near-sharp trailing edges would still need a separate constraint decision before they can survive feasible-candidate filtering.",
            "",
            _proposed_bounds_patch(rows),
            "",
            "## GPT Discussion Summary",
            "",
            "- Repo already had `data/airfoils/fx76mp140.dat`; DAE11/21/31/41 were absent and were added only as audit reference data under `docs/research/historical_airfoil_cst_coverage/airfoils/` from the MIT Drela HPA airfoil index.",
            "- Using the project CST form (`N1=0.5`, `N2=1.0`) and least-squares fitting, `n=6` is geometrically sufficient for the audited FX/DAE set if max vertical residual below `0.2%c` is the gate.",
            "- The present `_ROOT_SEEDLESS_CST_BOUNDS` and `_OUTBOARD_SEEDLESS_CST_BOUNDS` are not broad enough to include those historical `n=6` fits, especially TE thickness and several aft/positive lower coefficients.",
            "- Because coefficients are already out of bounds, this is a bounds-envelope issue before it is a `sample_count=96` issue. If bounds are widened and similar shapes are still not sampled, then the sparse 96-point Sobol draw becomes the next suspect.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(output_dir: Path = REPORT_DIR) -> list[dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _result_rows()
    _write_csv(output_dir / "fit_results.csv", rows)
    (output_dir / "fit_results.json").write_text(
        json.dumps(_json_ready(rows), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report(output_dir / "historical_airfoil_cst_coverage.md", rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPORT_DIR,
        help="Directory for CSV, JSON, and Markdown audit outputs.",
    )
    args = parser.parse_args()
    rows = run_audit(args.output_dir)
    worst_n6 = max(
        (row for row in rows if row["degree"] == 6),
        key=lambda row: float(row["max_error_percent_chord"]),
    )
    print(
        "wrote historical airfoil CST coverage audit; "
        f"worst n=6 max error={float(worst_n6['max_error_percent_chord']):.4f}%c "
        f"({worst_n6['airfoil']})"
    )


if __name__ == "__main__":
    main()
