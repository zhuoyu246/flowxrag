# Manuscript Blueprints

Use the closest blueprint and adapt it to the target venue template.

## Title

Strong CS titles usually combine object, mechanism, and outcome:

- Mechanism for task/context: "Adaptive Retrieval Calibration for Reliable Domain Question Answering"
- System name plus purpose: "NexusRAG: A Retrieval-Augmented System for Enterprise Learning Analytics"
- Empirical finding: "How Data Leakage Shapes Reported Performance in Student Risk Prediction"

Avoid unexplained acronyms, hype, and overly broad claims.

## Abstract

Use six moves in one compact paragraph unless the venue requires structure:

1. Context and problem.
2. Specific gap in existing work.
3. Proposed method or system.
4. Evaluation setting.
5. Key quantitative or qualitative results.
6. Implication and contribution.

Do not include citations in most CS abstracts unless venue norms permit them. Avoid unsupported numbers.

## Introduction

Recommended paragraph roles:

1. Motivate the problem with a concrete technical or domain need.
2. Explain why existing approaches are insufficient.
3. Identify the precise gap or challenge.
4. Present the proposed idea and intuition.
5. Summarize evaluation and key results.
6. List contributions.

Contribution bullets should be concrete:

- "We design..." for method or system artifacts.
- "We construct..." for dataset or benchmark artifacts.
- "We demonstrate..." for evidence.
- "We release..." for reproducibility artifacts.

## Related Work

Organize by research threads, not by paper-by-paper summaries. Each subsection should end with positioning:

- What the thread solves.
- What limitation remains.
- How the manuscript differs.

Use a comparison table when methods differ by data, model, assumptions, supervision, deployment setting, or evaluation metrics.

## Method

Minimum method content:

- Problem formulation with notation.
- Overall architecture or pipeline.
- Component details and rationale.
- Algorithm or pseudo-code when the procedure is nontrivial.
- Complexity, parameter count, runtime, or storage cost when relevant.
- Implementation details needed for reproducibility.

For equations, define every symbol near first use.

## Experiments

Recommended structure:

1. Research questions.
2. Datasets and preprocessing.
3. Baselines.
4. Metrics.
5. Implementation details.
6. Main results.
7. Ablation study.
8. Sensitivity or robustness.
9. Error analysis or case study.
10. Efficiency or scalability when relevant.

Each results subsection should follow: setup, observation, explanation, implication.

## Discussion

Use discussion for interpretation, boundary conditions, deployment implications, or tradeoffs. Do not repeat the results table in prose.

## Threats To Validity

For CS empirical and applied work, use:

- Internal validity: confounders, leakage, implementation errors, parameter search.
- External validity: dataset, domain, scale, user population, hardware.
- Construct validity: metrics, labels, proxy variables, measurement quality.
- Conclusion validity: statistical power, variance, multiple testing, effect interpretation.

## Conclusion

Restate the problem, method, and evidence in reduced form. Avoid introducing new claims. End with a grounded future direction only if it follows from limitations.
