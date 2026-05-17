import pathlib
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
