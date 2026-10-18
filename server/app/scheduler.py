"""Tarefas que o servidor repete sozinho: varredura de tempo, checagem diária de documentos e limpeza."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.domain.clock import local_date
from app.runtime import Runtime
from app.services.sweeps import SweepReport

log = logging.getLogger("app.scheduler")

POSITION_MAX_AGE_S = 600.0          # motoqueiro sem mandar posição há 10 minutos sai do mapa
DAILY_DOCS_MARK = "docs"


def sweep_once(runtime: Runtime) -> SweepReport:
    """Uma rodada de varredura: cada corrida é gravada e publicada na hora, as que falham vão para o registro."""
    with runtime.session_factory() as session:
        unit = runtime.make_unit(session)

        def publish() -> None:
            runtime.publish(unit.events.drain(), unit.now)

        report = unit.sweeps.run(session, unit.now, after_commit=publish)
        session.commit()
        publish()
    for error in report.errors:
        log.error("varredura: %s", error)
    return report


def run_daily_jobs(runtime: Runtime) -> int | None:
    """Bloqueia quem está com CNH ou documento da moto vencido, uma vez por dia (dia da Bahia).

    Devolve quantos foram bloqueados, ou None se hoje já rodou. Se falhar, não marca o dia: tenta de novo.
    """
    today = local_date(runtime.clock())
    if runtime.job_marks.get(DAILY_DOCS_MARK) == today.isoformat():
        return None
    blocked = runtime.run(lambda unit: unit.riders.block_expired_documents(unit.session, local_date(unit.now)))
    runtime.job_marks.set(DAILY_DOCS_MARK, today.isoformat())
    return len(blocked)


def prune_positions(runtime: Runtime) -> int:
    return runtime.positions.prune(runtime.clock(), POSITION_MAX_AGE_S)


class Scheduler:
    def __init__(self, runtime: Runtime, *, sweep_interval_s: float = 3.0, maintenance_every_s: float = 60.0) -> None:
        self.runtime = runtime
        self.sweep_interval_s = sweep_interval_s
        self.maintenance_every_s = maintenance_every_s
        self._last_maintenance: float | None = None

    @staticmethod
    def _safely(label: str, step: Callable[[], object]) -> None:
        try:
            step()
        except Exception as exc:       # uma tarefa que falha não pode impedir as outras nem derrubar o servidor
            log.error("%s falhou: %s", label, exc, exc_info=True)

    def tick(self) -> None:
        """Uma volta: varre sempre; a cada `maintenance_every_s` faz também a tarefa diária e a limpeza."""
        self._safely("varredura", lambda: sweep_once(self.runtime))
        now = self.runtime.clock()
        if self._last_maintenance is None or now - self._last_maintenance >= self.maintenance_every_s:
            self._last_maintenance = now
            self._safely("tarefa diária", lambda: run_daily_jobs(self.runtime))
            self._safely("limpeza de posições", lambda: prune_positions(self.runtime))

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("volta do agendador falhou: %s", exc, exc_info=True)
            await asyncio.sleep(self.sweep_interval_s)
