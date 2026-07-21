import datetime

import pytest

from app.engine.greeks import build_surface, calculate_curves, option_metrics, option_price
from tests.conftest import mk


def test_option_price_respects_expiry_intrinsic_value():
    assert option_price(90.0, 100.0, 0.0, 0.2, "P") == 10.0
    assert option_price(110.0, 100.0, 0.0, 0.2, "C") == 10.0


def test_option_price_put_call_parity():
    call = option_price(100.0, 100.0, 0.5, 0.2, "C", rate=0.0)
    put = option_price(100.0, 100.0, 0.5, 0.2, "P", rate=0.0)
    assert call == pytest.approx(put)


def test_option_metrics_have_standard_units_and_signs():
    metrics = option_metrics(100.0, 100.0, 0.5, 0.2, "C", rate=0.0)
    assert 0.0 < metrics["delta"] < 1.0
    assert metrics["gamma"] > 0.0
    assert metrics["theta"] < 0.0
    assert metrics["vega"] > 0.0


def test_curves_use_selected_implied_volatility_and_count_down_to_expiry():
    today = datetime.date(2026, 7, 18)
    contracts = [
        mk(expiry=today + datetime.timedelta(days=10), cp="P", strike=6000,
           iv=0.20, bid=10, ask=11),
        mk(expiry=today + datetime.timedelta(days=30), cp="P", strike=6000,
           iv=0.30, bid=20, ask=21),
    ]
    surface = build_surface(contracts, 6000.0, today)
    result = calculate_curves(surface, "2026-07-28", 6000.0, "P")

    assert result["cp"] == "P"
    assert result["iv_pct"] == 20.0
    assert result["expected_move"] == pytest.approx(198.63, abs=0.01)
    assert result["spot_lower"] == 5800.0
    assert result["spot_upper"] == 6200.0
    assert result["spot_curve"][0][0] == result["spot_lower"]
    assert result["spot_curve"][-1][0] == result["spot_upper"]
    assert len(result["spot_curve"]) == 61
    assert len(result["volatility_curve"]) == 61
    assert result["volatility_curve"][0][0] == 10.0
    assert result["volatility_curve"][-1][0] == 30.0
    assert result["volatility_curve"][30][0] == result["iv_pct"]
    assert result["volatility_curve"][0][1] < result["volatility_curve"][30][1]
    assert result["volatility_curve"][30][1] < result["volatility_curve"][-1][1]
    assert [row[0] for row in result["time_curve"]] == list(range(10, -1, -1))
    assert [row[2] for row in result["time_curve"]] == [20.0] * 11
    assert result["time_curve"][-1][1] == pytest.approx(0.0)
    assert set(result["curves"]) == {"price", "delta", "gamma", "theta", "vega"}
    assert all(set(curves) == {"spot", "volatility", "time"}
               for curves in result["curves"].values())

    later = calculate_curves(surface, "2026-08-17", 6000.0, "P")
    assert later["dte"] == 30
    assert later["time_curve"][0][0] == 30
    assert later["time_curve"][-1][0] == 0
    assert len(later["time_curve"]) == 31


def test_long_time_curves_are_downsampled_with_endpoints_preserved():
    today = datetime.date(2026, 7, 18)
    expiry = today + datetime.timedelta(days=730)
    surface = build_surface([
        mk(expiry=expiry, cp="C", strike=6000, iv=0.20, bid=10, ask=11),
    ], 6000.0, today)

    result = calculate_curves(surface, expiry.isoformat(), 6000.0, "C")
    dtes = [row[0] for row in result["time_curve"]]

    assert len(dtes) == 121
    assert dtes[0] == 730
    assert dtes[-1] == 0
    assert all(left > right for left, right in zip(dtes, dtes[1:]))


def test_short_position_inverts_price_and_all_greeks():
    today = datetime.date(2026, 7, 18)
    expiry = today + datetime.timedelta(days=30)
    surface = build_surface([
        mk(expiry=expiry, cp="C", strike=6000, iv=0.20, bid=10, ask=11),
    ], 6000.0, today)

    long = calculate_curves(surface, expiry.isoformat(), 6000.0, "C", "long")
    short = calculate_curves(surface, expiry.isoformat(), 6000.0, "C", "short")

    assert long["position"] == "long"
    assert short["position"] == "short"
    for metric in long["curves"]:
        for axis in long["curves"][metric]:
            assert [row[0] for row in short["curves"][metric][axis]] == [
                row[0] for row in long["curves"][metric][axis]
            ]
            assert [row[1] for row in short["curves"][metric][axis]] == pytest.approx([
                -row[1] for row in long["curves"][metric][axis]
            ])
