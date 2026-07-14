from __future__ import annotations

import datetime

from app.engine import gex
from tests.conftest import mk


def _row(strike, net):
    return {"strike": strike, "call_gex": max(net, 0.0),
            "put_gex": min(net, 0.0), "net_gex": net}


AS_OF = datetime.datetime(2026, 6, 9, 12, tzinfo=datetime.timezone.utc)
EXPIRY = datetime.date(2026, 7, 9)


def test_gamma_flip_reprices_contract_gamma_across_spot():
    contracts = [
        mk("P", 90, oi=100, iv=0.20, expiry=EXPIRY),
        mk("C", 110, oi=100, iv=0.20, expiry=EXPIRY),
    ]
    flip = gex.find_gamma_flip(contracts, spot=100.0, as_of=AS_OF)
    assert flip is not None
    assert 98.0 < flip < 102.0
    assert abs(gex.net_gex_at_spot(contracts, flip, AS_OF)) < 1.0


def test_gamma_flip_none_when_exposure_is_one_sided():
    contracts = [mk("C", 100, oi=100, iv=0.20, expiry=EXPIRY)]
    assert gex.find_gamma_flip(contracts, spot=100.0, as_of=AS_OF) is None


def test_gamma_flip_ignores_contracts_without_iv_or_oi():
    contracts = [mk("C", 100, oi=100, iv=0.0, expiry=EXPIRY),
                 mk("P", 100, oi=0, iv=0.2, expiry=EXPIRY)]
    assert gex.find_gamma_flip(contracts, spot=100.0, as_of=AS_OF) is None


def test_walls():
    profile = [_row(7300.0, -80e6), _row(7400.0, 20e6), _row(7500.0, 90e6)]
    call_wall, put_wall = gex.find_walls(profile)
    assert call_wall == 7500.0
    assert put_wall == 7300.0


def test_walls_one_sided():
    profile = [_row(7400.0, 20e6), _row(7500.0, 90e6)]
    call_wall, put_wall = gex.find_walls(profile)
    assert call_wall == 7500.0
    assert put_wall is None


def test_strike_profile_aggregates_and_sorts():
    from tests.conftest import EXP_A, EXP_B, mk
    cs = [mk("C", 7400, gamma=0.001, oi=100, expiry=EXP_A),
          mk("P", 7400, gamma=0.002, oi=100, expiry=EXP_B),
          mk("C", 7300, gamma=0.001, oi=50, expiry=EXP_A)]
    prof = gex.strike_profile(cs, 7400.0)
    assert [r["strike"] for r in prof] == [7300.0, 7400.0]
    r7400 = prof[1]
    assert r7400["net_gex"] == r7400["call_gex"] + r7400["put_gex"]
    assert r7400["put_gex"] < 0

    # Single-expiry filter
    prof_a = gex.strike_profile(cs, 7400.0, expiry=EXP_A)
    assert [r["strike"] for r in prof_a] == [7300.0, 7400.0]
    assert prof_a[1]["put_gex"] == 0.0
