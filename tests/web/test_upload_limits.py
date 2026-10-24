import asyncio

from backend.web.upload_limits import MAX_REQUEST_BYTES, ResumeUploadLimits


async def invoke(chunks, headers=(), active=0):
    called, messages = [], []

    async def app(scope, receive, send):
        called.append(True)
        await receive()

    middleware = ResumeUploadLimits(app)
    middleware.active = active
    scope = {"type": "http", "method": "POST", "path": "/api/candidates", "headers": headers}
    iterator = iter(chunks)

    async def receive():
        return next(iterator)

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    return called, messages, middleware.active


async def test_declared_oversize_is_rejected_before_reading():
    called, messages, active = await invoke(
        [], [(b"content-length", str(MAX_REQUEST_BYTES + 1).encode())]
    )
    assert not called and messages[0]["status"] == 413 and active == 0


async def test_chunked_and_underreported_bodies_cannot_bypass_limit():
    for headers in ([], [(b"content-length", b"1")]):
        called, messages, active = await invoke(
            [
                {"type": "http.request", "body": b"x" * MAX_REQUEST_BYTES, "more_body": True},
                {"type": "http.request", "body": b"x", "more_body": False},
            ],
            headers,
        )
        assert not called and messages[0]["status"] == 413 and active == 0


async def test_normal_request_and_disconnect_release_slot():
    called, _, active = await invoke([{"type": "http.request", "body": b"test"}])
    assert called and active == 0
    called, _, active = await invoke([{"type": "http.disconnect"}])
    assert not called and active == 0


async def test_busy_uploads_are_rejected_before_body_read():
    called, messages, active = await invoke([], active=2)
    assert not called and messages[0]["status"] == 429 and active == 2


async def test_slow_upload_times_out(monkeypatch):
    from backend.web import upload_limits

    timeout = asyncio.timeout
    monkeypatch.setattr(upload_limits.asyncio, "timeout", lambda seconds: timeout(0.01))
    messages = []

    async def app(*args):
        raise AssertionError("Timed out upload reached parser")

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    middleware = ResumeUploadLimits(app)
    await middleware(
        {"type": "http", "method": "POST", "path": "/api/candidates", "headers": []}, receive, send
    )
    assert messages[0]["status"] == 408 and middleware.active == 0
