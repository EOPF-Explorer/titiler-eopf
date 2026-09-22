"""Refuse work the server cannot start, instead of queueing it."""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ConcurrencyLimitMiddleware:
    """Cap in-flight requests, answering 503 past the cap rather than queueing.

    Deliberately not uvicorn's `--limit-concurrency`, which checks before routing and so
    503s every path, `/_mgmt/ping` included. kubelet reads a 503 exactly as it reads a
    timeout, so that flag causes the container kill it appears to prevent.
    """

    def __init__(self, app: ASGIApp, limit: int, exempt: str = "/_mgmt/") -> None:
        """Cap concurrent requests at `limit`.

        `exempt` matches anywhere in the path, not as a prefix: uvicorn prepends
        root_path, so staging sees "/rstaging/_mgmt/ping".
        """
        self.app = app
        self.limit = limit
        self.exempt = exempt
        self.in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request through, or answer 503 if already at capacity."""
        if scope["type"] != "http" or self.exempt in scope["path"]:
            await self.app(scope, receive, send)
            return

        if self.in_flight >= self.limit:
            await PlainTextResponse(
                "Server is at capacity, please retry shortly.",
                status_code=503,
                headers={"Retry-After": "1"},
            )(scope, receive, send)
            return

        self.in_flight += 1  # no await since the test, so no lock needed
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1
