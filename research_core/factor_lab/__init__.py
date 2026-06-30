from __future__ import annotations

from importlib import import_module
from typing import Any

from research_core.factor_lab.runtime import FactorLabWorkspaceConfig

_SERVICE_EXPORTS = {
    "get_alpha101_factor_detail",
    "get_factor_lab_job",
    "get_factor_lab_overview",
    "list_alpha101_factors",
    "list_factor_lab_jobs",
    "run_alpha101_research_job",
}

__all__ = [
    "FactorLabWorkspaceConfig",
    "get_alpha101_factor_detail",
    "get_factor_lab_job",
    "get_factor_lab_overview",
    "list_alpha101_factors",
    "list_factor_lab_jobs",
    "run_alpha101_research_job",
]


def __getattr__(name: str) -> Any:
    if name in _SERVICE_EXPORTS:
        service = import_module("research_core.factor_lab.service")
        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
