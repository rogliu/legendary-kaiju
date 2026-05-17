from __future__ import annotations
from typing import Annotated, Literal
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    kalshi_key_id: str = Field(validation_alias="KALSHI_KEY_ID")
    kalshi_private_key: SecretStr = Field(validation_alias="KALSHI_PRIVATE_KEY")
    mode: Literal["backtest", "shadow-paper", "live"] = Field(
        default="shadow-paper", validation_alias="KAIJU_MODE"
    )
    db_path: str = Field(default="./kaiju.sqlite", validation_alias="KAIJU_DB_PATH")
    bankroll_usd: float = Field(default=500.0, validation_alias="KAIJU_BANKROLL_USD")
    cities: Annotated[list[str], NoDecode] = Field(default=["KNYC"], validation_alias="KAIJU_CITIES")
    live_arm_token: SecretStr = Field(default=SecretStr(""), validation_alias="KAIJU_LIVE_ARM_TOKEN")

    net_edge_threshold: float = Field(
        default=0.08, validation_alias="KAIJU_NET_EDGE_THRESHOLD"
    )
    kelly_fraction: float = Field(
        default=0.25, validation_alias="KAIJU_KELLY_FRACTION"
    )
    max_bankroll_frac_per_event: float = Field(
        default=0.10, validation_alias="KAIJU_MAX_BANKROLL_FRAC_PER_EVENT"
    )
    max_events_per_day: int = Field(
        default=8, validation_alias="KAIJU_MAX_EVENTS_PER_DAY"
    )
    max_contracts_per_market: int = Field(
        default=50, validation_alias="KAIJU_MAX_CONTRACTS_PER_MARKET"
    )
    max_daily_loss_usd: float = Field(
        default=50.0, validation_alias="KAIJU_MAX_DAILY_LOSS_USD"
    )
    paper_proof_days: int = Field(
        default=30, validation_alias="KAIJU_PAPER_PROOF_DAYS"
    )

    @field_validator("cities", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [s for s in (x.strip() for x in v.split(",")) if s]
        return v

    @property
    def live_armed(self) -> bool:
        return bool(self.live_arm_token.get_secret_value().strip())

    @model_validator(mode="after")
    def _live_guard(self):
        """Safety gate: block live mode unless a real arm token is set."""
        if self.mode == "live" and not self.live_armed:
            raise ValueError("live mode requires KAIJU_LIVE_ARM_TOKEN to be set")
        return self
