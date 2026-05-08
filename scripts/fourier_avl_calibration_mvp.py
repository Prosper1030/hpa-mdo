#!/usr/bin/env python3
"""Build MVP 1 Fourier-AVL calibration artifacts from existing AVL station tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping

from hpa_mdo.aero.fourier_avl_calibration import (
    FourierAvlCalibrationCase,
    write_fourier_avl_calibration_artifacts,
)


DEFAULT_REPORT_JSON = Path(
    "output/birdman_mission_coupled_medium_search_20260503/"
    "mission_coupled_spanload_search_report.json"
)
DEFAULT_OUTPUT_DIR = Path("output/pipeline_redesign_v2/fourier_avl_calibration_mvp")


def load_cases_from_mission_report(
    report_json: str | Path,
    *,
    max_cases: int,
) -> list[FourierAvlCalibrationCase]:
    report_path = Path(report_json)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records_by_sample = _records_by_sample(report)
    cases: list[FourierAvlCalibrationCase] = []
    for artifact in report.get("export_artifacts", []):
        if len(cases) >= int(max_cases):
            break
        sample_index = _optional_int(artifact.get("sample_index"))
        station_csv = artifact.get("station_table_csv_path")
        if station_csv is None:
            continue
        station_path = Path(str(station_csv))
        if not station_path.is_file():
            continue
        record = records_by_sample.get(sample_index, {}) if sample_index is not None else {}
        geometry = _mapping(record.get("geometry"))
        avl_reference = _mapping(record.get("avl_reference_case"))
        fourier = _mapping(record.get("spanload_fourier"))
        rows = _read_station_csv(station_path)
        case_id = _case_id(artifact=artifact, sample_index=sample_index, rank=len(cases) + 1)
        cases.append(
            FourierAvlCalibrationCase(
                case_id=case_id,
                station_rows=rows,
                span_m=_coalesce_float(geometry.get("span_m"), _span_from_rows(rows)),
                speed_mps=_coalesce_float(record.get("design_speed_mps"), None),
                e_avl_cdi=_coalesce_float(
                    avl_reference.get("avl_e_cdi"),
                    record.get("avl_e_cdi"),
                ),
                cdi_avl=_coalesce_float(
                    avl_reference.get("trim_cd_induced"),
                    record.get("CDi"),
                ),
                commanded_r3=_coalesce_float(
                    fourier.get("a3_over_a1"),
                    record.get("a3_over_a1"),
                ),
                commanded_r5=_coalesce_float(
                    fourier.get("a5_over_a1"),
                    record.get("a5_over_a1"),
                ),
                commanded_r7=_coalesce_float(
                    fourier.get("a7_over_a1"),
                    record.get("a7_over_a1"),
                ),
                source_artifact=str(station_path),
                notes=f"source_report={report_path}",
            )
        )
    if not cases:
        raise ValueError(f"No calibration cases could be loaded from {report_path}")
    return cases


def _records_by_sample(report: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    output: dict[int, Mapping[str, Any]] = {}
    for key in ("top_candidates", "ranked_records_compact"):
        for record in report.get(key, []) or []:
            sample = _optional_int(_mapping(record).get("sample_index"))
            if sample is not None:
                output.setdefault(sample, _mapping(record))
    return output


def _read_station_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _span_from_rows(rows: list[Mapping[str, Any]]) -> float | None:
    y_values = [_optional_float(row.get("y_m")) for row in rows]
    finite_y = [float(value) for value in y_values if value is not None]
    if not finite_y:
        return None
    return 2.0 * max(finite_y)


def _case_id(*, artifact: Mapping[str, Any], sample_index: int | None, rank: int) -> str:
    bundle = str(artifact.get("bundle_dir") or "")
    if bundle:
        name = Path(bundle).name
        if name:
            return name
    if sample_index is not None:
        return f"sample_{sample_index:04d}"
    return f"case_{rank:02d}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _coalesce_float(primary: Any, fallback: Any) -> float | None:
    parsed = _optional_float(primary)
    if parsed is not None:
        return parsed
    return _optional_float(fallback)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-cases", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_cases_from_mission_report(args.report_json, max_cases=max(1, int(args.max_cases)))
    artifacts = write_fourier_avl_calibration_artifacts(cases, args.output_dir)
    print(json.dumps({key: str(path) for key, path in artifacts.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
