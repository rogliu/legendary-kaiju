import json
import respx
import httpx

from kaiju.data.obs import IEMClient


def test_official_daily_max_parses_int():
    fx = json.load(open("tests/fixtures/iem_knyc_dailymax.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=fx)
        )
        v = IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2026-05-14")
        assert isinstance(v, int) and v == 66  # known value in committed fixture


def test_observed_max_so_far_returns_int():
    fx = json.load(open("tests/fixtures/iem_knyc_asos.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=fx)
        )
        m = IEMClient().observed_max_so_far("NYC", "2026-05-14")
        assert isinstance(m, int)
