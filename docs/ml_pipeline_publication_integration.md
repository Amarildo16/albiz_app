# ML pipeline publication integration (Phase 2B1)

## Scope

Phase 2B1 connects the existing dataset, analysis, and benchmark producers to
the Phase 2A atomic-publication API without changing the frozen v1 artifacts or
the active Django consumer path.

This phase does **not** endorse or change the current academic methodology. It
does not alter features, labels, `performance_score`, models, cross-validation,
PCA, clustering, anomaly detection, feature importance, financial calculations,
filenames, CSV headers, or JSON structures. No real ML run was executed and no
generated result was regenerated.

## Final Phase 2B1 file inventory

The final Phase 2B1 change set contains ten files.

Modified production files:

- `analytics/services/ml_features.py`;
- `analytics/services/ml_analysis.py`;
- `analytics/services/ml_benchmark.py`;
- `analytics/management/commands/build_ml_dataset.py`;
- `analytics/management/commands/run_ml_analysis.py`;
- `analytics/management/commands/run_ml_benchmark.py`.

New files:

- `analytics/services/ml_pipeline_runner.py`;
- `analytics/management/commands/publish_ml_pipeline.py`;
- `analytics/test_ml_pipeline_runner.py`;
- `docs/ml_pipeline_publication_integration.md`.

`analytics/services/ml_runner.py` and
`analytics/services/ml_benchmark_runner.py` were audited but are unchanged from
`HEAD`. They remain legacy flat-layout web runners.

## Existing and explicit producer paths

The legacy commands still use `BASE_DIR/reports/ml` when no path option is
provided:

```text
manage.py build_ml_dataset
manage.py run_ml_analysis
manage.py run_ml_benchmark
```

Their service boundaries now also support isolated directories:

- `write_ml_dataset_artifacts(output_dir=None)` writes the eight dataset-group
  artifacts. `None` retains the legacy flat destination.
- `run_ml_analysis(output_dir, *, input_dir=None)` reads dataset inputs from
  `input_dir` and writes the analysis-group artifacts selected by the 21
  contracts to `output_dir` (19 always, plus two conditional financial CSVs).
  Omitting `input_dir` preserves the former one-directory call.
- `run_ml_benchmark(output_dir, *, input_dir=None)` has the same compatibility
  rule and writes the six benchmark-group artifacts.

The existing commands accept optional `--input-dir` and/or `--output-dir`
arguments as appropriate. Input directories must already exist. A safe missing
output directory is created only when the producer is invoked. A file supplied
where a directory is expected, symlink roots, junctions, Windows reparse
points, and unsafe path components are rejected before producer output is
written. Existing safe directories remain supported.

The dataset service owns dataset serialization now; the management command
delegates to it. This gives the CLI and the complete orchestrator one producer
implementation and prevents schema drift between two writers.

## Complete pipeline order and workspace

`analytics.services.ml_pipeline_runner.run_complete_ml_pipeline()` requires an
explicit publication root. It performs this sequence:

1. validate or generate the run ID;
2. acquire the Phase 2A `PublicationLock` for the supplied root;
3. reject an already archived exact or case-colliding run ID before workspace
   creation or producer computation;
4. create one temporary producer workspace directly under that root;
5. run dataset generation into the workspace;
6. verify the dataset group;
7. run analysis with the workspace as both input and output;
8. verify the analysis group and earlier dataset files;
9. run the benchmark with the same input/output workspace;
10. verify the benchmark group and the complete frozen-v1 contract;
11. call `publish_ml_run()` with the exact combined frozen-v1 selection and the
    already-held lock;
12. remove the producer workspace before releasing the outer lock.

The duplicate-ID preflight is a computation-saving check performed while the
shared lock is held. The Phase 2A publisher retains its authoritative duplicate
check immediately before staging, so the preflight is not presented as a
general defense against non-cooperating filesystem mutation.

The pipeline never copies its workspace into the legacy flat `reports/ml`
directory. The legacy directory, and descendants of it, are rejected as a
versioned publication root.

## Producer dependency injection

Production defaults lazily import and call the three existing producer services.
Tests may instead supply three narrow callables. Each callable receives the
same absolute workspace and returns the artifact paths it created. This permits
contract-valid synthetic tests without database access or ML training and does
not introduce a generalized producer/plugin framework.

Reported paths must be direct workspace children in the frozen-v1 allowlist.
The orchestrator detects a reported path outside the workspace. It cannot
portably prevent an arbitrary or malicious callable from writing an unreported
external file; production producers are trusted in-process code. Process-level
sandboxing is outside Phase 2B1.

## Producer-group verification

The frozen Phase 1 registry remains the source of filenames and ownership:

- dataset selection: 8 contracts;
- analysis selection: 21 contracts;
- benchmark selection: 6 contracts;
- combined selection: 35 contracts.

After each stage the orchestrator:

- scans only direct workspace entries;
- rejects unexpected, out-of-order, non-regular, symlink, junction, reparse, and
  hard-linked entries;
- hashes every file and records its byte size and filesystem identity;
- rejects removal or replacement of an earlier producer's artifacts;
- compares the producer's reported paths with files actually added;
- verifies required artifacts for that producer;
- applies the frozen-v1 JSON, CSV-header, and Markdown checks for that group.

The final workspace must represent the exact 35-contract combined selection.
The two conditional financial analysis CSVs are present only when
`ml_financial_subset_metrics.json` truthfully records `ran: true`. Therefore a
valid physical run contains 35 artifacts when the experiment ran or 33 when it
did not. A conditional CSV present while the experiment is inactive is rejected
as stale; a required active CSV that is absent is also rejected.

Hash comparisons detect normal producer overwrites and mutation during
verification. As with any path-based in-process workflow, a hostile producer
could attempt races between checks; producer code is part of the trusted local
application boundary.

The isolated orchestrator always starts with an empty private workspace. The
standalone path overrides can also target an existing directory for backward
compatibility. Callers must treat that directory as trusted: the legacy writers
do not provide a portable descriptor-relative/no-follow guarantee for every
pre-existing artifact leaf, so a hostile process racing or pre-populating that
directory remains outside the supported threat model.

## Shared lock and publication policy

One outer `PublicationLock` covers workspace creation, all producers, all stage
checks, final validation, nested `publish_ml_run()`, and controlled workspace
cleanup. Phase 2A's same-owner nested lease is used; no second operating-system
lock is established for publication.

The older web/standalone locks remain unchanged for backward compatibility.
The analysis web runner still calls `build_ml_dataset` followed by
`run_ml_analysis`, and the benchmark web runner still calls
`run_ml_benchmark`; all are invoked without directory options and therefore use
the flat `reports/ml` directory. Their lock names, status dictionaries, error
handling, and command-output capture are unchanged. They do not invoke
versioned publication and are not the primary lock for the complete versioned
operation.

The orchestrator always supplies the exact combined frozen-v1 artifact
selection. Under the mandatory Phase 2A policy this means:

- complete valid combined runs are archived and may atomically update
  `current.json`;
- partial dataset, analysis, or benchmark selections cannot become global
  current;
- the complete orchestrator does not expose a partial-activation override;
- rollback eligibility remains governed by Phase 2A and is unchanged here.

## Failure and cleanup guarantees

If a producer raises, omits an artifact, emits an invalid structure, writes an
unexpected workspace entry, or changes an earlier producer's output, publication
is not called. The temporary workspace is removed under the shared lock and the
previous `current.json` and archived runs remain unchanged.

If staged publication fails, Phase 2A preserves the prior pointer and cleans its
publication staging directory. The Phase 2B1 producer workspace is then cleaned
as part of the outer controlled failure path.

If publication succeeds but producer-workspace cleanup itself fails, the valid
archived/activated run is not deleted or rolled back. The caller receives a
domain error explaining that publication succeeded but cleanup failed. This is
safer than deleting a successfully published run.

The atomic visibility and crash-durability limits documented in
`docs/ml_atomic_publication_design.md` still apply. Phase 2B1 does not add
signing, authenticity, remote-filesystem guarantees, or process sandboxing.

## Provenance

The orchestrator supplies only metadata it can state truthfully:

- the dataset, analysis, and benchmark service stages executed;
- Python version through `PublicationMetadata`;
- dataset and feature-schema SHA-256 values calculated from the verified
  workspace;
- existing analysis/benchmark random-state metadata when production defaults
  are used;
- code revision and dirty state only when explicitly supplied;
- caller-supplied library versions and source-snapshot metadata when available.

No Git command is required or invoked. No label-definition version is invented;
it remains absent unless a truthful existing version is explicitly supplied.

## Frozen-v1 path-value limitation

Exactly two frozen-v1 JSON artifacts record producer output paths:

- `ml_analysis_summary.json.output_files` records 21 paths, including both
  conditional financial CSV paths even when `ran` is false and those files are
  absent;
- `ml_benchmark_summary.json.output_files` records six paths.

No other current v1 JSON artifact and neither generated Markdown artifact
records these paths. In an isolated run the values refer to the temporary
producer workspace, which is intentionally deleted after publication. The
archived artifact bytes, their hashes, structural validation, future rollback,
and the publication manifest remain valid; the legacy strings are informational
only and are not durable locations. Current Django consumers do not use them to
find sibling artifacts, and future consumers must not do so.

Phase 2B1 leaves those values unchanged because changing current JSON content is
explicitly out of scope. A later versioned-contract phase should replace them
with run-relative references before consumers rely on them. The publication
manifest already provides durable relative artifact paths for infrastructure
use. Frozen-v1 artifacts are therefore not fully location-independent.

## Complete-publication management command

The CLI-only entry point is:

```text
manage.py publish_ml_pipeline --publication-root <path>
```

Optional arguments are `--run-id`, `--code-revision`, `--dirty-state` (`clean`,
`dirty`, or `unknown`), and `--lock-timeout`. The command invokes only the
orchestration service. On success it reports the run ID, archive path, manifest
path, and activation state. Domain and path failures are converted to a Django
`CommandError` while preserving exception chaining.

This command was not executed during Phase 2B1.

## Legacy compatibility and later work

Django pages, exports, URLs, templates, `ML_OUTPUT_FILES`, `ML_CSV_EXPORTS`, and
browser-triggered behavior continue to read and generate the flat
`reports/ml` layout. No compatibility symlink is created. The existing producer
commands keep their no-option behavior and output schemas.

Migration of Django consumers from the flat directory to versioned
`current.json` runs belongs to a later phase. Academic-methodology corrections
also belong to later phases.
