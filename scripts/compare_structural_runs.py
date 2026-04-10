#!/usr/bin/env python3
"""Minimal structural run comparison/report utility.

This script compares multiple run outputs (text/JSON) against a chosen baseline
and emits:
1. Terminal-readable summary
2. JSON summary (default: output/structural_compare_summary.json)
3. Optional Markdown summary

Supported inputs (minimum viable set focused on current repository outputs):
- optimization_summary.txt
- dual_beam_internal_report.txt
- guardrail_summary.json (and other JSON summaries via key-based extraction)
- ANSYS comparison/spot-check text reports emitted by existing scripts

Run spec format:
    --run LABEL=PATH
    --run LABEL=PATH::SELECTOR

For JSON files, SELECTOR is a dotted path into nested objects
(e.g. baseline_unguarded.equivalent_beam).
For text files, SELECTOR can be used as profile hint (e.g. ansys) for
internal dual-beam reports that contain both internal and ANSYS table values.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional


NUMBER_RE = r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"

METRIC_ORDER = [
    "mass_kg",
    "tip_deflection_mm",
    "max_uz_any_mm",
    "rear_tip_displacement_mm",
    "rear_main_tip_ratio",
    "failure_index",
    "buckling_index",
    "twist_deg",
    "runtime_s",
]

METRIC_LABELS = {
    "mass_kg": "Mass",
    "tip_deflection_mm": "Tip deflection",
    "max_uz_any_mm": "Max |UZ| anywhere",
    "rear_tip_displacement_mm": "Rear tip displacement",
    "rear_main_tip_ratio": "Rear/main tip ratio",
    "failure_index": "Failure index",
    "buckling_index": "Buckling index",
    "twist_deg": "Twist",
    "runtime_s": "Runtime",
}

METRIC_UNITS = {
    "mass_kg": "kg",
    "tip_deflection_mm": "mm",
    "max_uz_any_mm": "mm",
    "rear_tip_displacement_mm": "mm",
    "rear_main_tip_ratio": "",
    "failure_index": "",
    "buckling_index": "",
    "twist_deg": "deg",
    "runtime_s": "s",
}

SAFETY_METRICS = [
    "tip_deflection_mm",
    "max_uz_any_mm",
    "rear_tip_displacement_mm",
    "rear_main_tip_ratio",
    "failure_index",
    "buckling_index",
    "twist_deg",
]

JSON_MM_KEYS = {
    "tip_deflection_mm": ["tip_deflection_mm", "tip_main_mm"],
    "max_uz_any_mm": ["max_uz_any_mm", "max_uz_mm"],
    "rear_tip_displacement_mm": ["tip_rear_mm", "rear_tip_mm", "rear_tip_displacement_mm"],
}

JSON_M_KEYS = {
    "tip_deflection_mm": ["tip_deflection_m"],
    "max_uz_any_mm": ["max_uz_any_m", "max_vertical_displacement_m"],
    "rear_tip_displacement_mm": ["tip_rear_m", "rear_tip_m", "rear_tip_displacement_m"],
}

JSON_DIRECT_KEYS = {
    "mass_kg": [
        "mass_kg",
        "mass_total_kg",
        "mass_final_total_kg",
        "total_mass_full_kg",
        "final_accepted_mass_total_kg",
    ],
    "rear_main_tip_ratio": ["rear_to_main_tip_ratio", "rear_main_tip_ratio"],
    "failure_index": ["failure_index", "failure"],
    "buckling_index": ["buckling_index"],
    "twist_deg": ["twist_max_deg", "max_twist_deg", "twist_deg"],
    "runtime_s": [
        "wall_time_s",
        "elapsed_s",
        "runtime_s",
        "total_s",
        "total_time_s",
        "time_s",
    ],
}


@dataclass(frozen=True)
class RunSpec:
    label: str
    path: Path
    selector: Optional[str] = None


@dataclass
class RunResult:
    label: str
    source_path: str
    selector: Optional[str]
    source_kind: str
    metrics: dict[str, Optional[float]]
    notes: list[str] = field(default_factory=list)
    delta_pct_vs_baseline: dict[str, Optional[float]] = field(default_factory=dict)
    delta_abs_vs_baseline: dict[str, Optional[float]] = field(default_factory=dict)
    classification: str = "unclassified"


def parse_run_spec(spec: str) -> RunSpec:
    if "=" not in spec:
        raise ValueError(f"Invalid --run spec '{spec}'. Expected LABEL=PATH[::SELECTOR].")
    label, rhs = spec.split("=", 1)
    label = label.strip()
    if not label:
        raise ValueError(f"Invalid --run spec '{spec}': label cannot be empty.")

    selector = None
    path_text = rhs.strip()
    if "::" in path_text:
        path_text, selector = path_text.split("::", 1)
        selector = selector.strip() or None

    path = Path(path_text.strip()).expanduser().resolve()
    return RunSpec(label=label, path=path, selector=selector)


def _init_metrics() -> dict[str, Optional[float]]:
    return {metric: None for metric in METRIC_ORDER}


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_float(pattern: str, text: str, *, flags: int = re.MULTILINE) -> Optional[float]:
    match = re.search(pattern, text, flags=flags)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _selector_parts(selector: str) -> list[Any]:
    parts: list[Any] = []
    for token in selector.split("."):
        token = token.strip()
        if not token:
            continue
        matches = list(re.finditer(r"([^\[\]]+)|\[(\d+)\]", token))
        if not matches:
            parts.append(token)
            continue
        for match in matches:
            if match.group(1) is not None:
                parts.append(match.group(1))
            else:
                parts.append(int(match.group(2)))
    return parts


def _select_json_path(data: Any, selector: Optional[str]) -> Any:
    if selector is None:
        return data

    current = data
    for part in _selector_parts(selector):
        if isinstance(current, dict):
            key = str(part)
            if key not in current:
                raise KeyError(f"Selector key '{key}' not found.")
            current = current[key]
            continue

        if isinstance(current, list):
            if isinstance(part, int):
                idx = part
            elif str(part).isdigit():
                idx = int(part)
            else:
                raise KeyError(f"Selector part '{part}' is not a valid list index.")
            if idx < 0 or idx >= len(current):
                raise IndexError(f"Selector index {idx} out of range.")
            current = current[idx]
            continue

        raise KeyError(f"Cannot traverse selector part '{part}' on scalar value.")

    return current


def _flatten_numeric_values(data: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], float]]:
    rows: list[tuple[tuple[str, ...], float]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            rows.extend(_flatten_numeric_values(value, prefix + (str(key),)))
        return rows

    if isinstance(data, list):
        for idx, value in enumerate(data):
            rows.extend(_flatten_numeric_values(value, prefix + (str(idx),)))
        return rows

    as_float = _as_float(data)
    if as_float is not None:
        rows.append((prefix, as_float))
    return rows


def _find_first_key_match(
    flattened: list[tuple[tuple[str, ...], float]],
    candidates: list[str],
) -> Optional[float]:
    lowered_candidates = [c.lower() for c in candidates]
    for candidate in lowered_candidates:
        for path, value in flattened:
            if not path:
                continue
            if path[-1].lower() == candidate:
                return value
    return None


def _extract_metrics_from_json(data: Any, notes: list[str]) -> dict[str, Optional[float]]:
    metrics = _init_metrics()

    if isinstance(data, list):
        if not data:
            notes.append("JSON selector resolved to an empty list.")
            return metrics
        notes.append("JSON selector resolved to list; using the first element.")
        data = data[0]

    if isinstance(data, dict) and "equivalent_beam" in data and "dual_beam" in data:
        notes.append(
            "Both equivalent_beam and dual_beam found; defaulting to equivalent_beam. "
            "Use ::...dual_beam to select explicitly."
        )
        data = data["equivalent_beam"]

    flattened = _flatten_numeric_values(data)

    for metric, keys in JSON_DIRECT_KEYS.items():
        metrics[metric] = _find_first_key_match(flattened, keys)

    for metric, keys in JSON_MM_KEYS.items():
        value = _find_first_key_match(flattened, keys)
        if value is not None:
            metrics[metric] = value

    for metric, keys in JSON_M_KEYS.items():
        if metrics[metric] is not None:
            continue
        value_m = _find_first_key_match(flattened, keys)
        if value_m is not None:
            metrics[metric] = value_m * 1000.0

    if (
        metrics["rear_main_tip_ratio"] is None
        and metrics["rear_tip_displacement_mm"] is not None
        and metrics["tip_deflection_mm"] not in (None, 0.0)
    ):
        metrics["rear_main_tip_ratio"] = (
            metrics["rear_tip_displacement_mm"] / metrics["tip_deflection_mm"]
        )

    return metrics


def _extract_table_baseline_and_value(text: str, metric_name: str) -> tuple[Optional[float], Optional[float]]:
    pattern = re.compile(
        rf"^{re.escape(metric_name)}\s+({NUMBER_RE}|N/A)\s+({NUMBER_RE}|N/A)",
        flags=re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None, None

    # NUMBER_RE contains a capture group, so each table value may appear twice
    # in the regex groups (outer + inner). Pick outer groups when available.
    base_token = match.group(1)
    value_token = match.group(3) if (match.lastindex or 0) >= 3 else match.group(2)

    base = None if base_token == "N/A" else float(base_token)
    value = None if value_token == "N/A" else float(value_token)
    return base, value


def _parse_optimization_summary(text: str) -> dict[str, Optional[float]]:
    metrics = _init_metrics()
    metrics["mass_kg"] = _extract_float(rf"Spar mass \(full\):\s*{NUMBER_RE}\s*kg", text)
    if metrics["mass_kg"] is None:
        metrics["mass_kg"] = _extract_float(rf"Total mass \(full\):\s*{NUMBER_RE}\s*kg", text)

    metrics["tip_deflection_mm"] = _extract_float(
        rf"Tip deflection\s*:\s*{NUMBER_RE}\s*mm",
        text,
    )
    metrics["twist_deg"] = _extract_float(rf"Max twist\s*:\s*{NUMBER_RE}\s*deg", text)
    metrics["failure_index"] = _extract_float(rf"Failure index\s*:\s*{NUMBER_RE}", text)
    metrics["buckling_index"] = _extract_float(rf"Buckling index\s*:\s*{NUMBER_RE}", text)

    metrics["runtime_s"] = _extract_float(
        rf"OPTIMIZATION TIMING \[s\][\s\S]*?\n\s*Total\s*:\s*{NUMBER_RE}",
        text,
        flags=re.MULTILINE,
    )
    return metrics


def _parse_internal_dual_beam(text: str, selector: Optional[str], notes: list[str]) -> dict[str, Optional[float]]:
    mode = (selector or "internal").strip().lower()
    metrics = _init_metrics()

    if mode in {"ansys", "ansys_only", "spotcheck_ansys"}:
        _, tip_ansys = _extract_table_baseline_and_value(text, "Tip deflection main (mm)")
        _, max_uz_ansys = _extract_table_baseline_and_value(text, "Max |UZ| anywhere (mm)")
        _, mass_ansys = _extract_table_baseline_and_value(text, "Spar mass full-span (kg)")
        metrics["tip_deflection_mm"] = tip_ansys
        metrics["max_uz_any_mm"] = max_uz_ansys
        metrics["mass_kg"] = mass_ansys

        if all(metrics[name] is None for name in ["tip_deflection_mm", "max_uz_any_mm", "mass_kg"]):
            notes.append("ANSYS table not found in internal dual-beam report; metrics are mostly N/A.")
        return metrics

    metrics["tip_deflection_mm"] = _extract_float(
        rf"Tip deflection main \(mm\)\s*:\s*{NUMBER_RE}",
        text,
    )
    metrics["rear_tip_displacement_mm"] = _extract_float(
        rf"Tip deflection rear \(mm\)\s*:\s*{NUMBER_RE}",
        text,
    )
    metrics["max_uz_any_mm"] = _extract_float(
        rf"Max \|UZ\| anywhere \(mm\)\s*:\s*{NUMBER_RE}",
        text,
    )
    metrics["mass_kg"] = _extract_float(
        rf"Spar mass full-span\s*:\s*{NUMBER_RE}\s*kg",
        text,
    )
    metrics["failure_index"] = _extract_float(
        rf"Failure index[^:]*:\s*{NUMBER_RE}",
        text,
    )

    if (
        metrics["rear_tip_displacement_mm"] is not None
        and metrics["tip_deflection_mm"] not in (None, 0.0)
    ):
        metrics["rear_main_tip_ratio"] = (
            metrics["rear_tip_displacement_mm"] / metrics["tip_deflection_mm"]
        )

    return metrics


def _parse_ansys_compare_summary(text: str) -> dict[str, Optional[float]]:
    metrics = _init_metrics()

    _, tip_ansys = _extract_table_baseline_and_value(text, "Tip deflection @ tip node (mm)")
    _, max_uz_ansys = _extract_table_baseline_and_value(text, "Max |UZ| anywhere (mm)")
    _, twist_ansys = _extract_table_baseline_and_value(text, "Max twist angle (deg)")
    _, mass_ansys = _extract_table_baseline_and_value(text, "Total spar mass full-span (kg)")

    metrics["tip_deflection_mm"] = tip_ansys
    metrics["max_uz_any_mm"] = max_uz_ansys
    metrics["twist_deg"] = twist_ansys
    metrics["mass_kg"] = mass_ansys
    return metrics


def _parse_dual_spar_spotcheck_summary(text: str) -> dict[str, Optional[float]]:
    metrics = _init_metrics()

    _, tip_ansys = _extract_table_baseline_and_value(text, "Tip deflection @ tip node (mm)")
    _, max_uz_ansys = _extract_table_baseline_and_value(text, "Max |UZ| anywhere (mm)")
    _, mass_ansys = _extract_table_baseline_and_value(text, "Spar mass full-span (kg)")

    metrics["tip_deflection_mm"] = tip_ansys
    metrics["max_uz_any_mm"] = max_uz_ansys
    metrics["mass_kg"] = mass_ansys
    return metrics


def _parse_crossval_report(text: str) -> dict[str, Optional[float]]:
    metrics = _init_metrics()

    metrics["tip_deflection_mm"] = _extract_float(
        rf"Tip deflection \(uz, y=[^)]+\)\s+{NUMBER_RE}\s+mm",
        text,
    )
    metrics["max_uz_any_mm"] = _extract_float(rf"Max uz anywhere\s+{NUMBER_RE}\s+mm", text)
    metrics["twist_deg"] = _extract_float(rf"Max twist angle\s+{NUMBER_RE}\s+deg", text)
    metrics["mass_kg"] = _extract_float(rf"Spar tube mass \(full-span\)\s+{NUMBER_RE}\s+kg", text)

    if metrics["mass_kg"] is None:
        metrics["mass_kg"] = _extract_float(
            rf"Total optimized mass \(full\)\s+{NUMBER_RE}\s+kg",
            text,
        )

    return metrics


def _parse_text_input(path: Path, text: str, selector: Optional[str], notes: list[str]) -> RunResult:
    if "HPA-MDO Spar Optimization Summary" in text:
        metrics = _parse_optimization_summary(text)
        source_kind = "optimization_summary_txt"
    elif "Internal Dual-Beam Analysis Report" in text:
        metrics = _parse_internal_dual_beam(text, selector=selector, notes=notes)
        source_kind = "internal_dual_beam_report_txt"
    elif "ANSYS vs Internal FEM Cross-Validation Summary" in text:
        metrics = _parse_ansys_compare_summary(text)
        source_kind = "ansys_compare_summary_txt"
    elif "Dual-Spar High-Fidelity Spot-Check Summary" in text:
        metrics = _parse_dual_spar_spotcheck_summary(text)
        source_kind = "dual_spar_spotcheck_summary_txt"
    elif "HPA-MDO ANSYS Cross-Validation Report" in text:
        metrics = _parse_crossval_report(text)
        source_kind = "crossval_report_txt"
    else:
        metrics = _init_metrics()
        notes.append("Unrecognized text format; no metrics extracted.")
        source_kind = "unknown_text"

    return RunResult(
        label="",
        source_path=str(path),
        selector=selector,
        source_kind=source_kind,
        metrics=metrics,
        notes=notes,
    )


def load_run(spec: RunSpec) -> RunResult:
    if not spec.path.exists():
        raise FileNotFoundError(f"Run path not found: {spec.path}")

    notes: list[str] = []
    suffix = spec.path.suffix.lower()
    result: RunResult

    if suffix == ".json":
        raw = json.loads(spec.path.read_text(encoding="utf-8"))
        selected = _select_json_path(raw, spec.selector)
        metrics = _extract_metrics_from_json(selected, notes=notes)
        result = RunResult(
            label=spec.label,
            source_path=str(spec.path),
            selector=spec.selector,
            source_kind="json",
            metrics=metrics,
            notes=notes,
        )
    else:
        text = spec.path.read_text(encoding="utf-8", errors="ignore")
        result = _parse_text_input(spec.path, text, spec.selector, notes=notes)
        result.label = spec.label

    if (
        result.metrics["rear_main_tip_ratio"] is None
        and result.metrics["rear_tip_displacement_mm"] is not None
        and result.metrics["tip_deflection_mm"] not in (None, 0.0)
    ):
        result.metrics["rear_main_tip_ratio"] = (
            result.metrics["rear_tip_displacement_mm"] / result.metrics["tip_deflection_mm"]
        )

    return result


def _delta_pct(value: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if value is None or baseline is None:
        return None
    if abs(baseline) < 1e-9:
        return None
    denom = abs(baseline)
    return (value - baseline) / denom * 100.0


def _delta_abs(value: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if value is None or baseline is None:
        return None
    return value - baseline


def _classify_run(
    run: RunResult,
    baseline: RunResult,
) -> tuple[str, list[str]]:
    if run.label == baseline.label:
        return "baseline reference", []

    mass_delta = run.delta_pct_vs_baseline.get("mass_kg")
    if mass_delta is None:
        mass_state = "unknown_mass"
    elif mass_delta <= -1.0:
        mass_state = "lighter"
    elif mass_delta >= 1.0:
        mass_state = "heavier"
    else:
        mass_state = "same_mass"

    safer = 0
    riskier = 0
    reasons: list[str] = []

    for metric in SAFETY_METRICS:
        delta = run.delta_pct_vs_baseline.get(metric)
        if delta is None:
            continue
        if delta <= -2.0:
            safer += 1
            reasons.append(f"{METRIC_LABELS[metric]} improved ({delta:.2f}%)")
        elif delta >= 2.0:
            riskier += 1
            reasons.append(f"{METRIC_LABELS[metric]} worsened (+{delta:.2f}%)")

    if safer == 0 and riskier == 0:
        safety_state = "unknown_or_neutral"
    elif safer > riskier:
        safety_state = "safer"
    elif riskier > safer:
        safety_state = "riskier"
    else:
        safety_state = "mixed"

    if mass_state == "lighter" and safety_state == "riskier":
        return "lighter but riskier", reasons[:3]
    if mass_state == "heavier" and safety_state == "safer":
        return "heavier but meaningfully safer", reasons[:3]
    if mass_state == "lighter" and safety_state == "safer":
        return "lighter and safer", reasons[:3]
    if mass_state == "heavier" and safety_state == "riskier":
        return "heavier and riskier", reasons[:3]

    if mass_state == "heavier":
        return "heavier with no clear safety gain", reasons[:3]
    if mass_state == "lighter":
        return "lighter with no clear safety gain", reasons[:3]

    if safety_state == "safer":
        return "similar mass but safer", reasons[:3]
    if safety_state == "riskier":
        return "similar mass but riskier", reasons[:3]

    return "no meaningful improvement", reasons[:3]


def compare_runs(run_results: list[RunResult], baseline_label: str) -> dict[str, Any]:
    by_label = {run.label: run for run in run_results}
    if baseline_label not in by_label:
        raise ValueError(f"Baseline label '{baseline_label}' not found in --run specs.")

    baseline = by_label[baseline_label]

    for run in run_results:
        for metric in METRIC_ORDER:
            run.delta_pct_vs_baseline[metric] = _delta_pct(
                run.metrics.get(metric),
                baseline.metrics.get(metric),
            )
            run.delta_abs_vs_baseline[metric] = _delta_abs(
                run.metrics.get(metric),
                baseline.metrics.get(metric),
            )

        run.classification, reasoning = _classify_run(run, baseline)
        if reasoning:
            run.notes.extend(reasoning)

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_label": baseline_label,
        "metrics": METRIC_ORDER,
        "units": METRIC_UNITS,
        "runs": [
            {
                "label": run.label,
                "source_path": run.source_path,
                "selector": run.selector,
                "source_kind": run.source_kind,
                "metrics": run.metrics,
                "delta_pct_vs_baseline": run.delta_pct_vs_baseline,
                "delta_abs_vs_baseline": run.delta_abs_vs_baseline,
                "classification": run.classification,
                "notes": run.notes,
            }
            for run in run_results
        ],
    }


def _format_value(metric: str, value: Optional[float]) -> str:
    if value is None:
        return "N/A"

    if metric in {"failure_index", "buckling_index", "rear_main_tip_ratio"}:
        return f"{value:.4f}"
    return f"{value:.3f}"


def _format_delta(delta_pct: Optional[float]) -> str:
    if delta_pct is None:
        return ""
    return f" ({delta_pct:+.2f}% vs baseline)"


def build_terminal_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    baseline_label = summary["baseline_label"]

    lines.append("=" * 96)
    lines.append("Structural Comparison Summary")
    lines.append("=" * 96)
    lines.append(f"Generated (UTC): {summary['generated_at_utc']}")
    lines.append(f"Baseline      : {baseline_label}")
    lines.append("")

    for run in summary["runs"]:
        tag = "BASELINE" if run["label"] == baseline_label else "RUN"
        lines.append(f"[{tag}] {run['label']}")
        lines.append(f"  Source      : {run['source_path']}")
        if run.get("selector"):
            lines.append(f"  Selector    : {run['selector']}")
        lines.append(f"  Source kind : {run['source_kind']}")

        for metric in METRIC_ORDER:
            value = run["metrics"].get(metric)
            unit = METRIC_UNITS[metric]
            delta = run["delta_pct_vs_baseline"].get(metric)
            value_text = _format_value(metric, value)
            if unit:
                value_text = f"{value_text} {unit}"
            lines.append(
                f"  {METRIC_LABELS[metric]:24}: {value_text}{_format_delta(delta)}"
            )

        lines.append(f"  Judgment    : {run['classification']}")
        if run.get("notes"):
            lines.append(f"  Notes       : {'; '.join(run['notes'][:3])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _markdown_cell(metric: str, run: dict[str, Any]) -> str:
    value = run["metrics"].get(metric)
    delta = run["delta_pct_vs_baseline"].get(metric)
    if value is None:
        return "N/A"

    value_text = _format_value(metric, value)
    unit = METRIC_UNITS[metric]
    if unit:
        value_text = f"{value_text} {unit}"

    if delta is None:
        return value_text
    return f"{value_text} ({delta:+.2f}%)"


def build_markdown_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Structural Comparison Summary")
    lines.append("")
    lines.append(f"- Generated (UTC): {summary['generated_at_utc']}")
    lines.append(f"- Baseline: `{summary['baseline_label']}`")
    lines.append("")

    headers = [
        "run",
        "mass",
        "tip deflection",
        "max |UZ|",
        "rear tip",
        "rear/main ratio",
        "failure",
        "buckling",
        "twist",
        "runtime",
        "judgment",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    metric_for_column = [
        "mass_kg",
        "tip_deflection_mm",
        "max_uz_any_mm",
        "rear_tip_displacement_mm",
        "rear_main_tip_ratio",
        "failure_index",
        "buckling_index",
        "twist_deg",
        "runtime_s",
    ]

    for run in summary["runs"]:
        row = [f"`{run['label']}`"]
        for metric in metric_for_column:
            row.append(_markdown_cell(metric, run))
        row.append(run["classification"])
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare structural run outputs and summarize deltas vs baseline."
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="Run spec: LABEL=PATH or LABEL=PATH::SELECTOR",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Baseline label. Default: first --run label.",
    )
    parser.add_argument(
        "--json-out",
        default="output/structural_compare_summary.json",
        help="Output path for JSON summary.",
    )
    parser.add_argument(
        "--md-out",
        default=None,
        help="Optional output path for Markdown summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    run_specs = [parse_run_spec(spec_text) for spec_text in args.run]
    if len(run_specs) < 2:
        raise ValueError("At least two --run specs are required for comparison.")

    results = [load_run(spec) for spec in run_specs]
    baseline_label = args.baseline or run_specs[0].label

    summary = compare_runs(results, baseline_label=baseline_label)

    terminal_summary = build_terminal_summary(summary)
    print(terminal_summary)

    json_out_path = Path(args.json_out).expanduser().resolve()
    json_out_path.parent.mkdir(parents=True, exist_ok=True)
    json_out_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"JSON summary saved: {json_out_path}")

    if args.md_out:
        md_out_path = Path(args.md_out).expanduser().resolve()
        md_out_path.parent.mkdir(parents=True, exist_ok=True)
        md_out_path.write_text(build_markdown_summary(summary), encoding="utf-8")
        print(f"Markdown summary saved: {md_out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
