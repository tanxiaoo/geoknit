"""Thread-safe fan-out of events to WebSocket clients (SPEC 9, ``/ws``).

Events come from the run thread and from request threads; each WebSocket
connection owns an ``asyncio.Queue`` on its event loop, filled with
``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

Message = dict[str, Any]


class Subscription:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[Message] = asyncio.Queue()

    def put(self, msg: Message) -> None:
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)
        except RuntimeError:  # the connection's loop is closed
            pass


class Broadcaster:
    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()

    def subscribe(self) -> Subscription:
        sub = Subscription(asyncio.get_running_loop())
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def publish(self, msg: Message) -> None:
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub.put(msg)
