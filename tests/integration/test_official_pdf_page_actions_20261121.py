"""Page actions, interactive form containers and JavaScript annotations need review holds.

A PDF may have normal textual scholarship evidence while hiding unsafe
interactive structures below its document catalog. The isolated evidence
reviewer never executes any action and must fail closed before accepting text.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from tools.official_pdf_worker import inspect


def _action(kind: str = "JavaScript", uri: str = "https://ieb.ub.edu/") -> DictionaryObject:
    if kind == "URI":
        return DictionaryObject({
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject(uri),
        })
    return DictionaryObject({
        NameObject("/S"): NameObject("/JavaScript"),
        NameObject("/JS"): TextStringObject("app.alert('Untrusted content')"),
    })


def _text_pdf(*, scenario: str, uri: str = "https://ieb.ub.edu/") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 30 700 Td (Barcelona Institute of Economics. "
        b"Current PhD Scholarship in Economics: candidates must hold a masters "
        b"degree and apply before 11 December 2026. University of Barcelona.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)

    if scenario == "page_script":
        page[NameObject("/AA")] = DictionaryObject({
            NameObject("/O"): _action(),
        })
    elif scenario in {"annotation_script", "annotation_uri"}:
        ann = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(20), NumberObject(20)]
            ),
            NameObject("/A"): _action("URI" if scenario == "annotation_uri" else "JavaScript", uri),
        })
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(ann)])
    elif scenario == "form_container":
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
            NameObject("/Fields"): ArrayObject([]),
        })
    elif scenario != "plain":
        raise ValueError(f"Unknown scenario: {scenario}")

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "scenario",
    ["page_script", "annotation_script", "form_container"],
)
def test_active_pdf_pages_and_forms_are_held_before_text_approval(scenario: str) -> None:
    result = inspect(_text_pdf(scenario=scenario))
    assert result == {"status": "document_unverified", "reason": "active_pdf"}


@pytest.mark.parametrize("scenario", ["plain", "annotation_uri"])
def test_plain_text_and_nonexecuting_website_links_remain_readable(scenario: str) -> None:
    result = inspect(_text_pdf(scenario=scenario))
    assert result["status"] == "ok", result
    assert "PhD Scholarship in Economics" in result["text"]


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "vbscript:msgbox('x')",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "ftp://files.example.edu/archive",
        "//evil.example.edu/relative",
        "https://student:password@ieb.ub.edu/private",
        "https://ieb.ub.edu\\@evil.example.org/redirect",
    ],
)
def test_pdf_action_uri_must_be_a_clean_http_or_https_web_link(uri: str) -> None:
    result = inspect(_text_pdf(scenario="annotation_uri", uri=uri))
    assert result == {"status": "document_unverified", "reason": "active_pdf"}


@pytest.mark.parametrize("uri", [
    "https://ieb.ub.edu/convocatorias/",
    "https://www.ub.edu/school-economics/phd-in-economics/",
    "http://www.ieb.ub.edu/",
])
def test_safe_web_link_does_not_invalidate_pdf_text(uri: str) -> None:
    result = inspect(_text_pdf(scenario="annotation_uri", uri=uri))
    assert result["status"] == "ok", result
