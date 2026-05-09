"""Low-order screening helpers for current pathfinder tail contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_MISSING_STATUSES = {
    "missing",
    "blocking_missing",
    "required_missing",
    "not_found",
}


def screen_tail_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return traceable low-order tail volume/reserve diagnostics.

    This is intentionally a contract screener, not a trim solver. It computes
    only quantities that are algebraic from the committed contract fields and
    keeps missing aircraft-level inputs visible for the next full-aircraft audit.
    """

    wing = _mapping_at(contract, "reference", "wing")
    missing: list[dict[str, str]] = []
    missing.extend(_normalise_missing_items(contract.get("required_inputs_missing")))

    wing_s = _read_number(wing.get("S_w_m2"))
    wing_b = _read_number(wing.get("b_w_m"))
    wing_cbar = _read_number(wing.get("cbar_w_m"))

    for field_name, value in (
        ("reference.wing.S_w_m2", wing_s),
        ("reference.wing.b_w_m", wing_b),
        ("reference.wing.cbar_w_m", wing_cbar),
    ):
        if value is None:
            _add_missing_once(missing, field_name, "Required wing reference value is absent.")

    _collect_flagged_missing(
        contract,
        missing,
        prefix="",
        interesting_leaf_names={
            "x_ac_w_m",
            "cg_range_x_m",
            "cm_wing_body",
            "epsilon_w_model",
            "cn_beta",
            "cn_delta_v",
            "cm_delta_h",
            "tail_drag_model",
            "tail_mass_model",
        },
    )

    horizontal = _screen_horizontal_tail(
        _mapping_at(contract, "horizontal_tail", "design_box"),
        wing_s=wing_s,
        wing_cbar=wing_cbar,
        missing=missing,
    )
    vertical = _screen_vertical_tail(
        _mapping_at(contract, "vertical_tail", "design_box"),
        wing_s=wing_s,
        wing_b=wing_b,
        missing=missing,
    )

    status = "required_inputs_missing" if missing else "ready_for_low_order_screening"
    return {
        "schema_version": "tail_contract_v0_screening_v1",
        "contract_id": str(contract.get("contract_id", "")),
        "candidate_id": str(_mapping_at(contract, "pathfinder").get("candidate_id", "")),
        "status": status,
        "computed": {
            "horizontal_tail": horizontal,
            "vertical_tail": vertical,
        },
        "required_inputs_missing": missing,
        "engineering_read": _engineering_read(status=status, horizontal=horizontal, vertical=vertical),
    }


def _screen_horizontal_tail(
    design_box: Mapping[str, Any],
    *,
    wing_s: float | None,
    wing_cbar: float | None,
    missing: list[dict[str, str]],
) -> dict[str, Any]:
    area = _read_number(design_box.get("S_H_m2"))
    arm = _read_number(design_box.get("l_H_m"))
    volume: float | None = None
    if None not in (area, arm, wing_s, wing_cbar):
        volume = float(area) * float(arm) / (float(wing_s) * float(wing_cbar))
    else:
        for field_name, value in (
            ("horizontal_tail.design_box.S_H_m2", area),
            ("horizontal_tail.design_box.l_H_m", arm),
        ):
            if value is None:
                _add_missing_once(missing, field_name, "Required H-tail volume input is absent.")
    return {
        "tail_volume_coefficient": volume,
        "usable_deflection_range_deg": _usable_deflection_range(design_box),
    }


def _screen_vertical_tail(
    design_box: Mapping[str, Any],
    *,
    wing_s: float | None,
    wing_b: float | None,
    missing: list[dict[str, str]],
) -> dict[str, Any]:
    area = _read_number(design_box.get("S_V_m2"))
    arm = _read_number(design_box.get("l_V_m"))
    volume: float | None = None
    if None not in (area, arm, wing_s, wing_b):
        volume = float(area) * float(arm) / (float(wing_s) * float(wing_b))
    else:
        for field_name, value in (
            ("vertical_tail.design_box.S_V_m2", area),
            ("vertical_tail.design_box.l_V_m", arm),
        ):
            if value is None:
                _add_missing_once(missing, field_name, "Required V-tail volume input is absent.")
    return {
        "tail_volume_coefficient": volume,
        "usable_deflection_range_deg": _usable_deflection_range(design_box),
    }


def _read_number(node: Any) -> float | None:
    if isinstance(node, int | float):
        return float(node)
    if isinstance(node, Mapping):
        for key in ("value", "nominal"):
            value = node.get(key)
            if isinstance(value, int | float):
                return float(value)
        if "range" in node and isinstance(node["range"], list | tuple) and len(node["range"]) == 2:
            low, high = node["range"]
            if isinstance(low, int | float) and isinstance(high, int | float):
                return 0.5 * (float(low) + float(high))
    return None


def _usable_deflection_range(design_box: Mapping[str, Any]) -> list[float] | None:
    raw_range = design_box.get("deflection_range_deg")
    reserve = _read_number(design_box.get("deflection_reserve_deg"))
    if not isinstance(raw_range, list | tuple) or len(raw_range) != 2 or reserve is None:
        return None
    lower, upper = raw_range
    if not isinstance(lower, int | float) or not isinstance(upper, int | float):
        return None
    usable_lower = float(lower) + float(reserve)
    usable_upper = float(upper) - float(reserve)
    return [usable_lower, usable_upper]


def _mapping_at(root: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    node: Any = root
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, Mapping) else {}


def _normalise_missing_items(node: Any) -> list[dict[str, str]]:
    if not isinstance(node, list):
        return []
    items: list[dict[str, str]] = []
    for item in node:
        if not isinstance(item, Mapping):
            continue
        field = str(item.get("field", "")).strip()
        if not field:
            continue
        items.append(
            {
                "field": field,
                "reason": str(item.get("reason", "Required input is missing.")),
            }
        )
    return items


def _collect_flagged_missing(
    node: Any,
    missing: list[dict[str, str]],
    *,
    prefix: str,
    interesting_leaf_names: set[str],
) -> None:
    if isinstance(node, Mapping):
        status = str(node.get("status", "")).strip()
        value = node.get("value", "not-a-value-field")
        leaf_name = prefix.rsplit(".", maxsplit=1)[-1]
        if (
            prefix
            and leaf_name in interesting_leaf_names
            and (status in _MISSING_STATUSES or value is None)
        ):
            _add_missing_once(
                missing,
                prefix,
                str(node.get("reason", "Required input is missing.")),
            )
        for key, child in node.items():
            if key in {"source", "reason", "status", "note"}:
                continue
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            _collect_flagged_missing(
                child,
                missing,
                prefix=child_prefix,
                interesting_leaf_names=interesting_leaf_names,
            )
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _collect_flagged_missing(
                child,
                missing,
                prefix=f"{prefix}[{index}]",
                interesting_leaf_names=interesting_leaf_names,
            )


def _add_missing_once(missing: list[dict[str, str]], field: str, reason: str) -> None:
    if any(item.get("field") == field for item in missing):
        return
    missing.append({"field": field, "reason": reason})


def _engineering_read(
    *,
    status: str,
    horizontal: Mapping[str, Any],
    vertical: Mapping[str, Any],
) -> str:
    if status == "required_inputs_missing":
        return (
            "Low-order tail volume/reserve bookkeeping is available, but this is not a "
            "trim or stability pass until the missing CG, moment, downwash, stability, "
            "drag, and mass inputs are supplied."
        )
    h_volume = horizontal.get("tail_volume_coefficient")
    v_volume = vertical.get("tail_volume_coefficient")
    return (
        f"Low-order algebraic screening is populated with V_H={h_volume:.6g} and "
        f"V_V={v_volume:.6g}; full-aircraft AVL trim/stability is still the next gate."
    )
