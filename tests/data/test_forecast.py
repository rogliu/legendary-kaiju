import pathlib

import pytest

from kaiju.data.forecast import nbm_percentiles_from_fixture, gefs_members_from_fixture

FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures"


def test_nbm_fixture_parses_monotone():
    pct = nbm_percentiles_from_fixture(str(FIX / "nbm_knyc.json"))
    ks = sorted(pct)
    assert len(pct) >= 5
    assert all(0 <= k <= 100 for k in pct)
    assert all(isinstance(pct[k], float) for k in pct)
    assert pct[ks[0]] <= pct[ks[-1]]            # monotone non-decreasing in percentile
    assert all(pct[a] <= pct[b] for a, b in zip(ks, ks[1:]))


def test_gefs_fixture_member_list():
    m = gefs_members_from_fixture(str(FIX / "gefs_knyc.json"))
    assert len(m) >= 20 and all(isinstance(x, float) for x in m)


def test_nbm_parser_empty_dict(tmp_path):
    p = tmp_path / "e.json"
    p.write_text("{}")
    assert nbm_percentiles_from_fixture(str(p)) == {}


def test_nbm_parser_non_numeric_value_raises(tmp_path):
    p = tmp_path / "b.json"
    p.write_text('{"50":"warm"}')
    with pytest.raises(ValueError):
        nbm_percentiles_from_fixture(str(p))


def test_gefs_parser_missing_members_key_raises(tmp_path):
    p = tmp_path / "g.json"
    p.write_text('{"nope":[1.0]}')
    with pytest.raises(KeyError):
        gefs_members_from_fixture(str(p))
