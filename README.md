# AI Interviewer

## Startup

Requires Python 3.12 or later.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e ".[test]"
Copy-Item .env.example .env
```

Configure `LLM_BASE_URL`, `LLM_MODEL`, and, if required, `LLM_API_KEY` in `.env`.
Then start the API:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

On Linux or macOS, replace `.venv\Scripts\python.exe` with `.venv/bin/python` and
`Copy-Item .env.example .env` with `cp .env.example .env`.
