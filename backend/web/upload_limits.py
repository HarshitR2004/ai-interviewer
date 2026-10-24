"""Bound resume requests before FastAPI's multipart parser receives their bodies."""

import asyncio

from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 10 * 1024 * 1024 + 64 * 1024


class ResumeUploadLimits:
    def __init__(self, app):
        self.app = app
        self.active = 0

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") != "/api/candidates"
        ):
            return await self.app(scope, receive, send)

        async def reject(status, message):
            await JSONResponse({"detail": message}, status_code=status)(scope, receive, send)

        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            return await reject(400, "Invalid request length.")
        if declared > MAX_REQUEST_BYTES:
            return await reject(413, "The resume upload request is too large.")
        if self.active >= 2:
            return await reject(429, "Resume uploads are busy. Please try again shortly.")
        self.active += 1
        try:
            # The same bound applies to chunked requests and false Content-Length headers.
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                            return await reject(413, "The resume upload request is too large.")
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "The resume upload timed out.")

            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, bounded_receive, send)
        finally:
            self.active -= 1
