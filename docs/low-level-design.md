# Demo server: low-level design and onboarding

This document describes the simplified implementation. It is an API-only modular
monolith intended for one demo process, with completed preparations in Markdown and
live sessions in memory.

## 1. Reading order and package ownership

Start at `backend/main.py`, then `bootstrap.py`. Follow an API route into its feature
service, then read the feature's models and domain rules before its I/O implementation.

| Package | Owns |
| --- | --- |
| api | HTTP parsing, single-file uploads, responses, error-to-status mapping |
| modules/resume_ingestion | Filename/MIME checks and basic PDF text extraction |
| modules/profiles | Profile models, model instructions, profile validation |
| modules/interview_planning | Competencies, generation schema, timing, plan validation |
| modules/preparation | Synchronous workflow, Markdown codecs, preparation store port |
| modules/live_interviews | Registry, typed state, reasoning, transitions, audio orchestration |
| integrations | External model/speech interfaces and HTTP implementations |
| common | Application errors, Markdown primitives, atomic file helpers |

`service.py` coordinates a use case. `models.py` defines typed data. `ports.py` defines
required behavior without choosing an implementation. Here the preparation-store port
has only create/load/replace-plan operations. The provider ports also remain useful for
fake clients and alternate providers. There is no task-runner or live-repository interface
because the demo has neither durable jobs nor a live database.

## 2. Construction and lifecycle

`create_app(settings, service_factory=build_services)` installs routes and error handlers. Its small lifespan builds a Services container, attaches it
to app.state, and closes model/speech clients on shutdown. No startup lock, recovery scan,
or background watcher runs. Merely starting the server does not create candidate files.

```text
ChatCompletionsClient â†’ StructuredGeneration â†’ ProfileService / InterviewService
                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â†’ ModelReasoner
MarkdownPreparationStore + profile/planning/ingestion â†’ PreparationService
SessionRegistry + PreparationService + optional reasoner â†’ LiveInterviewService
LiveInterviewService + optional transcriber/synthesizer â†’ AudioInterviewService
```

`settings.py` reads environment/.env configuration and validates endpoint URLs. Relative
DATA_DIR is resolved against the source-derived project root. The store writes only into
DATA_DIR/demo/candidates. Model URL and model name are required; live assessment and speech
are separately enabled. Clients are reusable HTTPX clients with trust_env=False.

## 3. Preparation request flow

1. POST /api/candidates parses one multipart PDF and interview settings.
2. ResumeIngestionService validates filename/type, then invokes the extractor in a thread.
3. PdfExtractor validates size, PDF readability, password protection, and page/text limits,
   then returns extracted text using pypdf.
4. ProfileService generates and validates a CandidateProfile.
5. InterviewService determines competencies, generates sections, normalizes time, and validates.
6. PreparationService constructs a Preparation with a new candidate ID.
7. The store writes resume.pdf, persona.md, and interview-plan.md; the request returns 201
   only after storage succeeds.

There is no queue or status-polling endpoint. The HTTP request waits for the actual model
work. An extraction or generation failure occurs before candidate storage. An initial disk
failure may leave an incomplete directory, which cannot be loaded as a preparation.

CandidateProfile contains identity, background, education, experience, grouped skills,
projects, discussion topics, source references, and collection status. A Project contains
its ID, name, purpose, technologies, contributions, technical details, and source labels.
Profile validation checks duplicate project IDs and allowed project sources. It does not
prove that all generated statements are factual.

InterviewPlan contains role, required competencies, and sections. Each section contains
exactly one base question, its competency and minutes. Questions include optional project
reference, candidate context, follow-ups, strong-answer signals, and weak/adequate/strong
rubric descriptions. The current live workflow does not calculate a numeric candidate score.

`planning.py` owns explicit competency extraction, dynamic required-section schemas,
conversion to the ordinary plan model, and proportional time allocation. If no explicit
Required competencies line exists, requirements are extracted through the model. Dynamic
schemas fix each section's competency. Validation checks total duration, coverage, project
references, and duplicate questions. Time allocation reserves one minute per section,
then distributes remaining time by weights and largest fractional remainders.

## 4. Markdown as authoritative storage

```text
DATA_DIR/demo/candidates/<id>/
â”œâ”€â”€ resume.pdf
â”œâ”€â”€ persona.md
â””â”€â”€ interview-plan.md
```

`preparation/documents.py` maps typed fields to the format documented in
[markdown-format.md](markdown-format.md). `common/markdown.py` supplies only Reader/Writer
primitives: headings, blockquoted scalars, lists, and numbered groups. No model is called
when parsing saved documents. Domain models do not depend on the document syntax.

`storage.py` owns paths, UTF-8 reads, and atomic writes. It serializes short file operations
under an RLock to avoid Windows reader/replacement races, and uses thread-based run_io.
A write flushes/fsyncs a temporary file before os.replace. This is an atomic file replacement,
not a guarantee against every hardware/power-loss scenario.

GET /api/candidates/{id} loads and validates both documents. A missing document returns
404; malformed content produces a document-format error. Reads never rewrite or repair
user documents. No JSON sidecar, manifest, digest, version history, or schema migration exists.

Replanning loads the profile, generates a new plan, and replaces only interview-plan.md,
which also contains its settings and complete job description. persona.md stays unchanged.
A generation or pre-replacement write failure preserves the previous plan. A small busy
set inside the preparation service rejects overlapping replans and reads during replanning;
its finally block releases ownership even if a request is cancelled.

## 5. Live state and registry

SessionRegistry owns a dictionary of session ID to SessionState and a busy-ID set. Its
operation context checks existence/busy status, claims the ID, and releases it in finally.
There is no SQL, process lock, durable receipt, revision counter, or correction history.

SessionState holds a deep copy of the loaded preparation, current section/question index,
status, current prompt, section start and overall deadline, follow-up bookkeeping, answer
turns, evidence, and compact transition explanations. Each section has one base question.
The question ID is derived from its section index, such as s1q1.

A question is the planned assessment item with its rubric. A prompt is the exact turn
presented to the client: it can be the base question, a clarification, or a follow-up.
Every new prompt receives a fresh ID. Answers must name the current prompt ID.

The public projection contains identity, active/completed status, prompt, counts, deadline,
and progression explanations. It excludes saved answer text, evidence, and question rubrics.
A Preparation response intentionally contains the full plan for preparation clients.

Restart creates an empty registry. Existing Markdown can create new sessions; previous
session IDs return 404. Replanning a candidate does not mutate a running session's copied plan.

## 6. Answer processing and transitions

The live service acquires the registry operation guard for text answers, reads, ending,
and speech operations. The guard remains held across awaited provider calls. Overlapping
requests return 409 rather than waiting or updating the state concurrently. Different
sessions remain independent. There are no client event IDs or automatic replay guarantees.

For an answer, the service checks session status, deadline, prompt, and reasoning availability.
The reasoner receives a deep copy of current state, current answer, remaining time, question
rubric, previous answer turns, recent evidence, and probe count. It returns a Decision.

No answer-history or transition mutation occurs before assessment finishes. Cancellation
therefore releases the guard with the same current question available. A provider failure,
timeout, or invalid Decision uses a prepared follow-up if available, otherwise advance.
Fallback never fabricates assessment evidence.

`transitions.py` mutates state deterministically from the Decision, supplied time, and
supplied prompt ID. Overall deadline forces finish. Section expiry or an exhausted budget
of two probes prevents another clarification/follow-up. Advance moves to the next section;
exhausting questions finishes the interview. Probe bookkeeping resets on advance.

Each TransitionExplanation contains proposed_action, executed_action, reason, and
assessment_available. These are the concise explanation returned to the client and retained
in session progression. No persistent audit history is written. Manual ending closes the
session and returns its public view.

Deadlines are checked on access and again after model assessment. An idle session is only
closed when next accessed; there is no background countdown. A model response arriving after
the deadline is passed through the same transition rules and finishes the session.

## 7. Speech and provider boundaries

AudioInterviewService shares the live operation guard through transcription and assessment.
It validates the prompt and reasoning availability before using STT, then constructs the
same typed AnswerInput used by text. The completed result includes the recognized transcript.
A speech failure/cancellation releases the guard without advancing the question. There are
no byte fingerprints, audio receipts, or replacement IDs.

Prompt synthesis also holds the guard, and checks the deadline after TTS returns. Other
operations cannot change the prompt during synthesis. Invalid/expired prompts conflict.
The SpeechClient adapter validates WAV, caps streamed responses, and maps provider failures
to safe errors. Audio is 16-bit PCM, mono/stereo, 8â€“48 kHz, up to 120 seconds and 12 MiB.

ChatCompletionsClient returns validated response text. StructuredGeneration parses that
text against the required Pydantic schema and applies domain validation. One invalid output
allows one repair request; transport failures are not retried. Live reasoning uses its own
timeout and fallback. Request metadata/version plumbing and the standalone evaluator runner
have been removed. JSON remains at these communication boundaries, not in preparation files.

PDF extraction runs in a worker thread using pypdf. The route reads at most 10 MiB plus
one byte; the extractor owns the file-size check. Filename/type, readable-text, password,
page-count, and text-length checks provide basic input validation. There is no custom upload
middleware, subprocess worker, or PDF object scanner.

## 8. Tests and extension points

Tests use synthetic data and fake ports; conftest blocks real HTTP transport. Unit tests
cover Markdown round trips/malformed formats, planning rules, transitions, busy handling,
and cancellation. Integration tests cover document reload/replacement, provider HTTP
contracts, and cleanup. API tests cover complete preparation/text/audio workflows. Strict
mypy, lint, formatting, and architecture rules are retained.

Extend providers through their existing contracts and wire them in bootstrap. Put new
interview rules in transitions, not API routes. Extend the Markdown format in documents.py
with matching render/parse and round-trip tests. Storage paths stay in storage.py; API
payload details stay in routes/models. If durable sessions or parallel session operations
become requirements later, design those explicitly rather than adding partial receipts.

See [API payloads](api.md), [Markdown examples](markdown-format.md), and [setup](../README.md).
