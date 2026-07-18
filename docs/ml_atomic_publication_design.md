# ML atomic publication design (Phase 2A)

## Purpose and scope

The current v1 ML outputs are a group of related files. Updating those files one
at a time can expose a mixture of old and new data to a reader, especially when
a producer fails midway through writing. Phase 2A provides reusable staging,
validation, versioned archiving, locking, pointer update, and rollback
infrastructure so a later integration can make one complete run visible as a
single operation.

This phase does **not** integrate the infrastructure into dataset, analysis, or
benchmark commands. The existing flat `reports/ml` layout and all Django pages,
routes, exports, and generated artifacts remain unchanged. No ML command was run
and no real ML output was regenerated.

The implementation is in `analytics/services/ml_publication.py`. It imports the
frozen Phase 1 v1 contracts directly, has no Django view or settings dependency,
and performs no filesystem, database, or network operation at import time. Every
filesystem or publication operation requires a caller-supplied publication
root; pure run-ID and serialization helpers do not touch a root.

## Supported public API

`ml_publication.__all__` defines the supported Phase 2B-facing surface. The
primary operations are `generate_run_id()`, `validate_run_id()`,
`PublicationLock`, `publish_ml_run()`, `validate_published_run()`,
`read_current_pointer()`, and `rollback_current()`. Typed artifact and metadata
value objects, immutable publication result/pointer objects, producer-group
constants, domain exceptions, and the v1 group adapter are also exported.
Manifest construction, copying, hashing, path checks, and schema-validation
helpers are implementation details even though this Phase 2A module keeps them
together for auditability.

## Versioned layout

For an explicitly supplied publication root, the infrastructure uses:

```text
<publication_root>/
    runs/
        <run_id>/
            artifacts/
                <allowlisted artifact files>
            ml_run_manifest.json
    current.json
    publication.lock
```

Temporary staging directories are direct children of the same publication root
and begin with `.staging-`. Keeping staging and `runs/` under the same root is
what permits a same-filesystem atomic directory rename. A successful run
directory is immutable by convention and is never deleted automatically.

`publication.lock` is a persistent regular file. Its presence does not mean a
publisher currently owns the lock; ownership is an operating-system lock held
on an open file descriptor, paired with an in-process guard keyed by the
canonical lock path.

## Artifact allowlists and producer groups

Publication requires an explicit sequence of immutable
`PublicationArtifactSpec` objects. A spec records the filename, artifact type,
producer, required status, and optional public export alias. Unknown source
entries are rejected. An extra artifact can be included only by explicitly
adding its spec, so the allowlist remains auditable.

`v1_artifact_specs_for_groups()` adapts the existing frozen Phase 1 registry and
does not duplicate v1 filenames or aliases. It supports:

- `dataset`: the 8 dataset-producer contracts;
- `analysis` (also accepted as `main_analysis`): the 21 main-analysis contracts;
- `benchmark`: the 6 benchmark contracts;
- `combined`: all three concrete producer groups and all 35 v1 contracts.

The cross-cutting financial-enrichment family remains owned by its actual
dataset or analysis producer; it is not a fourth producer group. The two
conditionally required financial-subset CSVs retain their frozen v1 condition
metadata in the publication allowlist. The staged discriminator JSON is read
before manifest creation: when `ran` activates a condition, the corresponding
CSV is required and its manifest entry records `required: true`; when inactive,
it may be absent. Missing discriminator keys, incompatible discriminator JSON
types, missing active outputs, and conditionally produced files present while
their condition is inactive all fail publication. Rejecting an inactive-but-
present output prevents a stale optional financial CSV from entering a new run.

Exact official dataset, analysis, benchmark, and combined selections invoke the
Phase 1 structural validator by default. Diagnostics are scoped to the selected
group, so expected missing-file diagnostics for other groups do not invalidate
a group-specific run. The full combined selection applies the complete
35-artifact contract validation, including its optional/conditional rules. A
custom allowlist is not treated as official v1 merely because its filenames
happen to overlap. To keep archived identity unambiguous without adding a second
schema framework, a custom allowlist that covers a complete official inventory
but changes its contract metadata is rejected before staging.

## Staging lifecycle

`publish_ml_run()` performs the following sequence while the shared lock is
held:

1. Validate the run ID and immutable artifact allowlist.
2. Accept exactly one source mode: a supplied source directory or an explicit
   sequence/mapping of artifact names to source paths.
3. Reject missing required artifacts, unexpected names, duplicate or
   case-colliding names, traversal names, links, junctions/reparse points, and
   non-regular files.
4. Create a unique staging directory inside the publication root.
5. Stream-copy each source into `artifacts/` without changing the source,
   calculating SHA-256 and byte size as it copies. Source identity, size, and
   modification time are checked for changes during the copy.
6. Build and flush the canonical manifest in staging.
7. Re-read the staged manifest, inventory, hashes, and sizes. If an exact v1
   producer group or the combined set is selected, also run the frozen v1
   JSON/CSV/Markdown structural validator at the corresponding scope.
8. Atomically rename the validated staging directory to `runs/<run_id>`.
9. For an exact complete combined frozen-v1 selection only, write and flush a
   temporary sibling of `current.json`, then atomically replace `current.json`.
   This replacement is the global visibility commit point. Dataset, analysis,
   benchmark, mixed-partial, and custom runs stop after archival and leave the
   pointer unchanged.

Structural validation is automatic for exact official selections and has no
caller opt-out. Custom allowlists receive publication-level inventory, metadata,
hash, size, and path validation but are never treated as frozen-v1 runs.

`publish_ml_run()` returns an immutable `PublicationResult` for both paths. It
identifies the archived run, manifest, digest and artifact count, and records
whether global activation occurred. There is deliberately no public override
that can activate a partial or custom archive.

On a controlled failure before the run rename, the incomplete staging directory
is removed after verifying that it is a direct, correctly prefixed child of the
publication root. Cleanup never follows a staging link or junction. If the run
rename succeeds but pointer replacement fails, the previous pointer remains
active and the complete new run remains as an unreferenced archived run; it is
not deleted.

If best-effort cleanup itself fails, publication preserves the original error
and adds a diagnostic note. A safely named incomplete staging directory or a
hidden pointer temporary file may remain for operator inspection, but neither
is a valid run or changes `current.json`.

The source-directory mode permits only direct child artifact files, and verifies
that each resolved source remains a direct child. The explicit-mapping mode
treats each supplied path as individually authorized but applies the same link,
regular-file, copy, and change-detection checks.

## Shared lock

`PublicationLock` implements one lock name for dataset, analysis, benchmark,
combined publication, and rollback operations. The lock:

- is associated with the explicit publication root;
- uses `msvcrt.locking` on Windows and `flock` on POSIX;
- adds a process-local condition guard keyed by canonical lock path so separate
  instances and threads remain exclusive even where POSIX locks are
  process-scoped;
- uses a monotonic deadline, explicit timeout, and short polling interval;
- raises `PublicationLockTimeout` (a `PublicationLockError` subclass) only for a
  contention deadline, and `PublicationLockError` for unsafe paths, backend
  failures, and release failures;
- releases the operating-system lock and file descriptor after normal exit,
  exceptions, `KeyboardInterrupt`, or process termination;
- leaves the regular lock file in place, preventing the split-inode race caused
  by unlinking and recreating lock files.

The same `PublicationLock` instance is reentrant only for its owning PID and
thread. Cross-thread reuse waits under the same deadline instead of borrowing
the owner's lease. POSIX fork handling detaches inherited child descriptors
without unlocking the parent's lease. A caller can pass an already-acquired
lock to publication; publication takes a nested owner-checked lease for its
full operation. This is intentional for Phase 2B: a producer will need to hold
the shared lock over input reading, generation, staging, and publication, not
merely over the final rename. A lock from a different publication root is
rejected.

Context-manager use is preferred. A caller that invokes `acquire()` manually
must put `release()` in `finally`; abandoning a live lock object can retain its
descriptor until process exit. The at-fork handler protects committed lock
descriptors, but Phase 2B must not deliberately fork a multithreaded process
while another thread is inside lock acquisition or release. Python cannot make
that transition fully atomic with `fork()` across every supported runtime.

Lock-file existence must never be used as a busy-status signal. A nonblocking
lock probe will be needed if the UI later needs an advisory activity indicator.

## Run IDs

Run IDs may be supplied explicitly or generated. Generated IDs combine UTC time
with a random suffix and can include an optional validated short code-revision
component. Git is not invoked. Names are limited to portable ASCII path
characters and reject separators, traversal sequences, absolute/drive/UNC
forms, unsafe trailing characters, case-colliding existing run IDs, and Windows
device names.

## Publication manifest

`ml_run_manifest.json` is publication metadata around the frozen artifact
schemas; it does not replace or revise those schemas. It uses publication schema
version `1` and contains:

- `publication_schema_version`;
- `run_id` and `generated_at_utc`;
- concrete `producer_groups`;
- `code_revision` and `dirty_state`;
- `commands`;
- `python_version` and supplied `library_versions`;
- `seeds` and `source_snapshot`;
- optional `dataset_sha256`, `feature_schema_sha256`, and
  `label_definition_version` values (stored as `null` when not supplied);
- `artifact_count` and `artifacts`.

Every artifact entry contains:

- `filename`;
- POSIX-form `relative_path` (`artifacts/<filename>`);
- `artifact_type` and `producer`;
- boolean `required` status;
- `byte_size` and lowercase SHA-256;
- `public_export_alias`, or `null`.

The concrete `producer_groups` must exactly equal the producers of included
artifacts, so a subset cannot claim unrelated producer groups. Artifact entries
are ordered by portable case-folded filename. JSON is encoded
as UTF-8 with sorted keys, compact separators, no NaN/infinity, and one trailing
newline. Fixed metadata and identical artifact bytes therefore produce
byte-identical manifests. Absolute local paths are rejected from supplied
manifest metadata, and source paths, staging paths, host names, users, PIDs,
mtimes, and inode values are never recorded.

Commands are stored as caller-supplied redacted strings. Metadata normalization
rejects standalone or embedded POSIX, drive-qualified, and UNC absolute paths.
`library_versions` is a string-to-string object; `seeds` and `source_snapshot`
may contain only finite JSON-compatible values with string object keys. This is
bounded metadata validation, not a general schema framework.

The three provenance fields remain optional. When `dataset_sha256` or
`feature_schema_sha256` is supplied and the corresponding `ml_dataset.csv` or
`ml_feature_columns.json` is included in the same run, it must equal that
artifact's computed digest. For downstream partial archives where the referenced
input is not included, the value remains a caller assertion that Phase 2B must
derive from its validated input snapshot.

Before activation, validation confirms the exact schema fields, canonical UTC
timestamps and ordering, safe relative paths, unique filenames, producer/spec
metadata, actual file inventory, artifact count, regular-file status, byte size,
and SHA-256. Only artifact headers/structures are read by the frozen v1
validator; publication hashing streams file contents in bounded chunks.
The manifest does not contain its own hash, avoiding a circular self-hash. Its
canonical bytes are hashed after writing and that digest is stored in
`current.json` when the run is activated.

## Atomic current pointer

`current.json` is a regular JSON file, not a symlink. It contains only:

- `run_id`;
- `relative_run_path`;
- `manifest_relative_path`;
- `published_at_utc`;
- `manifest_sha256`.

The pointer is serialized canonically into a unique temporary sibling, flushed
with `fsync`, closed, and replaced with `os.replace`. No pointer is created until
an activation-eligible complete combined run has passed validation. A failed
pre-replace operation leaves the previous pointer bytes unchanged. Partial and
custom archives never enter the pointer-writing path.

This is an atomic visibility guarantee, not a claim of complete power-loss
durability. Artifact and manifest files are flushed, and POSIX flushes the
`runs/` directory after the run rename, but the module does not portably fsync
the publication-root directory after replacing `current.json`; Windows does not
offer equivalent directory flushing through this implementation. A sudden
machine or filesystem failure can therefore lose a recently replaced directory
entry even though readers never observe a half-written pointer. An asynchronous
exception delivered after `os.replace` can likewise report interruption after
the new pointer has become visible.

Consumers are not switched to this pointer in Phase 2A. Phase 2B must ensure a
consumer reads `current.json` once and resolves every artifact for a request from
that single run.

## Rollback

`rollback_current()` accepts an explicit publication root and validated run ID,
acquires the same shared lock, and validates the target run directory, manifest,
inventory, artifact sizes, and hashes. Global rollback additionally requires a
complete combined frozen-v1 inventory, exact contract metadata, resolved
conditional requirements, and successful full-v1 structural validation.
Dataset-only, analysis-only, benchmark-only, mixed-partial, and custom archives
are valid inspection targets but are not valid global rollback targets. It
rejects linked, missing, incomplete, malformed, partial, custom, or tampered runs
before updating anything. A valid rollback changes only `current.json`; it never
copies, edits, or removes the archived run. If validation or atomic pointer
replacement fails, the active pointer is preserved.

The manifest hash proves that the pointer references the exact manifest bytes it
selected. Phase 2A does not introduce signing, a remote trust anchor, or a
separate append-only publication ledger, so it does not claim protection against
an attacker who can consistently rewrite an archived manifest and every
artifact.

## Failure guarantees

- Source artifacts are opened read-only and are never renamed or modified.
- A run cannot overwrite an existing or case-colliding run ID.
- Unvalidated or incomplete staging directories never become current.
- The previous current pointer is unchanged by failures before atomic pointer
  replacement.
- A pointer temporary-write or pre-replace failure can leave only a hidden
  best-effort-cleaned temporary sibling; it cannot expose partial JSON.
- A crash after run rename but before pointer replacement can leave a complete
  orphan run, not a partially visible current run.
- Successful historical runs are retained indefinitely by this module.
- No cross-device copy fallback is attempted for a failed run-directory rename.
- Public low-level errors are represented by `PublicationError` subclasses, with
  the originating OS/JSON error preserved through exception chaining.

The archive rename and pointer replacement are commit points. A later lock-
release failure can make `publish_ml_run()` or `rollback_current()` raise after
the archive or pointer has already become visible. Phase 2B must treat that
domain error as an indeterminate acknowledgement and inspect the run ID and
`current.json` before retrying; blindly retrying the same run ID will correctly
collide rather than overwrite it.

## Windows and POSIX considerations

Both platforms use direct-child validation, portable filename rules, canonical
forward-slash manifest paths, and same-root staging. Windows junctions and
reparse points are rejected in addition to symbolic links. Device identities
are compared before rename to fail closed if `runs/` and staging are not on the
same filesystem, and no `EXDEV` copy fallback exists. POSIX uses `O_NOFOLLOW`
where available and flushes the `runs/` directory after the atomic rename.
Windows closes temporary-file handles before `os.replace`, which is required
for replacement to succeed.

The guarantees assume a local filesystem whose locking and same-filesystem
rename implementations follow normal Windows or POSIX semantics. UNC/network
publication roots are rejected on Windows. Network filesystems, external
processes that ignore the shared lock, antivirus/open-handle sharing failures,
and hostile path replacement races cannot be given the same guarantees. The
implementation fails closed on observed link, reparse, identity, inventory, or
hash changes; OS-specific CI remains important.

Source hard links are regular files and are not categorically rejected. Copying
creates a new private staged inode, while identity, size, modification time and
content digest checks detect observed source mutation. Published files are
created new, but a privileged actor with write access to the archive can still
create a later hard link or rewrite a complete manifest/artifact set; subsequent
validation detects ordinary drift but is not an authenticity mechanism.

The explicitly supplied root itself and all publication-controlled children are
link-checked. Ancestors are resolved but not categorically rejected because
common POSIX layouts (including macOS temporary paths) contain system-managed
symlink ancestors. The deployment must therefore keep publication-root parent
directories trusted against concurrent replacement.

The checks reduce, but cannot eliminate, portable TOCTOU windows on platforms
without descriptor-relative no-follow operations for every filesystem step.

Temporary staging directories and newly written files use private creator-only
permissions before normal platform `umask`/ACL handling. Phase 2B must confirm
that producers and Django consumers run under the same OS identity, or define an
explicit group/ACL policy before integration. Phase 2A does not guess or widen
deployment permissions.

## Phase boundary

Phase 2A adds infrastructure and temporary-directory tests only. It intentionally
does not add publication manifests to real outputs, move the current flat
artifacts, change any ML method, alter Django consumers, or update the existing
runner locks. Production command integration, one-run consumer resolution, and
migration/compatibility policy belong to Phase 2B.

Group-specific and custom runs are supported as archived inspection units. The
Phase 2A activation policy is already fixed: only an exact, structurally valid,
complete combined frozen-v1 run may replace application-wide `current.json`, and
only such a run may be selected by rollback. Phase 2B must preserve that policy
while integrating producers and consumers; it does not need or receive an
activation override.
