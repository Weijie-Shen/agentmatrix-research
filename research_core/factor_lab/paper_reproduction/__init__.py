from __future__ import annotations

from research_core.factor_lab.paper_reproduction.agent_harness import (
    PaperReproductionAgentHarnessBundle,
    PaperReproductionAgentHarnessRequest,
    default_skill_path,
    prepare_agent_harness_bundle,
)
from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    DataFrameValidationResult,
    validate_input_frame,
)
from research_core.factor_lab.paper_reproduction.extraction import (
    ExtractedFactor,
    ExtractedTruthSource,
    ExtractionValidationResult,
    PaperExtraction,
    export_paper_extraction,
    load_paper_extraction,
    selected_truth_sources,
    summarize_factor_truth_sources,
    validate_paper_extraction,
)
from research_core.factor_lab.paper_reproduction.evaluators import (
    apply_transform_spec,
    compute_cross_sectional_regression,
    compute_ic_analysis,
    evaluate_paper_case,
)
from research_core.factor_lab.paper_reproduction.implementation import (
    FactorImplementationPlan,
    FamilyImplementationManifest,
    build_implementation_manifest,
    export_implementation_manifest,
    write_factor_family_scaffold,
)
from research_core.factor_lab.paper_reproduction.normalization import (
    normalize_extraction_to_specs,
    write_specs_module,
)
from research_core.factor_lab.paper_reproduction.paper_evaluation import (
    PaperEvaluationPlan,
    PaperFactorEvaluationPlan,
    build_paper_evaluation_plan,
)
from research_core.factor_lab.paper_reproduction.pipeline import (
    PaperReproductionPipelineState,
    PaperReproductionStage,
    PaperReproductionStageState,
    export_pipeline_state,
)
from research_core.factor_lab.paper_reproduction.quant_api import (
    QuantApiConfig,
    normalize_quant_daily_kline_frame,
)
from research_core.factor_lab.paper_reproduction.recommended_data import (
    RecommendedDataConfig,
    add_next_suspension_flag,
    apply_a_share_recommended_filters,
    load_recommended_daily_panel,
    load_recommended_data_manifest,
    normalize_recommended_daily_kline_frame,
    normalize_recommended_industry_frame,
    normalize_recommended_market_cap_frame,
    normalize_recommended_security_status_frame,
    normalize_recommended_symbol,
    recommended_data_available,
)
from research_core.factor_lab.paper_reproduction.reporting import (
    build_paper_reproduction_report,
    export_paper_reproduction_report,
    render_paper_reproduction_report_markdown,
)
from research_core.factor_lab.paper_reproduction.truth_matching import (
    PaperTruthMatchResult,
    compare_evaluation_metrics_to_paper_truth,
)

__all__ = [
    "DataFrameValidationRequest",
    "DataFrameValidationResult",
    "ExtractedFactor",
    "ExtractedTruthSource",
    "ExtractionValidationResult",
    "FactorImplementationPlan",
    "FamilyImplementationManifest",
    "PaperExtraction",
    "PaperEvaluationPlan",
    "PaperFactorEvaluationPlan",
    "PaperReproductionAgentHarnessBundle",
    "PaperReproductionAgentHarnessRequest",
    "PaperReproductionPipelineState",
    "PaperReproductionStage",
    "PaperReproductionStageState",
    "PaperTruthMatchResult",
    "QuantApiConfig",
    "RecommendedDataConfig",
    "add_next_suspension_flag",
    "apply_transform_spec",
    "apply_a_share_recommended_filters",
    "build_implementation_manifest",
    "build_paper_evaluation_plan",
    "build_paper_reproduction_report",
    "compare_evaluation_metrics_to_paper_truth",
    "compute_cross_sectional_regression",
    "compute_ic_analysis",
    "default_skill_path",
    "evaluate_paper_case",
    "export_implementation_manifest",
    "export_pipeline_state",
    "export_paper_extraction",
    "export_paper_reproduction_report",
    "load_paper_extraction",
    "load_recommended_daily_panel",
    "load_recommended_data_manifest",
    "normalize_extraction_to_specs",
    "normalize_quant_daily_kline_frame",
    "normalize_recommended_daily_kline_frame",
    "normalize_recommended_industry_frame",
    "normalize_recommended_market_cap_frame",
    "normalize_recommended_security_status_frame",
    "normalize_recommended_symbol",
    "prepare_agent_harness_bundle",
    "recommended_data_available",
    "render_paper_reproduction_report_markdown",
    "selected_truth_sources",
    "summarize_factor_truth_sources",
    "validate_paper_extraction",
    "validate_input_frame",
    "write_factor_family_scaffold",
    "write_specs_module",
]
