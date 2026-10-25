# Local conversational interviewer

The frontend now uses Next.js App Router 16.4. Run `npm --prefix frontend ci`
after updating this checkout. Both development and production use port 5173;
Next.js forwards interview requests to the local API on port 8000. Preparation uses
a Next.js server route that supplies the fixed job posting before forwarding.

The role comes from `sample_data/job_description.txt` (currently Artificial
Intelligence Intern at Medinex Workforce). This file must be present when the app
runs. Candidates can read the full posting but cannot edit it. The preparation
route replaces any submitted job description with the configured file contents,
and returns only the preparation identifier to the browser. No sample resume is
read or displayed. The app reads the posting at request time, so changes made by
the operator to the file are used without rebuilding the frontend.

The setup is a centered form with the full, always-visible read-only JD, resume upload and
interview settings and a microphone check. Marketing panels and repeated helper/privacy text have been
removed. The screen flow is setup and microphone check → waiting room → voice
interview → saved conversation. The lobby follows the actual preparation request;
preparation requires a successful microphone check, and joining requires completed preparation.
The test microphone stream stops on entering the waiting room. Preparation errors
retain the entered context for retry. Model names, internal identifiers, raw error
details, and completion codes are not displayed. API/WebRTC traffic and browser
session storage still require internal session data; UI cleanup is not a security boundary.

Resume selection uses the [Arc UI FileDropzone](https://uiarc.dev/components/file-dropzone),
vendored from its free registry with local theme tokens. It accepts one nonempty PDF
up to 10 MB through the picker or drag-and-drop, shows a removable file row, and
submits that File with the preparation form. Failed-size selections cannot be sent.
The component is disabled while waiting/preparing and resets for a new interview.

The interview uses the official LiveKit `AgentAudioVisualizerRadial`, driven by the
interviewer’s audio track and state, switching to the candidate microphone during
answers, around a microphone mute/unmute button. The
component and animator are vendored with the upstream Apache license, from
`livekit/components-js` commit `65701808b070bfdbba6627a5758dd13988b0141b`.
The palette is jet black, hot pink, and electric yellow, with local system fonts.

Migration references: [Next.js installation](https://nextjs.org/docs/app/getting-started/installation),
[LiveKit visualizers](https://docs.livekit.io/frontends/agents-ui/audio-visualizer/prebuilt/),
and [radial component reference](https://docs.livekit.io/reference/components/agents-ui/component/agent-audio-visualizer-radial/).

Frontend checks: `npm --prefix frontend test`, `npm --prefix frontend run typecheck`,
and `npm --prefix frontend run build`. Use `npm --prefix frontend start` for the
production build; the demo launcher starts `next dev`.

## Interview design

New plans begin with a brief introduction and project/experience overview, then mix
role fundamentals, a relevant framework or tool, and a focused project discussion.
A 15-minute interview has six lead questions, including an unscored closing. Longer
interviews add a realistic role scenario and a behavioral example, with more topics
for sessions of an hour or longer. If the resume has no projects, experience and
explicitly hypothetical role scenarios replace project-specific prompts.

Related competencies can share a question; every JD competency must still be covered.
Lead questions are short, single-focus prompts. Up to two optional probes support
answer-specific follow-ups instead of a compulsory checklist. Rubrics accept valid
alternative approaches and calibrate depth to seniority. Introduction and closing
collect context only: they never save assessment evidence or trigger technical probes.
The live reasoner receives recent conversation and the current section's time budget
to avoid repetition and over-probing. Candidate questions in closing may be answered
only from the supplied JD; unsupported employer details must not be invented.

This design uses job-related questions and anchored evidence, informed by
[OPM's structured interview guidance](https://www.opm.gov/policy-data-oversight/assessment-and-selection/other-assessment-methods/structured-interviews/)
and [Microsoft's student interview guidance](https://careers.microsoft.com/v2/global/en/hiring-tips/student-interviewing).
The question mix and time allocations are application design choices, not a claim
that these organizations prescribe this exact sequence.

Saved older plans remain readable; existing prepared/running interviews keep their
plans. Restart an already-running backend and prepare a new interview to use the
updated planner. An optional real-provider check with a synthetic candidate is
`work/speech-venv/Scripts/python.exe scripts/planner_smoke.py`; it calls the configured
LLM, validates the plan and Markdown round trip, and writes `work/planner-smoke.json`.

## Gemini voice demo

English interviews use a local LiveKit server for WebRTC transport and hosted Gemini
services for streaming transcription, answer assessment, and speech generation:

```text
Browser microphone -> LiveKit -> Gemini live transcription
  -> FastAPI assessment and transition rules -> validated question
  -> Gemini streaming TTS -> LiveKit -> browser speakers
```

There are no local speech models, model downloads, model warmup, or saved audio.
An internet connection and a Gemini API key with access to the configured speech
models are required. Audio is sent to Gemini for transcription; local history saves
text answers, questions, interruption markers, and assessment evidence.

### Setup

Install Python 3.12+ and Node 22.22+, then run from this project root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-demo.ps1
```

Setup retains the existing `work/speech-venv` environment location, installs pinned
Python packages and frontend dependencies, and installs the local LiveKit transport.
It preserves an existing `.env`. Configure `GEMINI_API_KEY` before the hosted speech
preflight can succeed; after adding the key, rerun setup. Existing downloaded model
assets are unused and can remain in place.

Server-side `.env` settings:

```dotenv
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=gemini-3.8-flash
LIVE_LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=<your Google Gemini API key>
GEMINI_STT_MODEL=gemini-3.5-transcribe-live
GEMINI_TTS_MODEL=gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Kore
LIVE_REASONING_TIMEOUT_SEC=8
```

`LIVE_LLM_MODEL` is optional and falls back to `LLM_MODEL`; preparation continues to
use `LLM_MODEL`. Live Flash-Lite requests use minimal thinking; other live models use
low thinking. The Gemini SDK handles speech; text assessment uses the compatible
HTTP endpoint. Credentials remain on the server. Use matching `AGENT_SECRET` values
in the API and worker environment.

Check real speech-model access and streaming without using a microphone:

```powershell
work/speech-venv/Scripts/python.exe scripts/setup_speech.py
```

This makes small paid Gemini requests, checks streaming speech output and a live
transcription connection, and reports provider errors directly. It never substitutes
another speech service or downloads local models.

### Start and use

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -OpenBrowser
```

The launcher starts LiveKit, FastAPI, the voice worker, and Next.js, then opens
[the local demo](http://127.0.0.1:5173). Services stream logs to the terminal. There is
no speech-model warmup. Keep the terminal open; Ctrl+C stops its services.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -Action Stop
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -Action Status
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -Action Check
```

Upload a resume, pass the microphone check, prepare, and join. Use headphones to
reduce echo. The browser enables echo cancellation and noise suppression. Speak
naturally; hosted activity detection uses a 700 ms silence threshold, with no extra
LiveKit endpoint delay. Interim captions update during speech; only final transcripts
reach assessment. The interviewer waits for assessment before speaking the next
question. The eight-second deadline remains failure recovery, not an early skip.

Hosted speech-start events stop playback and cancel pending assessment when you
resume. Stop speaking also stops playback immediately; Repeat question replays the
current prompt. A partial TTS failure offers repeat rather than automatically replaying
already emitted audio. A transcription failure requires reconnecting and repeating the
unfinished answer. The interface shows listening, preparation, speaking, and mute states;
a longer preparation wait receives a clearer status after three seconds.

Transcription connections renew after eight minutes when the candidate is not speaking,
before Gemini's documented ten-minute limit. A disconnect allows 30 seconds to reconnect;
the current question is repeated without advancing. A backend or worker restart requires
a new interview. Already running processes need restarting after configuration changes.

### State and endpoints

FastAPI remains the only owner of interview state and assessment. The worker streams
speech and submits idempotent finalized turns. One candidate at a time is supported;
run one API worker and avoid auto-reload during an interview.

- `POST /api/live-sessions/{id}/voice`: room token and explicit agent dispatch.
- `GET /api/live-sessions/{id}/history`: saved text history after backend restart.
- Agent-only `GET .../{id}/agent`, `POST .../{id}/agent/events`, and
  `POST .../{id}/agent/turns` require `X-Agent-Secret`.

Preparation remains in `data/demo/candidates`; history remains in
`data/demo/interviews/{session_id}.json`. Public APIs and stored history formats are unchanged.

### Verification

```powershell
work/speech-venv/Scripts/python.exe -m pytest -q --basetemp=work/pytest-live
work/speech-venv/Scripts/python.exe -m ruff check backend tests scripts
work/speech-venv/Scripts/python.exe -m mypy backend
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

With the demo running, exercise real Gemini speech and WebRTC using synthetic audio:

```powershell
work/speech-venv/Scripts/python.exe scripts/voice_smoke.py --reconnect
work/speech-venv/Scripts/python.exe scripts/voice_smoke.py --turns 20 --soak-seconds 900
work/speech-venv/Scripts/python.exe scripts/assessment_benchmark.py
```

These make paid Gemini calls, never use your microphone, and save reports under `work/`.
The voice benchmark measures received speech audio using an energy threshold, separately
from agent state messages. It reports functional success separately from latency targets.
Targets are median response under three seconds, p95 under five seconds, and median
interruption under 700 ms. Hosted TTS startup can exceed these targets; Gemini-only speech
simplifies installation but does not guarantee faster synthesis than the previous local TTS.
Synthetic tests do not validate your microphone, accent, or background noise. Test those
with the demo before presenting it.

References: [Gemini live transcription](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe),
[Gemini streaming TTS](https://ai.google.dev/gemini-api/docs/speech-generation), and
[LiveKit turn handling](https://docs.livekit.io/agents/logic/turns/).
