"""Regression checks for long salary labels in the listings ledger."""

import re
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parents[2] / "docs" / "index.html"


def styles():
    return DASHBOARD.read_text(encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]


def rule(css, selector):
    return re.findall(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css)


def test_long_compensation_cannot_force_a_narrow_title_column():
    css = styles()
    html = DASHBOARD.read_text(encoding="utf-8")
    layout = rule(css, ".row-main")
    assert "minmax(0, 1fr)" in layout[0]
    assert "fit-content(40%)" in layout[0]
    salary = rule(css, ".tag-salary")[0]
    assert "white-space: normal" in salary
    assert "max-width: 100%" in salary
    assert "overflow-wrap: anywhere" in salary
    assert "min-width: 0" in rule(css, ".row-info")[0]
    assert "flex-wrap: wrap" in rule(css, ".row-badges")[0]
    assert "grid-row: 2" in rule(css, ".row-info")[-1]
    assert "grid-row: 3" in rule(css, ".row-badges")[-1]
    renderer = html.split("function renderLedger(rows)", 1)[1].split("// Render Grid Cards", 1)[0]
    assert 'class="row-info"' in renderer
    assert 'class="row-badges"' in renderer
    assert "minmax(min(100%, 340px), 1fr)" in css


@pytest.mark.parametrize("width", [1200, 820, 390, 320])
@pytest.mark.parametrize("compensation", [
    "Remuneration in accordance with the guidelines of the MPG funding agreements "
    "(65 per cent of EG13, TVöD-Bund)",
    "VeryLongUnbrokenCompensationText" * 10,
])
def test_salary_badge_wraps_without_crushing_title(width, compensation):
    browser_api = pytest.importorskip("playwright.sync_api")
    from html import escape

    html = f"""<!doctype html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>{styles()}</style></head>
    <body style="margin:0;padding:18px"><div class="rows-container">
      <div class="row"><div class="row-main">
        <span class="dl">22 Nov 2026</span>
        <div class="row-info">
          <h4>Research Fellow positions (Doctoral Researchers)</h4>
          <p>Max-Planck-Institut für ausländisches öffentliches Recht
          und Völkerrecht · Heidelberg, Germany</p>
        </div>
        <div class="row-badges">
          <span class="tag">PhD</span>
          <span class="tag-salary">{escape(compensation)}</span>
        </div><i class="chev"></i>
      </div></div>
    </div></body></html>"""
    with browser_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f"Chromium unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.set_content(html)
            sizes = page.evaluate("""() => {
                const r = selector => {
                  const b = document.querySelector(selector).getBoundingClientRect();
                  return {width:b.width,left:b.left,right:b.right,top:b.top};
                };
                return {
                  row:r('.row-main'), title:r('.row-info h4'),
                  salary:r('.tag-salary'), badges:r('.row-badges'),
                  scrollWidth:document.documentElement.scrollWidth
                };
            }""")
            assert sizes["scrollWidth"] <= width + 1
            assert sizes["salary"]["right"] <= sizes["row"]["right"] - 8
            assert sizes["title"]["width"] >= sizes["row"]["width"] * (
                0.3 if width > 780 else 0.6
            )
            if width <= 780:
                assert sizes["badges"]["top"] > sizes["title"]["top"]
        finally:
            browser.close()
