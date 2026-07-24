from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_expected_ranges_highlights_preferred_dtes():
    app_source = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    css_source = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")

    assert "PREFERRED_EXPECTED_RANGE_DTES = [14, 28, 42, 56]" in app_source
    assert "preferredExpectedRangeDtes(ranges.rows)" in app_source
    assert 'class="expected-range-preferred"' in app_source
    assert "#expectedRangesTable tr.expected-range-preferred td" in css_source


def test_expected_ranges_tiers_checkbox_filters_to_highlighted_rows():
    app_source = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    html_source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="expectedRangesTiers" type="checkbox"' in html_source
    assert "<span>Tiers</span>" in html_source
    assert 'const tiersOnly = $("expectedRangesTiers").checked' in app_source
    assert "ranges.rows.filter((row) => preferredDtes.has(Number(row.dte)))" in app_source
    assert '$("expectedRangesTiers").addEventListener("change"' in app_source


def test_strikemap_level_chips_show_wall_distance_from_spot():
    app_source = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    html_source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "function strikeDistancePct(strike, spot)" in app_source
    assert "return (strike - spot) / spot * 100;" in app_source
    assert 'chipHtml("Call Dist", Fmt.fmtPct(strikeDistancePct(lv.call_wall, lv.spot))' in app_source
    assert 'chipHtml("Put Dist", Fmt.fmtPct(strikeDistancePct(lv.put_wall, lv.spot))' in app_source
    assert 'chipHtml("Call Dist", Fmt.fmtPct(strikeDistancePct(s.call_wall, s.spot))' in app_source
    assert 'chipHtml("Put Dist", Fmt.fmtPct(strikeDistancePct(s.put_wall, s.spot))' in app_source
    assert "/js/app.js?v=18" in html_source


def test_expected_range_fallback_prefers_nearest_available_dte_above():
    preferred = [14, 28, 42, 56]
    available = [14, 28, 43, 58, 70]
    selected = set()

    for target in reversed(preferred):
        above = next(
            (dte for dte in available
             if dte >= target and dte not in selected),
            None,
        )
        below = next(
            (dte for dte in reversed(available)
             if dte < target and dte not in selected),
            None,
        )
        selected.add(above if above is not None else below)

    assert selected == {14, 28, 43, 58}
