from enum import Enum


class ErrorCode(str, Enum):
    CONFIG_INVALID = "CONFIG_INVALID"
    AERO_PARSE_FAIL = "AERO_PARSE_FAIL"
    SOLVER_DIVERGED = "SOLVER_DIVERGED"
    EXPORT_FAIL = "EXPORT_FAIL"
    FSI_BACKEND_MISSING = "FSI_BACKEND_MISSING"
    LOAD_VALIDATION_FAIL = "LOAD_VALIDATION_FAIL"


class HPAError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")
