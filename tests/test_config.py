import pytest
from kaiju.config import Settings

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "KEY")
    monkeypatch.setenv("KAIJU_MODE", "shadow-paper")
    monkeypatch.setenv("KAIJU_BANKROLL_USD", "500")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC,KORD")
    s = Settings()
    assert s.mode == "shadow-paper"
    assert s.cities == ["KNYC", "KORD"]
    assert s.bankroll_usd == 500.0
    assert s.live_armed is False  # no token => not armed

def test_live_requires_arm_token(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "k")
    monkeypatch.setenv("KAIJU_MODE", "live")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC")
    monkeypatch.setenv("KAIJU_LIVE_ARM_TOKEN", "")
    with pytest.raises(ValueError, match="live mode requires"):
        Settings()


def test_whitespace_arm_token_not_armed(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "k")
    monkeypatch.setenv("KAIJU_MODE", "live")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC")
    monkeypatch.setenv("KAIJU_LIVE_ARM_TOKEN", "   ")
    with pytest.raises(ValueError, match="live mode requires"):
        Settings()


def test_secrets_not_in_repr(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "SUPERSECRETPEM")
    monkeypatch.setenv("KAIJU_MODE", "backtest")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC")
    s = Settings()
    assert "SUPERSECRETPEM" not in repr(s)
    assert s.kalshi_private_key.get_secret_value() == "SUPERSECRETPEM"


def test_empty_cities_filtered(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "k")
    monkeypatch.setenv("KAIJU_MODE", "backtest")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC, ,KORD,")
    s = Settings()
    assert s.cities == ["KNYC", "KORD"]


def test_frozen_blocks_mutation(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "k")
    monkeypatch.setenv("KAIJU_MODE", "backtest")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC")
    s = Settings()
    with pytest.raises(Exception):
        s.mode = "live"
