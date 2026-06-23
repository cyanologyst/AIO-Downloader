from __future__ import annotations

import asyncio


class QueueService:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.active = 0
        self._condition = asyncio.Condition()

    async def acquire(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self.active < self.limit)
            self.active += 1

    async def release(self) -> None:
        async with self._condition:
            self.active = max(0, self.active - 1)
            self._condition.notify_all()

    async def set_limit(self, limit: int) -> None:
        async with self._condition:
            self.limit = max(1, limit)
            self._condition.notify_all()
