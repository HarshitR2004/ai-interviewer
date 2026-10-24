# AI Interviewer

An API-only Python 3.12+ demonstration: upload a resume PDF, generate a candidate profile
and interview plan, then run a live text or optional audio interview. A future client
can consume the JSON API. This repository serves no frontend.

## Run

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe -m pip install --no-deps -e ".[test]"
Copy-Item .env.example .env
```

Preserve an existing `.env`. Configure `LLM_BASE_URL` including its API prefix,
`LLM_MODEL`, and optional `LLM_API_KEY`. Enable `LIVE_REASONING_ENABLED=true` for live
assessment. Start one demo process:

```powershell
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

On Linux/macOS use `.venv/bin/python` and `cp .env.example .env`.
`GET /openapi.json` describes the API. Root, static asset URLs, Swagger UI, and ReDoc
return 404. Preparation requests wait for generation; no status polling is necessary.

## Documents and demo behavior

Completed preparations live under `DATA_DIR/demo/candidates/<id>/` as `resume.pdf`,
`persona.md`, and `interview-plan.md`. Markdown is authoritative and reloadable after
restart. There is no saved preparation JSON, database, revision history, or recovery job.
Existing data outside this demo subtree is not read, migrated, or deleted.

Live sessions exist only in memory. Restarting the server loses them; create a new
session from a saved preparation. One operation per session is allowed, including reads
and synthesis; overlapping requests return 409. Clients should wait for each response.
Do not automatically retry answers: event receipts and pending-answer correction are
not supported. Deadlines are enforced when a session is accessed and after model calls,
not by a background timer. This is intended for one demo server process.

## Optional speech

Set `SPEECH_ENABLED=true` and `STT_BASE_URL` and/or `TTS_BASE_URL`, with optional separate
keys. STT accepts multipart WAV at `POST /transcribe` and returns `{"text":"..."}`.
TTS accepts `{"text":"..."}` at `POST /synthesize`, returning 16-bit PCM WAV.
Provider services are user-managed. Resume text/answers go to the configured model;
audio/text goes to configured speech providers. PDF subprocess isolation, complexity
limits, and timeouts remain in place; they are not an antivirus or OS sandbox.

## Verify

```powershell
.venv/Scripts/python.exe -m ruff check backend tests
.venv/Scripts/python.exe -m ruff format --check backend tests
.venv/Scripts/python.exe -m mypy backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m build --wheel --no-isolation
```

Tests block real HTTP requests. See [Markdown format](docs/markdown-format.md), [API](docs/api.md), and
[low-level design/onboarding](docs/low-level-design.md).
