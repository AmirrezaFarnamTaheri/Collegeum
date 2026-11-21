"""Constrained DOCX worker: inspect OOXML without resolving entities or running macros."""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import PurePosixPath
from typing import Any

MAX_DOCX_BYTES = 1024 * 1024
MAX_ZIP_ENTRIES = 100
MAX_EXPANDED_BYTES = 3 * 1024 * 1024
MAX_PART_BYTES = 1024 * 1024
MAX_PARAGRAPHS = 150
MAX_DOCX_TEXT = 24000

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PKG_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def _xml(blob: bytes) -> Any:
    from lxml import etree

    if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
        raise ValueError("DTD prohibited")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                              huge_tree=False, remove_comments=True, remove_pis=True)
    return etree.fromstring(blob, parser=parser)


def _part(archive: zipfile.ZipFile, name: str) -> bytes:
    with archive.open(name) as handle:
        value = handle.read(MAX_PART_BYTES + 1)
    if len(value) > MAX_PART_BYTES:
        raise ValueError("Oversized OOXML part")
    return value


def _inspect(data: bytes) -> dict[str, str]:
    if not isinstance(data, bytes) or len(data) > MAX_DOCX_BYTES:
        return {"status": "document_unverified", "reason": "oversize"}
    if not data.startswith(b"PK\\x03\\x04"):
        return {"status": "document_unverified", "reason": "not_docx"}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not 3 <= len(entries) <= MAX_ZIP_ENTRIES:
            return {"status": "document_unverified", "reason": "zip_entries"}
        seen: set[str] = set()
        expanded = 0
        for entry in entries:
            name = entry.filename
            canonical = name.casefold()
            parts = PurePosixPath(name).parts
            if (not name or name.startswith("/") or "\\\\" in name or ":" in name
                    or "\\x00" in name or any(x in {"..", "."} for x in parts)
                    or name.endswith("/") or canonical in seen
                    or entry.flag_bits & 1
                    or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or entry.file_size > MAX_PART_BYTES
                    or ((entry.external_attr >> 16) & 0o170000) == 0o120000):
                return {"status": "document_unverified", "reason": "unsafe_zip_entry"}
            seen.add(canonical)
            expanded += entry.file_size
            if (expanded > MAX_EXPANDED_BYTES
                    or (entry.file_size > 100 * max(1, entry.compress_size)
                        and entry.file_size > 10_000)):
                return {"status": "document_unverified", "reason": "zip_expansion"}
            if re.search(r"(?:^|/)(?:vba(?:project|data)|activex|embeddings|oleobject|customxml|afchunk)",
                         canonical, re.I):
                return {"status": "document_unverified", "reason": "active_content"}
        if not {"[content_types].xml", "_rels/.rels", "word/document.xml"} <= seen:
            return {"status": "document_unverified", "reason": "missing_package_parts"}
        types = _xml(_part(archive, "[Content_Types].xml"))
        if types.tag != f"{{{PKG_CONTENT}}}Types":
            return {"status": "document_unverified", "reason": "invalid_content_types"}
        document_types = [node.get("ContentType") for node in types
                          if node.get("PartName") == "/word/document.xml"]
        if document_types != [MAIN_TYPE] or any(
            "macroEnabled" in str(node.get("ContentType", "")) for node in types
        ):
            return {"status": "document_unverified", "reason": "active_content_type"}
        for info in entries:
            if info.filename.lower().endswith(".rels"):
                rels = _xml(_part(archive, info.filename))
                if rels.tag != f"{{{PKG_REL}}}Relationships":
                    return {"status": "document_unverified", "reason": "invalid_relationships"}
                if any(node.get("TargetMode", "").casefold() == "external" for node in rels):
                    return {"status": "document_unverified", "reason": "external_relationship"}
        body = _xml(_part(archive, "word/document.xml"))
        if body.tag != f"{{{WORD}}}document":
            return {"status": "document_unverified", "reason": "invalid_document"}
        ambiguous = {"ins", "del", "moveFrom", "moveTo", "instrText", "fldSimple",
                     "altChunk", "vanish", "webHidden", "object", "OLEObject",
                     "txbxContent", "sdt"}
        blocked = {f"{{{WORD}}}{tag}" for tag in ambiguous}
        if any(node.tag in blocked for node in body.iter()):
            return {"status": "document_unverified", "reason": "ambiguous_word_content"}
        paras = body.findall(f".//{{{WORD}}}p")
        if not 1 <= len(paras) <= MAX_PARAGRAPHS:
            return {"status": "document_unverified", "reason": "paragraph_count"}
        chunks: list[str] = []
        length = 0
        for p in paras:
            line = "".join((node.text or "") for node in p.iter(f"{{{WORD}}}t")).strip()
            if line:
                chunks.append(line)
                length += len(line) + 1
            if length > MAX_DOCX_TEXT:
                return {"status": "document_unverified", "reason": "text_oversize"}
        text = re.sub(r"\\s+", " ", " ".join(chunks)).strip()
        if len(text) < 100:
            return {"status": "document_unverified", "reason": "no_usable_text"}
        return {"status": "ok", "text": text}


def inspect(data: bytes) -> dict[str, str]:
    try:
        return _inspect(data)
    except Exception:
        return {"status": "document_unverified", "reason": "invalid_docx"}


def main() -> int:
    data = sys.stdin.buffer.read(MAX_DOCX_BYTES + 1)
    sys.stdout.write(json.dumps(inspect(data), ensure_ascii=True) + "\\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
