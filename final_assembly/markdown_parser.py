"""CommonMark parsing into the independently verifiable DOCX content model."""
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from .errors import AssemblyError


def fail(message, token=None):
    location = {"line": token.map[0] + 1} if token is not None and token.map else None
    raise AssemblyError("UNSUPPORTED_MARKDOWN", message, location)


def inline(token):
    spans, flags, depths = [], {}, {}
    link_has_content = None
    styles = {"strong": "bold", "em": "italic", "s": "strike"}
    for child in token.children or []:
        kind = child.type
        if kind in {"strong_open", "em_open", "s_open"}:
            style = styles[kind.removesuffix("_open")]
            depths[style] = depths.get(style, 0) + 1
            flags[style] = True
        elif kind in {"strong_close", "em_close", "s_close"}:
            # CommonMark allows the same style to nest. Closing an inner span
            # must not cancel an outer span that still applies to later text.
            style = styles[kind.removesuffix("_close")]
            depths[style] -= 1
            if depths[style] == 0:
                flags.pop(style, None)
        elif kind == "link_open":
            url = child.attrGet("href")
            try:
                parsed = urlsplit(url)
                valid = (parsed.scheme in {"https", "http"} and bool(parsed.hostname)) or (parsed.scheme == "mailto" and bool(parsed.path))
            except ValueError:
                valid = False
            if not valid or child.attrGet("title"):
                fail("Use absolute HTTP(S) or mailto links without a title; local/anchor links need an explicit portable destination.", token)
            flags["url"] = url
            link_has_content = False
        elif kind == "link_close":
            if not link_has_content:
                fail("Links must have a nonempty label; empty labels cannot be preserved in the DOCX profile.", token)
            flags.pop("url", None)
            link_has_content = None
        elif kind in {"text", "code_inline", "softbreak", "hardbreak"}:
            value = " " if kind == "softbreak" else "\n" if kind == "hardbreak" else child.content
            formatting = {**flags, **({"code": True} if kind == "code_inline" else {})}
            if value:
                if link_has_content is not None:
                    link_has_content = True
                if spans and {k: v for k, v in spans[-1].items() if k != "text"} == formatting:
                    spans[-1]["text"] += value
                else:
                    spans.append({"text": value, **formatting})
        else:
            fail(f"Unsupported inline content: {kind}. Images and embedded HTML are not included in this DOCX profile.", token)
    return spans


def parse_markdown(text):
    if not isinstance(text, str):
        raise AssemblyError("INVALID_MARKDOWN", "Markdown input must be a Unicode string.")
    if "<!-- final-assembly:" in text:
        fail("Reserved Final Assembly block markers cannot occur inside a source block.")
    if any((ord(c) < 32 and c not in "\r\n\t") or ord(c) in {0x7F, 0xFEFF, 0xFFFE, 0xFFFF} or 0xD800 <= ord(c) <= 0xDFFF for c in text):
        fail("Source contains a BOM, unsupported control character or invalid Unicode.")
    if "\r" in text.replace("\r\n", ""):
        fail("Use LF or CRLF line endings.")
    parser = MarkdownIt("commonmark").enable("table").enable("strikethrough")
    # Our URL policy emits a clear error instead of silently making a bad link literal.
    parser.validateLink = lambda url: True
    tokens = parser.parse(text)
    units, lists = [], []
    item, quote, index = None, 0, 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind in {"bullet_list_open", "ordered_list_open"}:
            if lists or quote:
                fail("Nested lists and lists inside quotes are not yet supported; keep these blocks as Markdown or separate approved sections.", token)
            start = token.attrGet("start")
            lists.append({"ordered": kind == "ordered_list_open", "next": 1 if start is None else int(start)})
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif kind == "list_item_open":
            item = {"seen": False}
        elif kind == "list_item_close":
            if item is not None and not item["seen"]:
                units.append({"kind": "list_item", "ordered": lists[-1]["ordered"], **({"number": lists[-1]["next"]} if lists[-1]["ordered"] else {}), "spans": []})
                lists[-1]["next"] += 1
            item = None
        elif kind == "blockquote_open":
            if quote or lists:
                fail("Nested quotes or quotes inside lists are not supported.", token)
            quote += 1
        elif kind == "blockquote_close":
            quote -= 1
        elif kind in {"paragraph_open", "heading_open"}:
            child = tokens[index + 1]
            if child.type != "inline":
                fail("Expected textual paragraph content.", token)
            spans = inline(child)
            if item is not None:
                if item["seen"] or kind == "heading_open":
                    fail("Each flat list item must contain one paragraph.", token)
                item["seen"] = True
                state = lists[-1]
                if child.content.startswith(("[ ] ", "[x] ", "[X] ")):
                    fail("Interactive task lists are not part of the DOCX profile.", child)
                unit = {"kind": "list_item", "ordered": state["ordered"], "spans": spans}
                if state["ordered"]:
                    unit["number"] = state["next"]
                    state["next"] += 1
            elif quote:
                if kind == "heading_open":
                    fail("Headings inside quotes are not supported.", token)
                unit = {"kind": "quote", "spans": spans}
            else:
                unit = {"kind": "heading", "level": int(token.tag[1:]), "spans": spans} if kind == "heading_open" else {"kind": "paragraph", "spans": spans}
            units.append(unit)
            index += 2
        elif kind in {"fence", "code_block"}:
            if quote or lists:
                fail("Code blocks inside lists/quotes are not supported.", token)
            # Fence language is a rendering hint; code text remains exact in DOCX.
            units.append({"kind": "code_block", "spans": [{"text": token.content}] if token.content else []})
        elif kind == "table_open":
            if quote or lists:
                fail("Tables inside lists/quotes are not supported.", token)
            rows, alignment, row = [], [], None
            index += 1
            while tokens[index].type != "table_close":
                current = tokens[index]
                if current.type == "tr_open":
                    row = []
                    rows.append(row)
                elif current.type in {"th_open", "td_open"}:
                    row.append(inline(tokens[index + 1]))
                    if current.type == "th_open":
                        alignment.append((current.attrGet("style") or "text-align:left").split(":")[-1])
                index += 1
            # Markdown-it pads/drops ragged cells per GFM; do not hide data loss.
            for source_line in text.replace("\r\n", "\n").split("\n")[token.map[0] + 2:token.map[1]]:
                from markdown_it.rules_block.table import escapedSplit
                parts = escapedSplit(source_line.strip())
                if parts and not parts[0].strip(): parts.pop(0)
                if parts and not parts[-1].strip(): parts.pop()
                if len(parts) != len(rows[0]):
                    raise AssemblyError("NON_RECTANGULAR_TABLE", "Table rows must have the same number of cells; no padding or dropped cells is permitted.", {"line": token.map[0] + 1})
            units.append({"kind": "table", "rows": rows, "alignment": alignment})
        elif kind == "hr":
            fail("Horizontal rules are not supported in the DOCX profile; use headings and paragraph spacing.", token)
        else:
            fail(f"Unsupported block: {kind}.", token)
        index += 1
    return units
