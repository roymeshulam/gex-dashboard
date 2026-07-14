from __future__ import annotations

import datetime

from app.engine import sentiment
from app.models import ChainData, VixData
from tests.conftest import EXP_A, mk

TODAY = datetime.date(2026, 6, 9)
TS = datetime.datetime(2026, 6, 9, 16, 14, tzinfo=datetime.timezone.utc)


def _chain(contracts, change_pct=0.0, iv30=16.0, iv30_chg=0.0):
    return ChainData(symbol="SPX", spot=7400.0, change_pct=change_pct,
                     iv30=iv30, iv30_change_pct=iv30_chg, data_ts=TS,
                     last_trade_time=TS, contracts=contracts)


def _totals(call_vol=100, put_vol=100, call_oi=100, put_oi=120,
            net_gex=1e9, call_dex=1e9, put_dex=-1e9):
    return {"net_gex": net_gex, "call_gex": abs(net_gex), "put_gex": -1.0,
            "net_dex": call_dex + put_dex, "call_dex": call_dex, "put_dex": put_dex,
            "call_vol": call_vol, "put_vol": put_vol,
            "call_oi": call_oi, "put_oi": put_oi}


def test_max_pain_toy_chain():
    cs = [mk("C", 90, oi=10, expiry=EXP_A), mk("C", 100, oi=10, expiry=EXP_A),
          mk("P", 100, oi=10, expiry=EXP_A), mk("P", 110, oi=10, expiry=EXP_A)]
    assert sentiment.max_pain(cs, EXP_A) == 100.0


def test_max_pain_no_oi():
    cs = [mk("C", 90, oi=0, expiry=EXP_A)]
    assert sentiment.max_pain(cs, EXP_A) is None


def test_iv_skew():
    exp = TODAY + datetime.timedelta(days=30)
    cs = [mk("P", 7200, oi=10, delta=-0.25, iv=0.20, expiry=exp),
          mk("C", 7600, oi=10, delta=0.25, iv=0.16, expiry=exp)]
    skew = sentiment.iv_skew_25d(cs, TODAY)
    assert abs(skew - 4.0) < 1e-9


def test_pcr_component_neutral_and_bullish():
    s_neutral = sentiment.compute_sentiment(
        _chain([]), _totals(call_vol=100, put_vol=100), flip=None, vix=None,
        today=TODAY, zero_dte_share=0.0)
    pcr = next(c for c in s_neutral["components"] if c["name"] == "pcr_volume")
    assert pcr["score"] == 0.0

    s_bull = sentiment.compute_sentiment(
        _chain([]), _totals(call_vol=100, put_vol=60), flip=None, vix=None,
        today=TODAY, zero_dte_share=0.0)
    pcr = next(c for c in s_bull["components"] if c["name"] == "pcr_volume")
    assert pcr["score"] == 100.0


def test_vix_component_present_and_volatility_renormalization():
    vix = VixData(level=20.0, change_pct=-5.0, ts=TS)
    with_vix = sentiment.compute_sentiment(
        _chain([]), _totals(), flip=7300.0, vix=vix, today=TODAY, zero_dte_share=0.0)
    names = [c["name"] for c in with_vix["components"]]
    assert "vix_change" in names
    vc = next(c for c in with_vix["components"] if c["name"] == "vix_change")
    assert vc["score"] == -100.0  # falling VIX indicates greater stability

    without_vix = sentiment.compute_sentiment(
        _chain([]), _totals(), flip=7300.0, vix=None, today=TODAY, zero_dte_share=0.0)
    assert "vix_change" not in [c["name"] for c in without_vix["components"]]
    # Each group is independently normalized.
    for s in (with_vix, without_vix):
        for group in (s["direction"], s["volatility"]):
            assert abs(sum(c["contribution"] for c in group["components"])
                       - group["score"]) < 0.5


def test_gamma_regime_above_flip_is_stable():
    s = sentiment.compute_sentiment(
        _chain([]), _totals(), flip=7250.0, vix=None, today=TODAY, zero_dte_share=0.0)
    g = next(c for c in s["components"] if c["name"] == "gamma_regime")
    assert g["score"] == -100.0  # spot 2% above flip, saturates as stable


def test_missing_flip_is_not_replaced_with_maximum_bearish_score():
    s = sentiment.compute_sentiment(
        _chain([]), _totals(net_gex=-5e9), flip=None, vix=None,
        today=TODAY, zero_dte_share=0.0)
    assert "gamma_regime" not in [c["name"] for c in s["components"]]
    assert "gamma flip" in s["confidence"]["missing_inputs"]
    assert s["volatility"]["confidence"] != "Medium"


def test_labels():
    bull = sentiment.compute_sentiment(
        _chain([], change_pct=2.0), _totals(call_vol=100, put_vol=40),
        flip=7200.0, vix=VixData(20.0, -6.0, TS), today=TODAY, zero_dte_share=0.0)
    assert bull["score"] > 15
    assert bull["label"] in ("Bullish pressure", "Strong bullish pressure")


def test_direction_and_volatility_are_separate_scores():
    result = sentiment.compute_sentiment(
        _chain([], change_pct=1.0, iv30_chg=8.0),
        _totals(call_vol=100, put_vol=60), flip=7500.0,
        vix=VixData(20.0, 5.0, TS), today=TODAY, zero_dte_share=0.0)
    assert result["direction"]["score"] > 0
    assert result["volatility"]["score"] > 0
    assert result["direction"]["label"] != result["volatility"]["label"]


def test_missing_market_changes_are_excluded_not_scored_as_zero():
    result = sentiment.compute_sentiment(
        _chain([], change_pct=None, iv30=None, iv30_chg=None),
        _totals(), flip=None, vix=VixData(20.0, None, TS),
        today=TODAY, zero_dte_share=0.0)
    names = {c["name"] for c in result["components"]}
    assert "price_momentum" not in names
    assert "iv30_change" not in names
    assert "vix_change" not in names
    assert result["volatility"]["score"] is None
    assert result["confidence"]["level"] == "Insufficient"
