"""Byte-preserving Markdown block framing."""
import re
from .errors import AssemblyError
from .markdown_parser import parse_markdown
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_BEGIN = re.compile(rb"<!-- final-assembly:block ([A-Za-z0-9][A-Za-z0-9_.-]{0,79}) -->\n")


def _decode(raw: bytes, block_id: str) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AssemblyError("INVALID_UTF8", "Markdown block is not valid UTF-8.", {"block": block_id, "byte_offset": exc.start}) from exc


def write_markdown(blocks: list[dict]) -> bytes:
    """Frame original bytes; source newlines are never trimmed or rewritten."""
    output: list[bytes] = []
    seen: set[str] = set()
    for block in blocks:
        block_id = block.get("id")
        if not isinstance(block_id, str) or not _ID.fullmatch(block_id):
            raise AssemblyError("INVALID_BLOCK_ID", "Markdown block IDs must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}.")
        if block_id in seen:
            raise AssemblyError("DUPLICATE_BLOCK_ID", "Duplicate Markdown block ID.", {"block": block_id})
        seen.add(block_id)
        raw = block.get("raw")
        if not isinstance(raw, bytes):
            raise AssemblyError("INVALID_MARKDOWN", "Each Markdown block must contain raw bytes.", {"block": block_id})
        units = parse_markdown(_decode(raw, block_id))
        if "units" in block and block["units"] != units:
            raise AssemblyError("SOURCE_IR_MISMATCH", "Block units differ from the actual source bytes.", {"block": block_id})
        output.extend([
            f"<!-- final-assembly:block {block_id} -->\n".encode("ascii"),
            raw,
            f"\n<!-- final-assembly:end {block_id} -->\n".encode("ascii"),
        ])
    return b"".join(output)


def read_markdown(data: bytes) -> list[dict]:
    """Read actual framed file bytes, refusing any unaccounted-for content."""
    if not isinstance(data, bytes):
        raise AssemblyError("INVALID_MARKDOWN", "Markdown export input must be bytes.")
    blocks: list[dict] = []
    seen: set[str] = set()
    position = 0
    while position < len(data):
        marker = _BEGIN.match(data, position)
        if marker is None:
            raise AssemblyError("INVALID_MARKDOWN_FRAME", "Unexpected content outside a block or malformed begin marker.", {"byte_offset": position})
        block_id = marker.group(1).decode("ascii")
        if block_id in seen:
            raise AssemblyError("DUPLICATE_BLOCK_ID", "Duplicate block marker in Markdown export.", {"block": block_id})
        seen.add(block_id)
        ending = f"\n<!-- final-assembly:end {block_id} -->\n".encode("ascii")
        end = data.find(ending, marker.end())
        if end < 0:
            raise AssemblyError("INVALID_MARKDOWN_FRAME", "Missing or malformed matching end marker.", {"block": block_id, "byte_offset": marker.end()})
        raw = data[marker.end():end]
        if b"<!-- final-assembly:" in raw:
            raise AssemblyError("INVALID_MARKDOWN_FRAME", "Nested or mismatched block marker.", {"block": block_id})
        units = parse_markdown(_decode(raw, block_id))
        blocks.append({"id": block_id, "raw": raw, "units": units})
        position = end + len(ending)
    return blocks
