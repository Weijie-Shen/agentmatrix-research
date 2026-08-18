# Neutralization method catalog

`neutralize.cross_sectional_regression_residual` executes a cross-sectional regression by signal date and outputs residual factor exposure. Declare controls in order with `semantic_input`, encoding (`continuous` or `categorical`), and their own ordered transforms.

Multiple neutralizations are multiple top-level recipe steps. Preserve sequential industry then style neutralization as two steps; do not merge it into one regression. Industry requirements retain provider, taxonomy version, level, and effective-date rule. Capitalization retains basis and a separate log/sqrt/winsor/z-score transform.

Runtime default for a missing control is complete-case regression; rows lacking any required control receive missing residuals. A paper-local unknown neutralization uses `custom.paper_defined`.
