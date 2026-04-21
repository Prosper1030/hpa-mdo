from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class EspMaterializationResult:
    status: str
    normalized_geometry_path: Optional[Path]
    topology_report_path: Optional[Path]
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    failure_code: Optional[str] = None
    provider_version: Optional[str] = None
    command_log_path: Optional[Path] = None
    script_path: Optional[Path] = None


def materialize_with_esp(
    *,
    source_path: Path,
    staging_dir: Path,
) -> EspMaterializationResult:
    raise NotImplementedError(
        "ESP/OpenCSM materialization pipeline is not implemented yet."
    )
