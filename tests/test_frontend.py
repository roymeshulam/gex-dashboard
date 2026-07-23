from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_expected_ranges_highlights_preferred_dtes():
    app_source = (ROOT / "frontend" / "js" / "app.js").read_text()
    css_source = (ROOT / "frontend" / "css" / "style.css").read_text()

    assert "new Set([14, 28, 42, 56])" in app_source
    assert 'class="expected-range-preferred"' in app_source
    assert "#expectedRangesTable tr.expected-range-preferred td" in css_source
