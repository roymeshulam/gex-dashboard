from __future__ import annotations

import datetime

import pytest

from app.providers import cboe


def test_parse_occ_spxw():
    root, exp, cp, strike = cboe.parse_occ("SPXW260612P07400000")
    assert (root, exp, cp, strike) == ("SPXW", datetime.date(2026, 6, 12), "P", 7400.0)


def test_parse_occ_spx_low_strike():
    root, exp, cp, strike = cboe.parse_occ("SPX260618C00200000")
    assert (root, exp, cp, strike) == ("SPX", datetime.date(2026, 6, 18), "C", 200.0)


def test_parse_occ_fractional_strike():
    root, exp, cp, strike = cboe.parse_occ("SPXW260620P00612500")
    assert (root, cp, strike) == ("SPXW", "P", 612.5)


@pytest.mark.parametrize("bad", ["", "BADSYMBOL", "SPX2606C00200000", "260618C00200000"])
def test_parse_occ_garbage(bad):
    with pytest.raises(cboe.OccParseError):
        cboe.parse_occ(bad)


def test_parse_timestamps():
    # last_trade_time fields are naive ET
    b = cboe.parse_et_timestamp("2026-06-09T12:28:07")
    assert b.hour == 12 and str(b.tzinfo) == "America/New_York"
    # the top-level snapshot timestamp is naive UTC
    a = cboe.parse_utc_timestamp("2026-06-09 23:04:44")
    assert a.hour == 23 and a.tzinfo == datetime.timezone.utc
    # 23:04 UTC == 19:04 ET same day
    assert a.astimezone(cboe.ET).hour == 19


def test_normalize_filters_and_coerces(mini_chain_raw):
    today = datetime.date(2026, 6, 9)
    chain = cboe.normalize(mini_chain_raw, today=today)

    assert chain.spot == 7400.0
    assert chain.iv30 == 16.12
    assert chain.change_pct == -0.26
    # 12 raw options: unrelated root, expired contract, and malformed symbol are gone.
    assert len(chain.contracts) == 9
    roots = {c.root for c in chain.contracts}
    assert roots == {"SPX", "SPXW"}

    # Null greeks coerced to 0.0, float OI cast to int.
    null_row = next(c for c in chain.contracts if c.strike == 7600.0)
    assert null_row.gamma == 0.0 and null_row.delta == 0.0
    assert isinstance(null_row.oi, int)

    assert chain.last_trade_time.hour == 16


def test_normalize_spot_fallback(mini_chain_raw):
    mini_chain_raw["data"]["current_price"] = 0
    mini_chain_raw["data"]["close"] = 0
    chain = cboe.normalize(mini_chain_raw, today=datetime.date(2026, 6, 9))
    assert chain.spot == 7419.0  # prev_day_close


def test_normalize_preserves_missing_market_changes(mini_chain_raw):
    mini_chain_raw["data"]["price_change_percent"] = None
    mini_chain_raw["data"]["iv30"] = None
    mini_chain_raw["data"]["iv30_change_percent"] = "bad"
    chain = cboe.normalize(mini_chain_raw, today=datetime.date(2026, 6, 9))
    assert chain.change_pct is None
    assert chain.iv30 is None
    assert chain.iv30_change_pct is None


def test_normalize_rejects_bad_schema():
    with pytest.raises(cboe.CboeParseError):
        cboe.normalize({"nope": 1})
