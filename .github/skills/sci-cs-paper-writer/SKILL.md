---
name: sci-cs-paper-writer
description: Specialized workflow for planning, drafting, polishing, and revising computer-science SCI or journal manuscripts. Use when Codex is asked to write, rewrite, outline, review, translate, polish, submit, or respond to reviewers for CS papers in AI, software engineering, systems, networks, databases, security, HCI, data mining, or learning analytics, especially when journal fit, novelty, experiments, baselines, ablations, reproducibility, citation integrity, or reviewer response quality matters.
---

# SCI CS Paper Writer

## Operating Mode

Treat the manuscript as a scientific argument, not a writing exercise. Build every section from a claim map:

1. Problem: what technical bottleneck or knowledge gap exists.
2. Method: what concrete algorithm, architecture, system, dataset, model, framework, theorem, or pipeline addresses it.
3. Evidence: what experiments, proofs, analyses, benchmarks, or case studies support the claims.
4. Boundary: what assumptions, limitations, threats to validity, ethics, and reproducibility constraints remain.
5. Venue fit: what journal or conference audience would accept the contribution.

Default to English manuscript text and concise Chinese process notes when the user writes in Chinese. Do not invent citations, venues, impact factors, policies, baselines, datasets, metrics, or numerical results. Browse or ask for sources when current literature, journal rules, or exact citations are needed.

## Quick Triage

Classify the user request before acting:

- **Idea to paper**: create contribution framing, title, abstract, outline, experiment plan, and target venues.
- **Drafting**: write sections in journal style from supplied notes, results, tables, figures, or code.
- **Polishing**: improve logic, concision, technical precision, and academic tone without changing facts.
- **Reviewing**: act as a strict CS journal reviewer and produce reject risks plus fixes.
- **Revision**: build response-to-reviewers tables, rebuttal text, and manuscript change plans.
- **LaTeX or template work**: preserve labels, equations, citations, cross-references, and package style.

For broad requests, produce the minimum useful first artifact plus a clear gap list. For manuscript writing, prefer this output order: diagnosis, revised text, evidence gaps, next edits.

## Core Workflow

### 1. Intake

Extract or request only missing essentials:

- Target venue or tier: SCI journal, IEEE/ACM/Elsevier/Springer journal, CCF conference, or "undecided".
- Field and paper type: algorithm, empirical study, system, benchmark, survey, application, theory, dataset, or tool.
- Assets: abstract, notes, related work, result tables, figures, code, dataset description, BibTeX, journal template.
- Hard constraints: word limit, section format, reference style, language, deadline, ethics restrictions.

If the user supplies files, inspect them before drafting. If the project contains a paper folder, check it for manuscript, figures, tables, bibliography, and logs.

### 2. Build The Claim Map

Before writing new technical content, make an explicit claim map:

| Claim | Evidence | Manuscript location | Risk |
| --- | --- | --- | --- |
| Main contribution | Result/table/source | Abstract/Intro/Conclusion | Missing baseline, weak novelty, unsupported number |

Every strong claim must have evidence. Downgrade unsupported claims instead of decorating them.

### 3. Pick A CS Paper Shape

Use the closest blueprint:

- **Algorithm/model paper**: problem formulation, method, complexity, implementation, datasets, baselines, metrics, ablation, sensitivity, error analysis.
- **System paper**: requirements, architecture, implementation, deployment, workload, performance, reliability, cost, scalability, failure modes.
- **Empirical software engineering paper**: research questions, data collection, coding protocol, statistical tests, validity threats, replication package.
- **Security paper**: threat model, adversary capabilities, attack or defense design, evaluation, false positives, robustness, responsible disclosure.
- **Data mining/AI application paper**: domain problem, dataset, features, model, baselines, interpretability, generalization, leakage checks.
- **Survey paper**: search protocol, inclusion/exclusion criteria, taxonomy, synthesis, open problems, reproducibility of literature search.

Read `references/manuscript-blueprints.md` when a section-level plan or template is needed.

### 4. Draft With Evidence Discipline

Write in precise technical prose:

- Prefer "we propose", "we evaluate", "results show" only when the evidence exists.
- State contributions as measurable or inspectable artifacts, not slogans.
- Put numbers near their experimental context: dataset, metric, baseline, condition, statistical status.
- Explain why each baseline, metric, ablation, and dataset was chosen.
- Include limitations and threats before reviewers have to infer them.
- Keep the abstract structured: problem, gap, method, evidence, result, significance.

For CS-specific experiment, reproducibility, and reviewer-risk checks, read `references/cs-sci-checklists.md`.

### 5. Polish For SCI Journal Style

Improve clarity without inflating claims:

- Replace vague adjectives with technical mechanisms or measured effects.
- Make topic sentences carry the logical role of each paragraph.
- Remove filler, hype, duplicate transitions, and AI-like over-signposting.
- Keep terminology stable across title, abstract, keywords, method, experiments, and conclusion.
- Preserve equations, citations, labels, tables, and figure references.

When translating Chinese to English, translate meaning and argument structure, not sentence order. Use natural CS journal English.

### 6. Review And Revision

When asked to review, be strict. Lead with decision-critical issues:

- novelty and positioning,
- method soundness,
- baseline fairness,
- dataset validity and leakage,
- metric choice,
- ablation and sensitivity,
- statistical rigor,
- reproducibility,
- threats to validity,
- ethics and data governance,
- writing and organization.

When responding to reviewers, read `references/revision-and-review.md`. Build a response matrix with reviewer concern, manuscript change, exact location, and response text. Never argue from authority; respond with evidence, edits, and respectful precision.

## Useful Local Skills

If installed, use these local skills as supporting material:

- `$academic-research-suite` for full research pipeline management, literature review, and structured academic workflows.
- `$cs-academic-writing` for CS academic phrasing and section-level writing patterns.

This skill remains the decision layer for SCI computer-science manuscripts: claim control, experiment rigor, reviewer risk, and venue fit.

## Quality Gate

Before finalizing any manuscript-facing output, run this quick gate:

1. Are all citations and facts sourced or explicitly marked as user-provided?
2. Are numerical claims tied to a table, figure, experiment, or source?
3. Does the contribution differ from related work in a concrete technical way?
4. Are baselines and metrics credible for the subfield?
5. Are limitations and threats to validity visible?
6. Would a reviewer understand why the result matters for the target venue?

If any answer is no, surface the gap instead of hiding it.
