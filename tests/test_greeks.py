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


def test_curves_use_selected_and_cycle_implied_volatility():
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
    assert len(result["spot_curve"]) == 61
    assert len(result["volatility_curve"]) == 61
    assert [row[2] for row in result["time_curve"]] == [20.0, 30.0]
    assert set(result["curves"]) == {"price", "delta", "gamma", "theta", "vega"}
    assert all(set(curves) == {"spot", "volatility", "time"}
               for curves in result["curves"].values())
