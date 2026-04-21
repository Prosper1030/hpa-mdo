from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

ESP_BATCH_BINARIES: tuple[str, ...] = ("serveCSM", "ocsm")
ESP_KNOWN_BINARIES: tuple[str, ...] = ("serveESP", *ESP_BATCH_BINARIES)


@dataclass(frozen=True)
class EspRuntimeStatus:
    available: bool
    binaries: Dict[str, Optional[str]]
    missing: List[str]
    batch_binary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "binaries": dict(self.binaries),
            "missing": list(self.missing),
            "batch_binary": self.batch_binary,
        }


def detect_esp_runtime() -> EspRuntimeStatus:
    binaries: Dict[str, Optional[str]] = {
        name: shutil.which(name) for name in ESP_KNOWN_BINARIES
    }
    missing = [name for name, path in binaries.items() if path is None]
    batch_binary = next(
        (binaries[name] for name in ESP_BATCH_BINARIES if binaries[name] is not None),
        None,
    )
    return EspRuntimeStatus(
        available=batch_binary is not None,
        binaries=binaries,
        missing=missing,
        batch_binary=batch_binary,
    )
