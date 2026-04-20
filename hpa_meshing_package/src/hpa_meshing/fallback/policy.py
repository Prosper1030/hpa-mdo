from __future__ import annotations

from typing import Dict, Any

from ..adapters.gmsh_backend import apply_recipe
from ..schema import GeometryHandle, MeshJobConfig, MeshRecipe


def run_with_fallback(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    history = []
    attempt = 1
    history.append({"attempt": attempt, "action": "initial"})
    backend_result = apply_recipe(recipe, handle, config)
    return {
        "status": backend_result["status"],
        "attempts": attempt,
        "history": history,
        "backend_result": backend_result,
        "notes": [
            "Replace with real backend retry loop.",
            f"max_attempts={config.fallback.max_attempts}",
        ],
    }


def run_with_fallback_stub(recipe: Dict[str, Any], config: MeshJobConfig) -> Dict[str, Any]:
    history = []
    attempt = 1
    history.append({"attempt": attempt, "action": "initial"})
    return {
        "status": "success",
        "attempts": attempt,
        "history": history,
        "notes": [
            "Legacy stub path retained for backward compatibility.",
            f"max_attempts={config.fallback.max_attempts}",
        ],
    }
