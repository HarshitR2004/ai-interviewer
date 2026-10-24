# Demo API

`GET /openapi.json` is the authoritative request/response schema. Communication uses JSON
or multipart uploads; saved generated documents use Markdown only.

## Preparation

`POST /api/candidates`: multipart `resume` (exactly one PDF up to 10 MiB),
`job_description` (40–12,000 characters), `duration` (15–120, default 45), `seniority`
(junior/mid/senior, default junior), `interview_type` (mixed/technical/project, default mixed).
The request waits for extraction, generation, validation, and persistence. HTTP 201 returns
`{candidate_id, profile, plan, settings, job_description}`. `profile` and `plan` are the
complete typed models defined in OpenAPI.

`GET /api/candidates/{candidate_id}` reloads the two Markdown documents and returns the
same preparation shape. The old `/status` endpoint is removed. Incomplete document pairs
return 404, invalid documents 422. Reading documents does not invoke the model.

`POST /api/candidates/{candidate_id}/interview` accepts:

```json
{"job_description":"Build Python APIs with database design and testing.","settings":{"duration":45,"seniority":"junior","interview_type":"mixed"}}
```

It waits for replanning, atomically replaces `interview-plan.md`, and returns the completed
preparation with HTTP 200. It does not regenerate or rewrite the persona. Overlapping
replans conflict. Provider/storage failures preserve the last completed plan.

## Live sessions

`POST /api/live-sessions` accepts `{"candidate_id":"<32 lowercase hex characters>"}` and
returns HTTP 201 with the public session. There are no client event IDs or creation receipts.
A repeated create request creates another independent session.

`GET /api/live-sessions/{session_id}` returns:

```text
session_id, candidate_id, status (active/completed), current_prompt (id/question_id/text or null),
question_number, question_count, follow_up_count, deadline_at, progression[]
```

`deadline_at` is Unix seconds. Each progression entry contains proposed_action,
executed_action, reason, and assessment_available. Rubrics, answers, and evidence stay private.

`POST /api/live-sessions/{session_id}/answers` accepts:

```json
{"prompt_id":"<current prompt id>","answer":"Use a transaction and unique constraint."}
```

It waits for assessment and returns HTTP 200 with `{session, transition, transcription}`.
The transition has the same explanation shape as progression entries; transcription is
null for text or `{"text":"recognized text"}` for audio. Actions are clarify, follow_up,
advance, or finish. A completed answer can leave the session active. Failed assessment
uses prepared fallback with assessment_available=false, without inventing evidence.

`POST /api/live-sessions/{session_id}/end` has no request body and returns the closed
public session. Operations on a busy session return 409, including reads/end requests.
Stale prompt IDs and answers to completed sessions also return 409. Answers are not
idempotent operations: do not automatically retry or submit pending corrections.

## Audio

`POST /api/live-sessions/{session_id}/audio-answers` accepts multipart `audio` and
`prompt_id`, then returns the same completed answer shape. There are no event IDs or
replacement IDs. Transcription and assessment hold the same session guard.

`GET /api/live-sessions/{session_id}/prompt/audio?prompt_id=...` returns `audio/wav`,
Cache-Control: no-store, and X-Prompt-ID. Synthesis holds the guard and rechecks the
deadline after the provider returns. WAV is 16-bit PCM, mono/stereo, 8–48 kHz, up to
120 seconds and 12 MiB. Disabled capabilities return 503.

## Errors and restart

Expected errors use `{"detail":"safe explanation"}`: 422 invalid input/document, 404
missing preparation/session, 409 busy/conflict/closed, 503 provider/storage unavailable.
Resume middleware also returns 400, 408, 413, and 429 for bounded-upload failures.
No processing receipts, recovery statuses, schema versions, or concurrency counters appear.

Restart loses live sessions. Preparations remain reloadable from Markdown, and a new
session can be created. Expiry is checked on access and after assessment; no background
watcher closes idle sessions. Authentication, CORS deployment policy, and frontend hosting
remain outside this demo change.
