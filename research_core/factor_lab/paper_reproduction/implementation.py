from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import keyword
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

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
class FactorImplementationArtifact:
    """Identity and executable contract for the final factor implementation."""

    module_path: str
    callable_import_path: str
    implemented_factor_ids: list[str]
    factor_specification_hash: str
    source_hash: str
    required_input_columns: list[str]
    output_key_columns: list[str]
    output_factor_columns: list[str]
    factor_columns_by_id: dict[str, str] = field(default_factory=dict)
    validation_status: str = "not_assessed"
    validation_evidence: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "factor_implementation_artifact/v1"


@dataclass(slots=True)
class FactorImplementationValidationResult:
    valid: bool
    execution_status: str
    errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class FactorImplementationValidationError(ValueError):
    """Raised when a declared factor implementation cannot be certified."""

    def __init__(self, result: FactorImplementationValidationResult):
        self.result = result
        super().__init__("; ".join(result.errors) or "factor implementation validation failed")


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


def build_factor_implementation_artifact(
    specs: list[FactorResearchSpec],
    *,
    module_path: str | Path,
    callable_import_path: str,
    probe_panel: pd.DataFrame,
    output_key_columns: list[str] | None = None,
    output_factor_columns: list[str] | None = None,
    factor_columns_by_id: dict[str, str] | None = None,
) -> FactorImplementationArtifact:
    """Build and certify the canonical executable artifact for a factor family."""

    if not specs:
        raise ValueError("At least one FactorResearchSpec is required to build an implementation artifact.")
    path = Path(module_path).expanduser().resolve()
    key_columns = list(output_key_columns or ["date", "code"])
    factor_ids = [_spec_factor_id(spec) for spec in specs]
    columns_by_id = dict(factor_columns_by_id or {})
    if not columns_by_id:
        columns_by_id = {_spec_factor_id(spec): spec.factor_name for spec in specs}
    factor_columns = list(output_factor_columns or [columns_by_id[factor_id] for factor_id in factor_ids])
    artifact = FactorImplementationArtifact(
        module_path=str(path),
        callable_import_path=callable_import_path,
        implemented_factor_ids=factor_ids,
        factor_specification_hash=factor_specification_hash(specs),
        source_hash=_file_sha256(path),
        required_input_columns=_required_input_columns(specs, key_columns=key_columns),
        output_key_columns=key_columns,
        output_factor_columns=factor_columns,
        factor_columns_by_id=columns_by_id,
    )
    validation = validate_factor_implementation_artifact(artifact, probe_panel=probe_panel, specs=specs)
    if not validation.valid:
        raise FactorImplementationValidationError(validation)
    artifact.validation_status = validation.execution_status
    artifact.validation_evidence = {
        "errors": list(validation.errors),
        "limitations": list(validation.limitations),
        "diagnostics": dict(validation.diagnostics),
    }
    return artifact


def validate_factor_implementation_artifact(
    artifact: FactorImplementationArtifact,
    *,
    probe_panel: pd.DataFrame,
    specs: list[FactorResearchSpec] | None = None,
) -> FactorImplementationValidationResult:
    """Import and probe an artifact without claiming mathematical factor correctness."""

    errors: list[str] = []
    limitations: list[str] = []
    diagnostics: dict[str, Any] = {
        "schema_version": artifact.schema_version,
        "callable_import_path": artifact.callable_import_path,
    }
    path = Path(artifact.module_path)
    if not path.is_file():
        errors.append(f"implementation module does not exist: {path}")
        return FactorImplementationValidationResult(False, "failed", errors, limitations, diagnostics)

    actual_source_hash = _file_sha256(path)
    diagnostics["actual_source_hash"] = actual_source_hash
    if actual_source_hash != artifact.source_hash:
        errors.append("implementation source hash does not match the declared artifact")
    if specs is not None:
        actual_spec_hash = factor_specification_hash(specs)
        diagnostics["actual_factor_specification_hash"] = actual_spec_hash
        if actual_spec_hash != artifact.factor_specification_hash:
            errors.append("factor specification hash does not match the declared artifact")

    duplicated_factor_ids = _duplicates(artifact.implemented_factor_ids)
    duplicated_output_columns = _duplicates(artifact.output_factor_columns)
    if duplicated_factor_ids:
        errors.append(f"implemented_factor_ids contains duplicates: {duplicated_factor_ids}")
    if duplicated_output_columns:
        errors.append(f"output_factor_columns contains duplicates: {duplicated_output_columns}")
    missing_mappings = [factor_id for factor_id in artifact.implemented_factor_ids if factor_id not in artifact.factor_columns_by_id]
    if missing_mappings:
        errors.append(f"factor_columns_by_id is missing declared factors: {missing_mappings}")
    unexpected_mappings = sorted(set(artifact.factor_columns_by_id) - set(artifact.implemented_factor_ids))
    if unexpected_mappings:
        errors.append(f"factor_columns_by_id contains undeclared factors: {unexpected_mappings}")
    mapped_columns = set(artifact.factor_columns_by_id.values())
    if mapped_columns != set(artifact.output_factor_columns):
        errors.append("factor_columns_by_id values must exactly match output_factor_columns")

    missing_probe_columns = [column for column in artifact.required_input_columns if column not in probe_panel.columns]
    if missing_probe_columns:
        errors.append(f"probe panel is missing required input columns: {missing_probe_columns}")
    missing_probe_keys = [column for column in artifact.output_key_columns if column not in probe_panel.columns]
    if missing_probe_keys:
        errors.append(f"probe panel is missing output key columns: {missing_probe_keys}")
    if errors:
        return FactorImplementationValidationResult(False, "failed", errors, limitations, diagnostics)

    try:
        output = execute_factor_callable(artifact, probe_panel)
    except NotImplementedError:
        errors.append("declared factor callable is still an unimplemented scaffold")
        return FactorImplementationValidationResult(False, "failed", errors, limitations, diagnostics)
    except Exception as exc:  # probe failures are returned as structured validation evidence
        errors.append(f"declared factor callable failed on the probe panel: {type(exc).__name__}: {exc}")
        return FactorImplementationValidationResult(False, "failed", errors, limitations, diagnostics)

    if not isinstance(output, pd.DataFrame):
        errors.append(f"declared factor callable returned {type(output).__name__}, expected pandas.DataFrame")
        return FactorImplementationValidationResult(False, "failed", errors, limitations, diagnostics)

    diagnostics["probe_input_rows"] = len(probe_panel)
    diagnostics["probe_output_rows"] = len(output)
    diagnostics["probe_output_columns"] = list(output.columns)
    expected_columns = [*artifact.output_key_columns, *artifact.output_factor_columns]
    missing_output_columns = [column for column in expected_columns if column not in output.columns]
    unexpected_output_columns = [column for column in output.columns if column not in expected_columns]
    if missing_output_columns:
        errors.append(f"factor output is missing declared columns: {missing_output_columns}")
    if unexpected_output_columns:
        errors.append(f"factor output contains undeclared columns: {unexpected_output_columns}")
    if all(column in output.columns for column in artifact.output_key_columns):
        null_key_rows = int(output[artifact.output_key_columns].isna().any(axis=1).sum())
        duplicate_key_rows = int(output.duplicated(artifact.output_key_columns, keep=False).sum())
        diagnostics["probe_null_key_rows"] = null_key_rows
        diagnostics["probe_duplicate_key_rows"] = duplicate_key_rows
        if null_key_rows:
            errors.append(f"factor output contains {null_key_rows} rows with null keys")
        if duplicate_key_rows:
            errors.append(f"factor output contains {duplicate_key_rows} rows with duplicate keys")
    for column in artifact.output_factor_columns:
        if column in output.columns and not pd.api.types.is_numeric_dtype(output[column]):
            errors.append(f"factor output column is not numeric: {column}")

    if not errors and all(column in output.columns for column in artifact.output_key_columns):
        input_keys = _normalized_key_frame(probe_panel, artifact.output_key_columns)
        output_keys = _normalized_key_frame(output, artifact.output_key_columns)
        key_check = input_keys.merge(output_keys, on=artifact.output_key_columns, how="outer", indicator=True)
        left_only = int((key_check["_merge"] == "left_only").sum())
        right_only = int((key_check["_merge"] == "right_only").sum())
        diagnostics["probe_left_only_keys"] = left_only
        diagnostics["probe_right_only_keys"] = right_only
        if left_only or right_only:
            limitations.append(
                f"probe key coverage is incomplete: input-only={left_only}, output-only={right_only}"
            )

    return FactorImplementationValidationResult(
        valid=not errors,
        execution_status="completed_with_limitations" if limitations and not errors else ("completed" if not errors else "failed"),
        errors=errors,
        limitations=limitations,
        diagnostics=diagnostics,
    )


def execute_factor_callable(
    artifact: FactorImplementationArtifact,
    panel: pd.DataFrame,
    *,
    copy_input: bool = True,
) -> pd.DataFrame:
    """Execute only the callable declared by the canonical implementation artifact."""

    current_hash = _file_sha256(Path(artifact.module_path))
    if current_hash != artifact.source_hash:
        raise ValueError("implementation source changed after the artifact was created")
    callable_object = _load_declared_callable(artifact)
    signature = inspect.signature(callable_object)
    kwargs: dict[str, Any] = {}
    if "factor_names" in signature.parameters:
        kwargs["factor_names"] = list(artifact.output_factor_columns)
    callable_input = panel.copy() if copy_input else panel
    output = callable_object(callable_input, **kwargs)
    if not isinstance(output, pd.DataFrame):
        raise TypeError(f"declared factor callable returned {type(output).__name__}, expected pandas.DataFrame")
    return output


def export_factor_implementation_artifact(
    artifact: FactorImplementationArtifact,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(artifact), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_factor_implementation_artifact(path: str | Path) -> FactorImplementationArtifact:
    return FactorImplementationArtifact(**json.loads(Path(path).read_text(encoding="utf-8")))


def factor_specification_hash(specs: list[FactorResearchSpec]) -> str:
    """Hash only implementation-relevant fields, excluding notes and report metadata."""

    payload = [
        {
            "factor_id": _spec_factor_id(spec),
            "factor_name": spec.factor_name,
            "formula": spec.formula,
            "required_fields": list(spec.required_fields),
            "parameters": spec.parameters,
            "frequency": spec.frequency,
        }
        for spec in sorted(specs, key=_spec_factor_id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _load_declared_callable(artifact: FactorImplementationArtifact) -> Any:
    module_name, callable_name = _split_callable_import_path(artifact.callable_import_path)
    module: Any
    if module_name:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name and not module_name.startswith(f"{exc.name}."):
                raise
            module = _load_standalone_module(Path(artifact.module_path))
    else:
        module = _load_standalone_module(Path(artifact.module_path))
    target: Any = module
    for part in callable_name.split("."):
        if not hasattr(target, part):
            raise AttributeError(f"declared callable was not found: {artifact.callable_import_path}")
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"declared implementation target is not callable: {artifact.callable_import_path}")
    callable_source = inspect.getsourcefile(target)
    if callable_source is not None and Path(callable_source).resolve() != Path(artifact.module_path).resolve():
        raise ValueError(
            "declared callable resolves to a different source module than module_path: "
            f"{Path(callable_source).resolve()}"
        )
    return target


def _split_callable_import_path(value: str) -> tuple[str, str]:
    text = value.strip()
    if not text:
        raise ValueError("callable_import_path must not be empty")
    if ":" in text:
        module_name, callable_name = text.split(":", 1)
        if not module_name.strip() or not callable_name.strip():
            raise ValueError("callable_import_path must use 'module:callable'")
        return module_name.strip(), callable_name.strip()
    if "." in text:
        module_name, callable_name = text.rsplit(".", 1)
        return module_name, callable_name
    return "", text


def _load_standalone_module(path: Path) -> Any:
    module_name = f"paper_factor_implementation_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load implementation module from {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _required_input_columns(specs: list[FactorResearchSpec], *, key_columns: list[str]) -> list[str]:
    result = list(key_columns)
    for spec in specs:
        for column in spec.required_fields:
            if column not in result:
                result.append(column)
    return result


def _spec_factor_id(spec: FactorResearchSpec) -> str:
    return spec.factor_id.strip() or spec.factor_name


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_key_frame(frame: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    result = frame[key_columns].copy()
    for column in key_columns:
        if column.lower() in {"date", "datetime", "trade_date"}:
            result[column] = pd.to_datetime(result[column], errors="coerce")
        else:
            result[column] = result[column].astype("string")
    return result.drop_duplicates().reset_index(drop=True)


def _duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")
