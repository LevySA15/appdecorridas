"""Dia local da operação (Bahia, UTC-3, sem horário de verão). Usado para contar as corridas do dia."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Bahia")


def local_date(epoch_s: float) -> date:
    return datetime.fromtimestamp(epoch_s, LOCAL_TZ).date()


def local_day_start(epoch_s: float) -> float:
    d = local_date(epoch_s)
    return datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ).timestamp()
