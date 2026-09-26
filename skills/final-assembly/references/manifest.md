# Manifest

```json
{
  "schema_version": 1,
  "title": "Release brief",
  "blocks": [{
    "id": "summary-v1",
    "section": "Summary",
    "order": 10,
    "source": {"path": "sources/summary.md", "origin": "User-selected draft"},
    "approved": true,
    "sha256": "<SHA-256 of exact UTF-8 file bytes>"
  }]
}
```

IDs use 1–80 ASCII letters, digits, dots, underscores or hyphens, starting with a
letter/digit. `sha256` is 64 lowercase hex digits; compute it from file bytes.
Effective blocks need unique orders. `source.reference` may hold provenance.
New versions may add `replaces: "summary-v1"`; retain the older source.

`prepare` creates unapproved records and source snapshots. `inspect` can show
drafts and their issues without authorizing a build. `approve` writes a new
manifest and may add the optional block field
`approval: {"decision": "The actual adoption instruction", "sha256": "<same block hash>"}`.
The decision must be nonempty and bound to that block's hash; it is not an identity
signature. Existing manifests with boolean approval and no decision field remain
compatible. Source paths are rebased when writing a manifest in a new directory.

ContextPack import preserves reference metadata, including the full-message
`sourceHash`. The selected `exactText` is checked against `excerptHash`, which is
distinct from full-message provenance. Unknown source IDs remain null. Legacy
whole-message imports are identified as such; partial legacy input needs re-export
with an excerpt hash, never a rewritten source hash. All imports remain unapproved.

Supported: CommonMark headings, paragraphs, flat one-paragraph lists,
inline bold/italic/strikethrough/code, hard/soft breaks, one-level quotes, code
blocks, absolute HTTP(S)/mailto links and rectangular pipe tables with alignment.
Markdown bytes remain exact. DOCX checks normalized rendered content: soft wraps
become spaces, escapes/entities decode, numbering follows CommonMark, and fence
language hints are not syntax highlighting. Nested lists, interactive task lists,
images, HTML, horizontal rules and merged cells fail explicitly. Dollar signs
and underscores can be text; there is no formula renderer.

Empty-label links, relative/anchor links and link title attributes are rejected. Sources must be
UTF-8 without BOM. Verification covers generated DOCX, not arbitrary Word files.
