from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

ESP_REQUIRED_BINARIES: tuple[str, ...] = ("serveESP", "serveCSM", "ocsm")


@dataclass(frozen=True)
class EspRuntimeStatus:
    available: bool
    binaries: Dict[str, Optional[str]]
    missing: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "binaries": dict(self.binaries),
            "missing": list(self.missing),
        }


def detect_esp_runtime() -> EspRuntimeStatus:
    binaries: Dict[str, Optional[str]] = {
        name: shutil.which(name) for name in ESP_REQUIRED_BINARIES
    }
    missing = [name for name, path in binaries.items() if path is None]
    return EspRuntimeStatus(
        available=not missing,
        binaries=binaries,
        missing=missing,
    )
