from datetime import date, datetime, timezone

from app.domain.clock import local_date, local_day_start


def test_dia_local_e_o_da_bahia():
    # 02:30 UTC do dia 9 ainda é 23:30 do dia 8 na Bahia (UTC-3).
    t = datetime(2026, 10, 9, 2, 30, tzinfo=timezone.utc).timestamp()
    assert local_date(t) == date(2026, 10, 8)


def test_inicio_do_dia_local():
    t = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc).timestamp()
    assert local_day_start(t) == datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc).timestamp()
