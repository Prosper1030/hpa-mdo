from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml


def _validate_stations_rows(stations_rows: list[dict]) -> None:
    if not stations_rows:
        raise ValueError("stations_rows must not be empty.")

    expected_keys = set(stations_rows[0].keys())
    for row in stations_rows[1:]:
        if set(row.keys()) != expected_keys:
            raise ValueError("stations_rows rows must share the same schema.")


def write_selected_concept_bundle(
    *,
    output_dir: Path,
    concept_id: str,
    concept_config: dict,
    stations_rows: list[dict],
    airfoil_templates: dict,
    lofting_guides: dict,
    prop_assumption: dict,
    concept_summary: dict,
) -> Path:
    _validate_stations_rows(stations_rows)

    bundle_dir = Path(output_dir) / concept_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    (bundle_dir / "concept_config.yaml").write_text(
        yaml.safe_dump(concept_config, sort_keys=False),
        encoding="utf-8",
    )

    with (bundle_dir / "stations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stations_rows[0].keys()))
        writer.writeheader()
        writer.writerows(stations_rows)

    (bundle_dir / "airfoil_templates.json").write_text(
        json.dumps(airfoil_templates, indent=2),
        encoding="utf-8",
    )
    (bundle_dir / "lofting_guides.json").write_text(
        json.dumps(lofting_guides, indent=2),
        encoding="utf-8",
    )
    (bundle_dir / "prop_assumption.json").write_text(
        json.dumps(prop_assumption, indent=2),
        encoding="utf-8",
    )
    (bundle_dir / "concept_summary.json").write_text(
        json.dumps(concept_summary, indent=2),
        encoding="utf-8",
    )
    return bundle_dir
