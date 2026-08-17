# Revision And Review

Use this reference for reviewer response, rebuttal, or pre-submission review.

## Pre-Submission Review Output

When acting as reviewer, produce:

1. Overall recommendation risk: accept-leaning, major revision, weak reject, or strong reject risk.
2. Decision-critical issues first.
3. Required experiments or analyses.
4. Writing and organization fixes.
5. Citation and positioning gaps.
6. A prioritized revision plan.

Do not bury fatal issues under language polishing.

## Response Matrix

Use this table for revision planning:

| Reviewer | Concern | Severity | Manuscript change | Location | Response strategy |
| --- | --- | --- | --- | --- | --- |
| R1 | Baseline missing | High | Add comparison with X | Sec. 4.3, Table 2 | Agree, add evidence, explain impact |

Severity:

- High: affects validity, novelty, or acceptance.
- Medium: affects clarity, completeness, or reproducibility.
- Low: wording, formatting, minor citation, small clarification.

## Response Principles

- Thank the reviewer briefly.
- State the action taken.
- Point to exact manuscript location.
- Explain evidence, not intention.
- If disagreeing, be respectful and provide technical rationale plus a manuscript clarification.
- Avoid emotional language, overpromising, or claiming the reviewer misunderstood without revising the paper.

## Response Template

Reviewer comment:
`<quote or paraphrase the concern>`

Response:
`Thank you for this helpful suggestion. We have revised <section/table/figure> to <specific action>. The revised manuscript now <states evidence or clarification>. Specifically, <short technical detail>.`

Manuscript change:
`Section X, Page Y, Lines Z-Z: <what changed>`

## Common Review Issues And Fixes

### Weak Novelty

Fix by adding closest-work comparison, clarifying the technical delta, and tying the delta to evidence. Do not solve weak novelty with stronger adjectives.

### Missing Baseline

Fix by adding the baseline or explaining why it is inapplicable. If not feasible, add a limitation and compare conceptually with evidence.

### Unclear Method

Fix with a pipeline figure, notation table, algorithm block, component rationale, and implementation details.

### Inadequate Experiments

Fix by mapping each claim to an experiment. Add ablation, robustness, sensitivity, efficiency, statistical test, or case study depending on the unsupported claim.

### Overclaiming

Fix by narrowing scope, adding boundary conditions, or downgrading language from universal to observed.

### Reproducibility Concern

Fix with artifact statement, environment details, seed and parameter settings, data processing steps, and pseudo-code.

## Final Revision Checklist

- Every reviewer concern has a visible manuscript change or a justified no-change response.
- New experiments are integrated into abstract, results, discussion, and conclusion where necessary.
- Line/page references are updated after formatting.
- Responses and manuscript use consistent terminology.
- No response depends on data or citations that are absent from the manuscript.
