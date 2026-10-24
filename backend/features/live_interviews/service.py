import asyncio
import copy
import logging
import time
from collections.abc import Callable

from . import graph
from .models import Decision, EngineError
from .ports import PlanSource, Reasoner
from .storage import SQLiteRepository

log = logging.getLogger(__name__)


class LiveInterviewService:
    def __init__(
        self,
        repository: SQLiteRepository,
        source: PlanSource,
        reasoner: Reasoner | None,
        *,
        clock: Callable[[], float] = time.time,
        timeout: float = 15,
    ):
        self.repository = repository
        self.source = source
        self.reasoner = reasoner
        self.clock = clock
        self.timeout = timeout

    async def initialize(self):
        await self.repository.initialize()
        await self.repository.close_unfinished(self.clock(), restart=True)

    async def expire(self):
        await self.repository.close_unfinished(self.clock())

    async def create(self, request):
        await self.expire()
        existing = await self.repository.create(request, None, self.clock())
        if existing is not None:
            return existing
        source = await self.source.load(request.candidate_id)
        return await self.repository.create(request, source, self.clock())

    async def get(self, session_id):
        await self.expire()
        return graph.public_session(await self.repository.get(session_id))

    async def answer(self, session_id, event, *, audio=False):
        if self.reasoner is None:
            raise EngineError(503, "Live reasoning is disabled. No answer was saved.")
        await self.expire()
        snapshot, existing = await self.repository.accept(
            session_id, event, self.clock(), audio=audio
        )
        if existing is not None:
            return existing
        unavailable = False
        try:
            decision = await asyncio.wait_for(
                self.reasoner.assess(copy.deepcopy(snapshot), event.answer), timeout=self.timeout
            )
            decision = Decision.model_validate(decision)
        except Exception as exc:
            log.warning("Live assessment unavailable (%s)", type(exc).__name__)
            unavailable = True
            decision = graph.fallback(snapshot)
        return await self.repository.commit(
            snapshot, event.event_id, decision, self.clock(), unavailable
        )

    async def end(self, session_id, event):
        return await self.repository.end(session_id, event, self.clock())
