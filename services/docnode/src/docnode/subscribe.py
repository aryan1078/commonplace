"""Delivery of committed operations to live subscribers.

Subscriptions only observe the replicated state; they are not part of it.
Writers must never wait for a reader, so each subscriber gets a bounded
queue, and a subscriber whose queue is full is dropped (it can subscribe
again from the last revision it received) instead of slowing everyone down.
"""

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class SubscriberTooSlow(Exception):
    """The subscriber fell too far behind and was dropped."""


class Subscription(Generic[T]):
    """Queued items for one subscriber, in commit order.

    Read `backlog` first (what was committed between the requested revision
    and subscribing), then call `next()` until it returns None.
    """

    def __init__(self, backlog: list[T], buffer: int, unregister: Callable[["Subscription[T]"], None]):
        self.backlog = backlog
        self.error: Exception | None = None  # why it ended; None if closed normally
        self._buffer = buffer
        self._queue: deque[T] = deque()
        self._unregister = unregister
        self._closed = False
        self._wakeup = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed

    def deliver(self, item: T) -> bool:
        """Queues item without blocking. Returns False if the subscriber was
        dropped because its queue was full; the caller must then forget it."""
        if self._closed:
            return False
        if len(self._queue) >= self._buffer:
            self._end(SubscriberTooSlow("subscriber fell too far behind"))
            return False
        self._queue.append(item)
        self._wakeup.set()
        return True

    def get_nowait(self) -> T | None:
        """The next queued item, or None if nothing is queued right now."""
        return self._queue.popleft() if self._queue else None

    async def next(self) -> T | None:
        """Waits for the next item. Returns None once the subscription has
        ended and everything queued before that has been read."""
        while True:
            if self._queue:
                return self._queue.popleft()
            if self._closed:
                return None
            self._wakeup.clear()
            await self._wakeup.wait()

    def close(self) -> None:
        """Stops delivery. Safe to call more than once."""
        if not self._closed:
            self._unregister(self)
            self._end(None)

    def _end(self, error: Exception | None) -> None:
        if not self._closed:
            self._closed = True
            self.error = error
            self._wakeup.set()
