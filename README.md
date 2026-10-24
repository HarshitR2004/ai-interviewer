# AI Interviewer Workflow

A Python backend that turns a resume into a candidate profile, a role-specific
interview plan, and a live text interview. Bring your own LLM and optional STT/TTS
services. The browser UI provides a preparation demo; live interviews are API-driven.

## Setup

Requires Python 3.12+ and an OpenAI-compatible LLM endpoint with JSON output support.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Edit `.env` with your `LLM_BASE_URL` (including the API prefix, such as `/v1`),
`LLM_MODEL`, and optional `LLM_API_KEY`. Keep `LIVE_REASONING_ENABLED=true` for live
interview answers. Preserve your existing `.env` if already configured.

Start the app:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and upload a text-based PDF resume.
On macOS/Linux, use `.venv/bin/python` and `cp .env.example .env`.

PDF uploads are limited to 10 MB, validated for type and structure, and rejected if they contain scripts, embedded files, forms, automatic actions, or unsafe link actions. Parsing runs in a separate process with time and complexity limits; these checks reduce risk but do not guarantee a file is malware-free.

## Optional speech

Set `SPEECH_ENABLED=true` and configure `STT_BASE_URL` and/or `TTS_BASE_URL`, with
optional `STT_API_KEY` and `TTS_API_KEY`. Your services must expose:

- STT: `POST /transcribe`, multipart `audio` (WAV), returning `{"text":"..."}`.
- TTS: `POST /synthesize`, JSON `{"text":"..."}`, returning 16-bit PCM WAV.

Models and speech runtimes are managed by the user. Generated files stay in `data/`;
resume text, answers, and audio are sent to the services you configure.
