# Global evaluation policy

Every v3 recipe references `china_a_share_ic_evaluation_v1`. This is project policy, not paper evidence.

After full-history factor calculation and factor/evaluation-input alignment, but before the truth-source recipe:

1. exclude ST/PT securities at signal date `t`;
2. exclude securities suspended on the next exchange trading day `t+1`;
3. exclude a row when either status is missing.

The policy never filters rolling factor history. It applies even when the paper omits or contradicts it; record that difference as a project-policy deviation.

Global non-factor missing defaults are: complete-case neutralization controls with missing output residuals, pairwise missing-return removal at IC, exclusion for missing eligibility status, and execution blocking for invalid security/date keys.
