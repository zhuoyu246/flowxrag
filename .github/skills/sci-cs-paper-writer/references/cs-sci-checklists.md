# CS SCI Checklists

Use these checklists when planning, drafting, reviewing, or revising computer-science journal manuscripts.

## Novelty And Contribution

- State the technical gap as a missing capability, missing evidence, or unresolved tradeoff.
- Compare against the closest methods, not only broad categories.
- Avoid claiming "first" unless verified by a current literature search.
- Define each contribution as one of: method, system, dataset, benchmark, theory, empirical finding, tool, or taxonomy.
- Make every contribution traceable to a section, figure, table, theorem, algorithm, or artifact.

## Experiment Design

- Match each research question to datasets, baselines, metrics, and expected evidence.
- Use representative public datasets when possible; justify private or synthetic data.
- Include data split strategy, leakage prevention, preprocessing, hardware, software, random seeds, and hyperparameter selection.
- Compare with strong recent baselines and simple classical baselines when appropriate.
- Report uncertainty when results vary: repeated runs, confidence intervals, statistical tests, or effect sizes.
- Include negative or boundary results when they clarify applicability.

## AI And Data Mining Papers

- Check train, validation, test separation.
- Report architecture or model family, objective function, optimizer, learning rate, batch size, epochs, early stopping, seed count, and compute.
- Include ablations for major modules, loss terms, features, prompts, retrieval components, or augmentation steps.
- Include sensitivity analysis for key hyperparameters.
- Include error analysis: failure categories, difficult cases, bias, and domain shift.
- For LLM or RAG work, document model versions, retrieval index, chunking, embedding model, reranking, context length, prompts, evaluation protocol, and hallucination controls.

## Software Engineering Papers

- Convert broad goals into research questions.
- Describe data sources, mining pipeline, inclusion and exclusion criteria, annotation protocol, inter-rater agreement, and cleaning steps.
- Use appropriate statistical tests and correct for multiple comparisons when needed.
- Separate correlation from causation.
- Include internal, external, construct, and conclusion validity threats.

## Systems And Networks Papers

- Explain workload realism, deployment conditions, hardware, network topology, implementation details, and failure assumptions.
- Evaluate latency, throughput, scalability, resource use, reliability, overhead, cost, and tail behavior as relevant.
- Include stress tests and comparison against production-relevant baselines.
- Discuss operational limits and failure modes.

## Security Papers

- Define threat model, attacker knowledge, attacker capability, and security goals.
- Distinguish attack success, detection, robustness, false positives, and usability impact.
- Include adaptive or transfer attacks when claiming robustness.
- Address ethics, disclosure, and data handling.

## Reproducibility

Minimum reproducibility items:

- Code or pseudo-code availability statement.
- Dataset source, license, and preprocessing details.
- Environment: OS, language/runtime, library versions, hardware.
- Parameters and random seeds.
- Exact evaluation protocol.
- Artifact structure or replication steps.

If artifacts cannot be shared, state why and provide a practical substitute: synthetic data, scripts, pseudo-code, or detailed configuration.

## Reviewer Red Flags

- Main claim is stronger than experiments.
- Only weak or outdated baselines are used.
- Result improvements are small without significance or practical interpretation.
- Datasets are narrow but conclusions are broad.
- Method description cannot be reimplemented.
- Related work is a list instead of a positioning argument.
- Threats to validity are absent or generic.
- The abstract promises a system, but experiments only test a component.
- Citations are missing for established concepts or benchmark choices.
