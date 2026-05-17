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
