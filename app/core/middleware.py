from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadBodyLimitMiddleware:
    """Bound multipart traffic before Starlette finishes parsing/spooling uploads."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        try:
            too_large = length is not None and int(length) > self.max_bytes
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length header."}, 400)(
                scope, receive, send
            )
            return
        if too_large:
            await JSONResponse({"detail": "Request body exceeds the size limit."}, 413)(
                scope, receive, send
            )
            return
        consumed = 0
        limit_exceeded = False

        async def bounded_receive() -> Message:
            nonlocal consumed, limit_exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    limit_exceeded = True
                    # Starlette closes partially spooled files for this exception type.
                    raise MultiPartException("Request body exceeds the size limit.")
            return message

        async def bounded_send(message: Message) -> None:
            if limit_exceeded and message["type"] == "http.response.start":
                message["status"] = 413
            await send(message)

        await self.app(scope, bounded_receive, bounded_send)
