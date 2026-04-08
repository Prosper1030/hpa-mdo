"""Physical constants of nature.

This module hosts only constants of nature (universal physical
constants), NOT engineering parameters. Engineering parameters
must live in YAML configs per CLAUDE.md iron rule #1.
"""
from __future__ import annotations

# Standard gravity [m/s^2] — ISO 80000-3 / CIPM 1901
G_STANDARD: float = 9.80665
