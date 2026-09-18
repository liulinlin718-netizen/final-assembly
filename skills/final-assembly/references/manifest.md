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

Supported: CommonMark headings, paragraphs, flat one-paragraph lists,
inline bold/italic/strikethrough/code, hard/soft breaks, one-level quotes, code
blocks, absolute HTTP(S)/mailto links and rectangular pipe tables with alignment.
Markdown bytes remain exact. DOCX checks normalized rendered content: soft wraps
become spaces, escapes/entities decode, numbering follows CommonMark, and fence
language hints are not syntax highlighting. Nested lists, interactive task lists,
images, HTML, horizontal rules and merged cells fail explicitly. Dollar signs
and underscores can be text; there is no formula renderer.

Relative/anchor links and link title attributes are rejected. Sources must be
UTF-8 without BOM. Verification covers generated DOCX, not arbitrary Word files.
