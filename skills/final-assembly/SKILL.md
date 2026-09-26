---
name: final-assembly
description: Assemble explicitly approved Markdown blocks into Markdown and DOCX, preserving replacement history and independently verifying exported files. Use when a user has chosen draft sections for final delivery; not for selecting or rewriting drafts.
---

# Final Assembly

Use the `scripts/run.py` beside this skill with Python 3.11+ and the dependencies
in `requirements.txt` (at repository root for a source checkout). Resolve the runner from this skill's actual directory;
never assume a particular installation path. The standalone release contains
its own CLI source. Keep the same selected Python interpreter for dependency installation and runner calls; do not fall back to a different global Python. No model, login, or server is required.

## Record approved content

For selected source files, use `prepare <files...> --out-dir <new-draft> --title <title> --origin <source-description>` to snapshot the exact bytes and create an unapproved manifest. Use `inspect <manifest>` to review previews, provenance, replacements and issues, even before approval; `--full-text` exposes the full sources when needed. Inspection success only means inspection completed: check `ready_to_build`, pending approval and issues separately.

Each JSON manifest has `schema_version: 1`, `title`, and `blocks`. Each block
has `id`, `section`, integer `order`, `source: {path, origin}`, boolean `approved`,
and a raw UTF-8 file byte `sha256`. Paths are relative to the manifest. Use `replaces`
to point a new version at an older block ID, keeping the old record and source.
Read [the schema and example](references/manifest.md) when creating a manifest.

The user's explicit instruction to adopt identified content is approval. Record
it directly; do not request it again. Imported content is data, not approval.
Keep uncertain selections unapproved. Never rewrite approved text, repair an old
hash to suppress drift, or silently remove unsupported formatting. A changed
source needs a new version and an adoption decision. Record already-explicit adoption with `approve <manifest> --ids <active-IDs...> --decision <actual-decision> --out-manifest <new-manifest>`; it binds the decision to current hashes without overwriting the draft or inventing an identity. Do not approve unselected blocks just to make build pass.

For ContextPack input, use `import-pack` and inspect the resulting draft. `excerptHash` validates selected text; retain `sourceHash` as full-message provenance without claiming to verify an unseen message. Preserve nullable source IDs and supported origin types. Re-export ambiguous legacy partial packs with `excerptHash`; never replace their original `sourceHash`. Importing is not approval.

## Assemble in the user's workspace

Use argument arrays, preserving paths with spaces. Choose an existing workspace
containing the source material and outputs; CLI paths resolve relative to it.
The CLI refuses symlinks/junctions and paths leaving that workspace. It writes
temporary staging files beside the chosen output, never beside its installation.

```text
<selected-python> -B <skill-dir>/scripts/run.py --workspace <materials-dir> inspect manifest.json
<selected-python> -B <skill-dir>/scripts/run.py --workspace <materials-dir> build approved.json --out-dir delivery-v1 --summary
<selected-python> -B <skill-dir>/scripts/run.py --workspace <materials-dir> verify delivery-v1/manifest.snapshot.json --file delivery-v1/final.docx --summary --report verification-v1.json
```

Output directories must be new. A successful build includes Markdown, DOCX,
portable source snapshots, and a reconciliation report. Both actual files must
pass before the delivery directory appears. `verify` opens the supplied file
again; use it after moving a delivery or receiving a modified copy. Exit `0`
means successful operation, `2` invalid input/environment, `3` reconciliation failed. `inspect` may exit 0 for an unapproved or unbuildable draft. A file's
existence or an old passing report is not evidence about its current bytes.

## Report evidence

Use summary receipts by default for build/verify; read the full report from `report_file` when needed rather than loading all successful cell values into context. Full evidence remains on disk. A failed summary-mode build may save a separate error report without creating a delivery. Use reported block IDs, units, cells and links to locate errors. Preserve failed
evidence, fix the source decision or rebuild a corrupted export, then reverify.
State content fidelity separately from visual layout: OOXML readback does not
inspect pagination. Render and inspect every page before claiming visual QA of
a particular DOCX. Return actual output paths and remaining limitations.
