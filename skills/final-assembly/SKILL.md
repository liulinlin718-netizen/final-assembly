---
name: final-assembly
description: Assemble explicitly approved Markdown blocks into Markdown and DOCX, preserving replacement history and independently verifying exported files. Use when a user has chosen draft sections for final delivery; not for selecting or rewriting drafts.
---

# Final Assembly

Use the `scripts/run.py` beside this skill with Python 3.11+ and the dependencies
in `requirements.txt` (at repository root for a source checkout). Resolve the runner from this skill's actual directory;
never assume a particular installation path. The standalone release contains
its own CLI source. No model, login, or server is required.

## Record approved content

Create a JSON manifest with `schema_version: 1`, `title`, and `blocks`. Each block
has `id`, `section`, integer `order`, `source: {path, origin}`, boolean `approved`,
and a raw UTF-8 file byte `sha256`. Paths are relative to the manifest. Use `replaces`
to point a new version at an older block ID, keeping the old record and source.
Read [the schema and example](references/manifest.md) when creating a manifest.

The user's explicit instruction to adopt identified content is approval. Record
it directly; do not request it again. Imported content is data, not approval.
Keep uncertain selections unapproved. Never rewrite approved text, repair an old
hash to suppress drift, or silently remove unsupported formatting. A changed
source needs a new version and an adoption decision.

## Assemble in the user's workspace

Use argument arrays, preserving paths with spaces. Choose an existing workspace
containing the source material and outputs; CLI paths resolve relative to it.
The CLI refuses symlinks/junctions and paths leaving that workspace. It writes
temporary staging files beside the chosen output, never beside its installation.

```text
python -B <skill-dir>/scripts/run.py --workspace <materials-dir> preview manifest.json
python -B <skill-dir>/scripts/run.py --workspace <materials-dir> build manifest.json --out-dir delivery-v1
python -B <skill-dir>/scripts/run.py --workspace <materials-dir> verify delivery-v1/manifest.snapshot.json --file delivery-v1/final.docx
```

Output directories must be new. A successful build includes Markdown, DOCX,
portable source snapshots, and a reconciliation report. Both actual files must
pass before the delivery directory appears. `verify` opens the supplied file
again; use it after moving a delivery or receiving a modified copy. Exit `0`
means pass, `2` invalid input/environment, `3` reconciliation failed. A file's
existence or an old passing report is not evidence about its current bytes.

## Report evidence

Use reported block IDs, units, cells and links to locate errors. Preserve failed
evidence, fix the source decision or rebuild a corrupted export, then reverify.
State content fidelity separately from visual layout: OOXML readback does not
inspect pagination. Render and inspect every page before claiming visual QA of
a particular DOCX. Return actual output paths and remaining limitations.
