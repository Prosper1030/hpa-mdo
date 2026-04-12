"""Minimal consumer-facing autoresearch helpers for HPA-MDO."""

from hpa_mdo.autoresearch.consumer import (
    EXPECTED_DECISION_SCHEMA_NAME,
    EXPECTED_DECISION_SCHEMA_VERSION,
    AutoresearchConsumerError,
    AutoresearchPrimaryConfig,
    AutoresearchPrimaryRun,
    build_primary_mass_score,
    build_producer_cli_argv,
    default_output_dir,
    load_primary_mass_run,
)

__all__ = [
    "EXPECTED_DECISION_SCHEMA_NAME",
    "EXPECTED_DECISION_SCHEMA_VERSION",
    "AutoresearchConsumerError",
    "AutoresearchPrimaryConfig",
    "AutoresearchPrimaryRun",
    "build_primary_mass_score",
    "build_producer_cli_argv",
    "default_output_dir",
    "load_primary_mass_run",
]
