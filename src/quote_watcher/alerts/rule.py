"""AlertRule + AlertKind + AlertsFile schema. Used by AlertEngine."""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

import asteval
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertKind(StrEnum):
    THRESHOLD = "threshold"
    INDICATOR = "indicator"
    EVENT = "event"
    COMPOSITE = "composite"


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class AlertRule(_Base):
    id: str
    kind: AlertKind
    expr: str
    cooldown_min: int = 30
    severity: Literal["info", "warning", "critical"] = "warning"

    ticker: str | None = None
    name: str | None = None
    target_kind: Literal["ticker", "sector"] = "ticker"
    sector: str | None = None
    holding: str | None = None
    portfolio: bool = False
    needs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_target(self) -> AlertRule:
        if self.kind in (AlertKind.THRESHOLD, AlertKind.INDICATOR):
            if self.ticker is None:
                raise ValueError(f"rule {self.id}: kind={self.kind.value} requires ticker")
        elif self.kind == AlertKind.EVENT:
            if self.target_kind == "ticker" and self.ticker is None:
                raise ValueError(
                    f"rule {self.id}: event with target_kind=ticker requires ticker"
                )
            if self.target_kind == "sector" and not self.sector:
                raise ValueError(
                    f"rule {self.id}: event with target_kind=sector requires sector"
                )
        elif self.kind == AlertKind.COMPOSITE and not self.holding and not self.portfolio:
            raise ValueError(
                f"rule {self.id}: composite requires holding or portfolio=true"
            )
        return self


class AlertsFile(_Base):
    alerts: list[AlertRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> AlertsFile:
        seen: set[str] = set()
        for r in self.alerts:
            if r.id in seen:
                raise ValueError(f"duplicate alert id: {r.id}")
            seen.add(r.id)
        return self

    @model_validator(mode="after")
    def _expr_syntax(self) -> AlertsFile:
        for r in self.alerts:
            interp = asteval.Interpreter(no_print=True, no_assert=True)
            try:
                interp.parse(r.expr)
            except SyntaxError as e:
                raise ValueError(f"rule {r.id}: expr syntax error: {e}") from e
            if interp.error:
                msgs = "; ".join(str(e.get_error()) for e in interp.error)
                raise ValueError(f"rule {r.id}: expr syntax error: {msgs}")
        return self
