"""Per-client rate limiting, held in memory for a single replica."""

import time
from collections import OrderedDict, deque

from starlette.requests import Request


def client_ip(request: Request) -> str:
    """The address Azure's ingress saw.

    The ingress appends the address it saw to X-Forwarded-For, so only the last
    entry is trustworthy. Anything before it may have been sent by the client.
    """
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    last_entry = forwarded.rsplit(",", 1)[-1].strip()
    return last_entry or request.client.host


class RateLimiter:
    """Allow `limit` hits per client in any rolling `window_seconds`.

    Memory is bounded: at most `max_clients` clients, each holding at most
    `limit` timestamps. The least recently seen client is dropped first.
    Only call this from the event loop: it has no lock because it never awaits.
    """

    def __init__(self, limit=30, window_seconds=60, max_clients=10_000, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.clock = clock
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, client: str) -> bool:
        now = self.clock()
        hits = self.hits.setdefault(client, deque())
        self.hits.move_to_end(client)
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()

        allowed = len(hits) < self.limit
        if allowed:
            hits.append(now)
        if len(self.hits) > self.max_clients:
            self.hits.popitem(last=False)
        return allowed
