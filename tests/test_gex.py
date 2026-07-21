from __future__ import annotations

import datetime

from app import config
from app.engine import flow, gex
from tests.conftest import EXP_A, EXP_B, mk


def test_contract_gex_anchor():
    # gamma .001 x OI 1000 x 100 x 7400^2 x 0.01 = $54.76M
    c = mk("C", 7400, gamma=0.001, oi=1000)
    assert gex.contract_gex(c, 7400.0) == 54_760_000.0


def test_put_gex_negative():
    c = mk("P", 7400, gamma=0.001, oi=1000)
    assert gex.contract_gex(c, 7400.0) == -54_760_000.0


def test_dex_sign_via_delta():
    call = mk("C", 7400, oi=10, delta=0.5)
    put = mk("P", 7400, oi=10, delta=-0.5)
    assert gex.contract_dex(call, 7400.0) > 0
    assert gex.contract_dex(put, 7400.0) < 0


def test_choose_step_spx():
    assert gex.choose_step(7386.0, 0.08, [5.0, 10.0, 25.0, 50.0, 100.0], 55) == 25.0


def test_choose_step_small_underlying():
    assert gex.choose_step(735.0, 0.10, [1.0, 2.0, 5.0, 10.0], 55) == 5.0


def test_bucket_strike():
    assert gex.bucket_strike(7412.0, 25.0) == 7400.0
    assert gex.bucket_strike(7413.0, 25.0) == 7425.0


def test_totals_split():
    cs = [mk("C", 7400, gamma=0.001, oi=1000, volume=100, delta=0.5),
          mk("P", 7400, gamma=0.001, oi=500, volume=200, delta=-0.5)]
    t = gex.totals(cs, 7400.0)
    assert t["call_gex"] == 54_760_000.0
    assert t["put_gex"] == -27_380_000.0
    assert t["net_gex"] == 27_380_000.0
    assert t["call_vol"] == 100 and t["put_vol"] == 200
    assert t["call_oi"] == 1000 and t["put_oi"] == 500


def test_heatmap_structure_and_conservation():
    spot = 7400.0
    cfg = config.SPX
    cs = [
        mk("C", 7400, gamma=0.001, oi=1000, expiry=EXP_A),
        mk("P", 7350, gamma=0.0009, oi=1500, expiry=EXP_A),
        mk("C", 7412, gamma=0.0005, oi=200, expiry=EXP_A),   # off-step, folds to 7400
        mk("C", 7500, gamma=0.0005, oi=3000, expiry=EXP_B),
    ]
    hm = gex.build_heatmap(cs, spot, cfg)

    assert hm["expiries"] == [EXP_A.isoformat(), EXP_B.isoformat()]
    assert hm["strikes"] == sorted(hm["strikes"], reverse=True)
    assert hm["step"] == 25.0
    assert hm["strikes"][hm["spot_row"]] == 7400.0

    # Folding conserves the windowed total (within rounding).
    total_cells = sum(v for _, _, v in hm["cells"])
    expected = sum(gex.contract_gex(c, spot) for c in cs) / 1e6
    assert abs(total_cells - expected) < 0.5


def test_expiry_dropdowns_respect_configured_caps():
    start = datetime.date(2099, 1, 1)
    contracts = [
        mk("C", 7400, gamma=0.001, oi=10, volume=10,
           expiry=start + datetime.timedelta(days=i))
        for i in range(31)
    ]
    cfg = config.SPX

    heatmap = gex.build_heatmap(contracts, 7400.0, cfg)
    strikemap = gex.build_strikemap(contracts, 7400.0, cfg)
    option_flow = flow.build_flow(contracts, 7400.0, cfg)

    assert len(heatmap["expiries"]) == 14
    assert len(strikemap["expiries"]) == config.MAX_STRIKEMAP_EXPIRATIONS
    assert len(option_flow["expiries"]) == config.MAX_FLOW_EXPIRATIONS
    assert strikemap["expiries"][-1] == (
        start + datetime.timedelta(days=config.MAX_STRIKEMAP_EXPIRATIONS - 1)
    ).isoformat()
    assert option_flow["expiries"][-1] == (
        start + datetime.timedelta(days=config.MAX_FLOW_EXPIRATIONS - 1)
    ).isoformat()


def test_flow_includes_open_interest_and_available_bid_ask_spreads():
    cs = [
        mk("C", 7400, oi=100, volume=0, bid=1.0, ask=1.4),
        mk("C", 7400, oi=200, volume=0, bid=2.0, ask=2.2),
        mk("P", 7400, oi=300, volume=0, bid=0.0, ask=0.1),
        mk("P", 7400, oi=400, volume=0, bid=0.0, ask=0.0),
    ]

    row = flow.build_flow(cs, 7400.0, config.SPX)["by_expiry"]["ALL"]["rows"][0]

    assert row[5:7] == [300, 700]
    assert row[7] == 0.3
    assert row[8] == 0.1


def test_flow_expected_move_uses_nearest_call_and_put_mids_per_expiry():
    other_expiry = EXP_A + datetime.timedelta(days=7)
    cs = [
        mk("C", 7390, bid=19.0, ask=21.0, expiry=EXP_A),
        mk("P", 7410, bid=29.0, ask=31.0, expiry=EXP_A),
        mk("C", 7500, bid=99.0, ask=101.0, expiry=EXP_A),
        mk("P", 7400, bid=1.0, ask=2.0, expiry=other_expiry),
    ]

    result = flow.build_flow(
        cs, 7400.0, config.SPX, today=EXP_A - datetime.timedelta(days=28)
    )["by_expiry"]

    assert result["ALL"]["expected_move"] is None
    assert result[EXP_A.isoformat()]["expected_move"] == {
        "lower": 7350.0,
        "upper": 7450.0,
        "straddle": 50.0,
        "call_strike": 7390,
        "put_strike": 7410,
        "atm_iv_pct": 20.0,
        "standard_deviation": 409.92,
        "sd_lower": 7000.0,
        "sd_upper": 7800.0,
    }
    assert result[other_expiry.isoformat()]["expected_move"] is None


def test_flow_builds_atm_iv_term_structure_by_dte():
    cs = [
        mk("C", 7400, bid=10.0, ask=12.0, iv=0.18, expiry=EXP_A),
        mk("P", 7400, bid=11.0, ask=13.0, iv=0.22, expiry=EXP_A),
    ]

    result = flow.build_flow(
        cs, 7400.0, config.SPX, today=EXP_A - datetime.timedelta(days=28)
    )

    assert result["term_structure"] == [{
        "expiry": EXP_A.isoformat(), "dte": 28, "atm_iv_pct": 20.0,
    }]
    assert result["expected_move_term_structure"] == [{
        "expiry": EXP_A.isoformat(), "dte": 28,
        "lower": 7375.0, "upper": 7425.0,
    }]


def test_zero_dte_empty_state():
    cs = [mk("C", 7400, gamma=0.001, oi=10, expiry=EXP_A)]
    z = gex.build_zero_dte(cs, 7400.0, config.SPX,
                           today=datetime.date(2026, 6, 9))
    assert z["available"] is False
    assert z["next_expiry"] == EXP_A.isoformat()


def test_zero_dte_available():
    today = datetime.date(2026, 6, 9)
    cs = [mk("C", 7400, gamma=0.001, oi=100, volume=500, expiry=today),
          mk("P", 7390, gamma=0.001, oi=100, volume=300, expiry=today),
          mk("C", 7450, gamma=0.001, oi=100, volume=200, expiry=EXP_A)]
    z = gex.build_zero_dte(cs, 7400.0, config.SPX, today=today)
    assert z["available"] is True
    assert z["stats"]["dte_volume"] == 800
    assert z["stats"]["dte_share_pct"] == 80.0
    assert len(z["rows"]) > 0


def test_build_expiry_levels():
    cs = [
        mk("P", 7300, gamma=0.001, oi=100, expiry=EXP_A),
        mk("C", 7500, gamma=0.001, oi=200, expiry=EXP_A),
        mk("C", 7600, gamma=0.001, oi=100, expiry=EXP_B),
    ]

    levels = gex.build_expiry_levels(cs, 7400.0)

    assert levels[EXP_A.isoformat()]["call_wall"] == 7500
    assert levels[EXP_A.isoformat()]["put_wall"] == 7300
    assert levels[EXP_B.isoformat()]["call_wall"] == 7600
    assert levels[EXP_B.isoformat()]["put_wall"] is None
