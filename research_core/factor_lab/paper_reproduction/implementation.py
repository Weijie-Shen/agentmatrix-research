from __future__ import annotations

import json
import keyword
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.data_validation import DataFrameValidationResult
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig

KNOWN_OPERATOR_HINTS = {
    "abs",
    "correlation",
    "covariance",
    "delta",
    "delay",
    "log",
    "mean",
    "rank",
    "scale",
    "sign",
    "signedpower",
    "stddev",
    "sum",
    "ts_argmax",
    "ts_argmin",
    "ts_max",
    "ts_mean",
    "ts_min",
    "ts_rank",
}

FORMULA_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(slots=True)
class FactorImplementationPlan:
    factor_name: str
    status: str
    formula: str
    required_fields: list[str]
    suggested_function_name: str
    required_operator_hints: list[str] = field(default_factory=list)
    ai_designed_functions: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    test_requirements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FamilyImplementationManifest:
    family_name: str
    library_slug: str
    factors: list[FactorImplementationPlan]
    status: str
    paper_local_evaluators: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_implementation_manifest(
    specs: list[FactorResearchSpec],
    *,
    data_validation_results: dict[str, DataFrameValidationResult] | None = None,
) -> FamilyImplementationManifest:
    if not specs:
        raise ValueError("At least one FactorResearchSpec is required to build an implementation manifest.")
    family_name = specs[0].library
    library_slug = _slug(family_name)
    data_validation_results = data_validation_results or {}
    plans = [_build_factor_plan(spec, data_validation_results.get(spec.factor_name)) for spec in specs]
    status = _manifest_status(plans)
    return FamilyImplementationManifest(
        family_name=family_name,
        library_slug=library_slug,
        factors=plans,
        status=status,
        paper_local_evaluators=_paper_local_evaluators(specs, library_slug=library_slug),
    )


def export_implementation_manifest(
    manifest: FamilyImplementationManifest,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> Path:
    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    output_dir = workspace.runtime_root / "implementation_plans"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{manifest.library_slug}_implementation_manifest.json"
    path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_factor_family_scaffold(manifest: FamilyImplementationManifest, family_dir: str | Path) -> dict[str, Path]:
    output_dir = Path(family_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    init_path = output_dir / "__init__.py"
    factors_path = output_dir / "factors.py"
    tests_path = output_dir / "test_factors.py"
    module_slug = manifest.library_slug
    constant_name = f"IMPLEMENTED_{module_slug.upper()}_FACTORS"
    compute_name = f"compute_{module_slug}_factors"

    init_path.write_text(
        "from __future__ import annotations\n\n"
        f"from .factors import {constant_name}, {compute_name}\n\n"
        f"__all__ = [\"{constant_name}\", \"{compute_name}\"]\n",
        encoding="utf-8",
    )
    factors_path.write_text(_render_factors_scaffold(manifest, constant_name=constant_name, compute_name=compute_name), encoding="utf-8")
    tests_path.write_text(_render_tests_scaffold(manifest, constant_name=constant_name, compute_name=compute_name), encoding="utf-8")
    return {"init": init_path, "factors": factors_path, "tests": tests_path}


def _build_factor_plan(
    spec: FactorResearchSpec,
    data_validation: DataFrameValidationResult | None,
) -> FactorImplementationPlan:
    blocked_reasons: list[str] = []
    status = "ready_for_code"
    factor_ambiguities = _factor_ambiguities(spec)
    if any(factor_ambiguities.values()):
        status = "needs_human_review"
        blocked_reasons.append("formula ambiguities must be resolved")
    if spec.metadata.get("status") == "needs_human_review" and status == "ready_for_code":
        status = "needs_human_review"
        blocked_reasons.append("spec normalization marked this factor as needs_human_review")
    if data_validation is not None:
        if not data_validation.valid or data_validation.status == "failed":
            status = "blocked_by_data"
            blocked_reasons.extend(data_validation.errors or ["input dataframe validation failed"])
        elif data_validation.status == "needs_human_review" and status == "ready_for_code":
            status = "ready_for_code_with_limitations"

    required_operator_hints, ai_designed_functions = _operator_and_ai_function_hints(spec)
    return FactorImplementationPlan(
        factor_name=spec.factor_name,
        status=status,
        formula=spec.formula,
        required_fields=list(spec.required_fields),
        suggested_function_name=f"compute_{_slug(spec.factor_name)}",
        required_operator_hints=required_operator_hints,
        ai_designed_functions=ai_designed_functions,
        blocked_reasons=blocked_reasons,
        test_requirements=[
            "import generated factor family module",
            "compute output with date, code, and requested factor columns",
            "preserve input row count",
            "factor columns are numeric or null",
            "replace infinite outputs with nulls",
            "check paper-reported truth sources after implementation",
        ],
        metadata={
            "truth_source_summary": spec.metadata.get("truth_source_summary", {}),
            "factor_ambiguities_by_category": factor_ambiguities,
            "data_requirements": spec.metadata.get("data_requirements", {}),
            "known_limitations": spec.metadata.get("known_limitations", []),
            "data_validation_status": data_validation.status if data_validation else "not_provided",
            "data_validation_warnings": data_validation.warnings if data_validation else [],
            "evaluation_support_summary": spec.metadata.get("evaluation_support_summary", {}),
            "evaluator_implementation_targets": spec.metadata.get("evaluator_implementation_targets", []),
        },
    )


def _paper_local_evaluators(specs: list[FactorResearchSpec], *, library_slug: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        targets = spec.metadata.get("evaluator_implementation_targets", [])
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            family = str(target.get("evaluation_family", "") or "custom")
            function_name = str(target.get("suggested_function_name", "") or f"evaluate_{library_slug}_{family}")
            key = (family, function_name)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "evaluation_family": family,
                    "suggested_function_name": function_name,
                    "reason": str(target.get("reason", "No generic evaluator exists for this paper evaluation method.")),
                }
            )
    return result


def _operator_and_ai_function_hints(spec: FactorResearchSpec) -> tuple[list[str], list[str]]:
    identifiers = {identifier.lower() for identifier in FORMULA_IDENTIFIER_RE.findall(spec.formula)}
    fields = {field.lower() for field in spec.required_fields}
    parameter_names = {str(name).lower() for name in spec.parameters}
    noise = fields | parameter_names | {"true", "false", "nan", "if", "else"}
    operator_hints = sorted(identifier for identifier in identifiers if identifier in KNOWN_OPERATOR_HINTS)
    ai_functions = sorted(
        identifier
        for identifier in identifiers
        if identifier not in KNOWN_OPERATOR_HINTS and identifier not in noise and not keyword.iskeyword(identifier)
    )
    return operator_hints, ai_functions


def _factor_ambiguities(spec: FactorResearchSpec) -> dict[str, list[str]]:
    payload = spec.metadata.get("factor_ambiguities_by_category", {})
    result: dict[str, list[str]] = {}
    for category in ("formula", "field_mapping", "evaluation", "other"):
        items = payload.get(category, []) if isinstance(payload, dict) else []
        result[category] = list(items) if isinstance(items, list) else []
    return result


def _manifest_status(plans: list[FactorImplementationPlan]) -> str:
    statuses = {plan.status for plan in plans}
    if "blocked_by_data" in statuses:
        return "blocked_by_data"
    if "needs_human_review" in statuses:
        return "needs_human_review"
    if statuses == {"ready_for_code"}:
        return "ready_for_code"
    if statuses <= {"ready_for_code", "ready_for_code_with_limitations"}:
        return "ready_for_code_with_limitations"
    return "mixed"


def _render_factors_scaffold(manifest: FamilyImplementationManifest, *, constant_name: str, compute_name: str) -> str:
    plan_payload = asdict(manifest)
    return f'''from __future__ import annotations

from typing import Any

import pandas as pd

# Stage 4A scaffold generated from paper-derived FactorResearchSpec records.
# AI-designed helper functions are intentionally listed in IMPLEMENTATION_MANIFEST
# instead of silently invented here. Fill implementations only after formula review.
IMPLEMENTATION_MANIFEST: dict[str, Any] = {plan_payload!r}
{constant_name}: tuple[str, ...] = ()


def {compute_name}(panel: pd.DataFrame, factor_names: list[str] | None = None) -> pd.DataFrame:
    requested = factor_names or [item["factor_name"] for item in IMPLEMENTATION_MANIFEST["factors"]]
    raise NotImplementedError(
        "Paper-derived factor code has not been implemented yet. "
        f"Requested factors: {{requested}}. Review IMPLEMENTATION_MANIFEST first."
    )
'''


def _render_tests_scaffold(manifest: FamilyImplementationManifest, *, constant_name: str, compute_name: str) -> str:
    class_name = "GeneratedPaperFactorScaffoldTest"
    return f'''from __future__ import annotations

import unittest

from .factors import {constant_name}, {compute_name}


class {class_name}(unittest.TestCase):
    def test_scaffold_imports_and_is_intentionally_unimplemented(self) -> None:
        self.assertEqual({constant_name}, ())
        with self.assertRaises(NotImplementedError):
            {compute_name}(None)


if __name__ == "__main__":
    unittest.main()
'''


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")
