"""HPA-MDO: Human-Powered Aircraft Multidisciplinary Design Optimization Framework."""

from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.config import load_config
from hpa_mdo.core.errors import ErrorCode, HPAError
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.optimizer import OptimizationResult, SparOptimizer

__version__ = "0.1.0"

__all__ = [
    "ErrorCode",
    "HPAError",
    "LoadMapper",
    "MaterialDB",
    "OptimizationResult",
    "SparOptimizer",
    "load_config",
]
