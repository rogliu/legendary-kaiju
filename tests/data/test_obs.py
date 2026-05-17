import json
import pathlib

import httpx
import pytest
import respx

from kaiju.data.obs import IEMClient

FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures"


def test_official_daily_max_parses_int():
    fx = json.load(open(FIX / "iem_knyc_dailymax.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=fx)
        )
        v = IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2026-05-14")
        assert isinstance(v, int) and v == 66  # known value in committed fixture


def test_observed_max_so_far_returns_int():
    fx = json.load(open(FIX / "iem_knyc_asos.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=fx)
        )
        m = IEMClient().observed_max_so_far("NYC", "2026-05-14")
        assert isinstance(m, int)
        assert m == 65  # committed fixture max tmpf is 65.0


def test_official_daily_max_raises_on_missing_date():
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json={"data": []}))
        with pytest.raises(LookupError):
            IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2099-01-01")


def test_official_daily_max_raises_on_null_max_tmpf():
    body = {"data": [{"date": "2026-05-14", "max_tmpf": None, "tmpf_est": False}]}
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=body))
        with pytest.raises(LookupError):
            IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2026-05-14")


def test_official_daily_max_raises_on_preliminary_est():
    body = {"data": [{"date": "2026-05-14", "max_tmpf": 66, "tmpf_est": True}]}
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=body))
        with pytest.raises(LookupError):
            IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2026-05-14")


def test_observed_max_so_far_raises_on_empty_obs():
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json={"data": []}))
        with pytest.raises(LookupError):
            IEMClient().observed_max_so_far("NYC", "2026-05-14")


def test_official_daily_max_non_json_body_raises_lookup():
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, text="<html>maintenance</html>"))
        with pytest.raises(LookupError):
            IEMClient().official_daily_max("NYTNYC", "NYCLIMATE", "2026-05-14")
