"use client";
import React, { useEffect, useRef, useState } from "react";
import { RoomContext, RoomAudioRenderer } from "@livekit/components-react";
import {
  ConnectionState,
  ParticipantKind,
  Room,
  RoomEvent,
} from "livekit-client";
import {
  request,
  RequestError,
  type Session,
  type History,
} from "@/api";
import { VoicePresence } from "./voice-presence";
import { MicIcon } from "./mic-icon";
import { Check, Square } from "lucide-react";
import { JobDescription } from "./job-description";
import { ResumeUpload } from "./resume-upload";

export function App({ jobDescription }: { jobDescription: string }) {
  const [room] = useState(
    () =>
      new Room({
        adaptiveStream: true,
        audioCaptureDefaults: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      }),
  );
  const [candidate, setCandidate] = useState<string | null>(null);
  const [resume, setResume] = useState<File | null>(null);
  const [lobby, setLobby] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [details, setDetails] = useState({
    duration: "15",
    seniority: "Junior",
  });
  const heading = useRef<HTMLHeadingElement>(null);
  const [session, setSession] = useState<Session | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("interview-session") || "null");
    } catch {
      return null;
    }
  });
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [state, setState] = useState("Not connected"),
    [caption, setCaption] = useState("");
  const [captions, setCaptions] = useState<string[]>([]),
    [muted, setMuted] = useState(false);
  const [micReady, setMicReady] = useState(false),
    [level, setLevel] = useState(0);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const meter = useRef<() => void>(() => {});
  const [checkingMic, setCheckingMic] = useState(false);
  const micAttempt = useRef(0);
  const latest = useRef<Session | null>(null);
  latest.current = session;
  const finalCaption = useRef("");
  const [slowReply, setSlowReply] = useState(false);
  useEffect(() => {
    setSlowReply(false);
    if (state !== "Preparing the next question…") return;
    const timer = setTimeout(() => setSlowReply(true), 3000);
    return () => clearTimeout(timer);
  }, [state]);
  useEffect(() => {
    setCaptions([]);
    setCaption("");
    finalCaption.current = "";
  }, [session?.current_prompt?.id]);
  const ended = !!session && ["completed", "failed"].includes(session.status);
  const stage = ended
    ? "review"
    : session
      ? "interview"
      : lobby
        ? "lobby"
        : "setup";
  useEffect(() => {
    heading.current?.focus();
  }, [stage]);
  useEffect(() => {
    if (session)
      sessionStorage.setItem("interview-session", JSON.stringify(session));
    else sessionStorage.removeItem("interview-session");
  }, [session]);
  useEffect(() => {
    const onData = (
      bytes: Uint8Array,
      participant?: { kind: ParticipantKind },
    ) => {
      if (participant?.kind !== ParticipantKind.AGENT) return;
      try {
        const event = JSON.parse(new TextDecoder().decode(bytes));
        if (event.kind === "session")
          setSession((old) =>
            old &&
            old.session_id === event.session.session_id &&
            ["completed", "failed"].includes(old.status)
              ? old
              : event.session,
          );
        if (event.kind === "state")
          setState(
            (
              {
                initializing: "Connecting",
                connecting: "Connecting",
                listening: "Listening",
                thinking: "Preparing the next question…",
                speaking: "Interviewer speaking",
              } as Record<string, string>
            )[event.state] || "Connecting",
          );
        if (event.kind === "caption") {
          setCaption(event.text);
          if (event.final && event.text !== finalCaption.current) {
            finalCaption.current = event.text;
            setCaptions((old) => [...old, event.text]);
            setCaption("");
          }
        }
        if (event.kind === "error")
          setError(
            "The interviewer hit a problem. Try reconnecting to continue.",
          );
      } catch {
        /* Ignore unrelated room messages. */
      }
    };
    const reconnecting = () => setState("Reconnecting");
    const reconnected = () => {
      setState("Listening");
      setError("");
    };
    const disconnected = () => setState("Disconnected");
    const audio = () => setAudioBlocked(!room.canPlaybackAudio);
    room
      .on(RoomEvent.DataReceived, onData)
      .on(RoomEvent.Reconnecting, reconnecting)
      .on(RoomEvent.Reconnected, reconnected)
      .on(RoomEvent.Disconnected, disconnected)
      .on(RoomEvent.AudioPlaybackStatusChanged, audio);
    return () => {
      room
        .off(RoomEvent.DataReceived, onData)
        .off(RoomEvent.Reconnecting, reconnecting)
        .off(RoomEvent.Reconnected, reconnected)
        .off(RoomEvent.Disconnected, disconnected)
        .off(RoomEvent.AudioPlaybackStatusChanged, audio);
      meter.current();
      micAttempt.current++;
      void room.disconnect();
    };
  }, [room]);
  useEffect(() => {
    if (!session) return;
    const base = "/api/live-sessions/" + session.session_id;
    if (session.status === "completed" || session.status === "failed") {
      request<History>(base + "/history")
        .then(setHistory)
        .catch((e) => setError(e.message));
      setState(session.status === "completed" ? "Completed" : "Failed");
      const timer = setTimeout(() => void room.disconnect(), 4500);
      return () => clearTimeout(timer);
    }
    let stopped = false;
    const timer = setInterval(
      () =>
        request<Session>(base)
          .then((value) => {
            if (!stopped) setSession(value);
          })
          .catch((e) => {
            if (!stopped) {
              setError(e.message);
              if (e.status === 404)
                setSession((old) =>
                  old
                    ? {
                        ...old,
                        status: "failed",
                        completion_reason: "backend_restarted",
                      }
                    : old,
                );
            }
          }),
      2000,
    );
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [session?.session_id, session?.status, room]);
  async function run(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof DOMException
          ? "Microphone access was denied or unavailable. Check your browser permissions and try again."
          : e instanceof RequestError
            ? e.message
            : "We couldn’t complete that step. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function checkMic() {
    if (checkingMic) {
      micAttempt.current++;
      meter.current();
      setCheckingMic(false);
      setBusy(false);
      return;
    }
    const attempt = ++micAttempt.current;
    let succeeded = false;
    setCheckingMic(true);
    await run(async () => {
      meter.current();
      setMicReady(false);
      if (!navigator.mediaDevices)
        throw new RequestError(
          "Your browser can’t access a microphone here. Open this app on localhost or a secure connection.",
          0,
        );
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        });
      } catch (error) {
        if (attempt !== micAttempt.current) return;
        throw error;
      }
      if (attempt !== micAttempt.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const context = new AudioContext();
      meter.current = () => {
        stream.getTracks().forEach((track) => track.stop());
        void context.close().catch(() => {});
      };
      await context.resume();
      if (attempt !== micAttempt.current) return;
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.frequencyBinCount);
      const timer = setInterval(() => {
        analyser.getByteFrequencyData(samples);
        setLevel(
          Math.min(100, samples.reduce((a, b) => a + b, 0) / samples.length),
        );
      }, 100);
      meter.current = () => {
        meter.current = () => {};
        clearInterval(timer);
        stream.getTracks().forEach((t) => t.stop());
        void context.close().catch(() => {});
        setLevel(0);
        setCheckingMic(false);
      };
      setMicReady(true);
      succeeded = true;
    });
    if (attempt === micAttempt.current) {
      // A failed check must return to the start control.
      if (!succeeded) {
        meter.current();
        setCheckingMic(false);
      }
    }
  }
  async function prepare(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resume) {
      setError("Choose a PDF resume before continuing.");
      return;
    }
    if (!micReady) {
      setError("Check your microphone before continuing.");
      return;
    }
    const data = new FormData(event.currentTarget);
    data.set("resume", resume);
    meter.current();
    setLobby(true);
    setPreparing(true);
    setError("");
    try {
      const result = await request<{ candidate_id: string }>(
        "/api/candidates",
        { method: "POST", body: data },
      );
      setCandidate(result.candidate_id);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "We couldn’t prepare your interview. Please try again.",
      );
    } finally {
      setPreparing(false);
    }
  }
  async function join() {
    await run(async () => {
      meter.current();
      setState("Connecting");
      // Start playback permission from the user's click before waiting on network work.
      await room.startAudio();
      let active = latest.current;
      if (!active || ["completed", "failed"].includes(active.status)) {
        active = await request<Session>("/api/live-sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ candidate_id: candidate }),
        });
        latest.current = active;
        setSession(active);
        setHistory(null);
        setCaptions([]);
        setCaption("");
        finalCaption.current = "";
      }
      const connection = await request<{ url: string; token: string }>(
        `/api/live-sessions/${active.session_id}/voice`,
        { method: "POST" },
      );
      if (room.state !== ConnectionState.Disconnected) await room.disconnect();
      await room.connect(connection.url, connection.token);
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        setMuted(false);
      } catch {
        await room.disconnect();
        throw new RequestError(
          "Microphone access was denied. Allow it in your browser, then reconnect.",
          0,
        );
      }
      setAudioBlocked(!room.canPlaybackAudio);
    });
  }
  async function control(action: string) {
    await run(async () => {
      const agent = [...room.remoteParticipants.values()].find(
        (p) => p.kind === ParticipantKind.AGENT,
      );
      if (!agent)
        throw new RequestError(
          "The interviewer is still loading. Wait a moment, then retry.",
          0,
        );
      await room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: "control",
        payload: JSON.stringify({ action }),
        responseTimeout: 8,
      });
    });
  }
  const connected = room.state === ConnectionState.Connected && !ended;
  return (
    <RoomContext.Provider value={room}>
      <RoomAudioRenderer />
      <div className="app" data-stage={stage}>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <a href="/" className="brand" aria-label="Interview room home">
            <span className="brand-symbol" aria-hidden="true">
              i<span>r</span>
            </span>
            <span>
              interview<span className="brand-second">room.</span>
            </span>
          </a>
        </header>
        <main id="main">
          <nav className="journey" aria-label="Interview progress">
            <span aria-current={stage === "setup" ? "step" : undefined}>
              <b>Setup</b>
            </span>
            <i />
            <span aria-current={stage === "lobby" ? "step" : undefined}>
              <b>Waiting room</b>
            </span>
            <i />
            <span
              aria-current={
                stage === "interview" || stage === "review" ? "step" : undefined
              }
            >
              <b>Interview</b>
            </span>
          </nav>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {!session && (
            <>
              <div className="setup" hidden={lobby}>
                <form className="context-form" onSubmit={prepare}>
                  <h1
                    ref={stage === "setup" ? heading : undefined}
                    tabIndex={-1}
                  >
                    Interview
                  </h1>
                  <ResumeUpload
                    disabled={preparing || lobby}
                    onFilesChange={(files) => setResume(files[0] ?? null)}
                  />
                  <JobDescription text={jobDescription} />
                  <div className="form-row">
                    <div>
                      <label htmlFor="duration">Your time</label>
                      <select
                        id="duration"
                        name="duration"
                        disabled={preparing}
                      >
                        <option value="15">15 minutes</option>
                        <option value="30">30 minutes</option>
                        <option value="45">45 minutes</option>
                      </select>
                    </div>
                    <div>
                      <label htmlFor="seniority">Experience level</label>
                      <select
                        id="seniority"
                        name="seniority"
                        disabled={preparing}
                      >
                        <option value="junior">Junior</option>
                        <option value="mid">Mid-level</option>
                        <option value="senior">Senior</option>
                      </select>
                    </div>
                  </div>
                  <div className="sound-check">
                    <button
                      className={`secondary mic-check-control ${checkingMic ? "is-checking" : ""}`}
                      type="button"
                      disabled={busy && !checkingMic}
                      onClick={checkMic}
                      aria-label={checkingMic ? "Stop microphone check" : "Check microphone"}
                      title={checkingMic ? "Stop microphone check" : "Check microphone"}
                    >
                      {checkingMic ? <Square size={18} fill="currentColor" aria-hidden="true" /> : <MicIcon />}
                    </button>
                    <meter
                      min="0"
                      max="100"
                      value={level}
                      aria-label="Microphone input level"
                    />
                    <span className="mic-check-result" aria-hidden="true">{micReady && <Check size={20} />}</span>
                    <p className="sr-only" role="status">
                      {micReady
                        ? "Microphone ready"
                        : "Check your microphone to continue."}
                    </p>
                  </div>
                  <button
                    className="primary prepare-button"
                    disabled={!resume || !micReady || busy || preparing}
                  >
                    Prepare interview <span aria-hidden="true">↗</span>
                  </button>
                </form>
              </div>
              {lobby && (
                <section className="lobby">
                  <div
                    className={`lobby-signal ${candidate ? "ready" : ""}`}
                    aria-hidden="true"
                  >
                    <span />
                    <span />
                    <span />
                    <b>{candidate ? "↗" : "✳"}</b>
                  </div>
                  <h1 ref={heading} tabIndex={-1}>
                    Waiting room
                  </h1>
                  <p className="lobby-message" role="status">
                    {preparing
                      ? "Please wait while we prepare your interview."
                      : candidate
                        ? "Your interview is ready."
                        : "Go back and try again."}
                  </p>
                  <button
                    className="primary"
                    disabled={!candidate || !micReady || busy || preparing}
                    onClick={join}
                  >
                    {busy ? "Connecting…" : "Join interview"}
                    <span aria-hidden="true">↗</span>
                  </button>
                  {!preparing && (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => {
                        meter.current();
                        setMicReady(false);
                        setLobby(false);
                        setCandidate(null);
                        setError("");
                      }}
                    >
                      ← Back to setup
                    </button>
                  )}
                </section>
              )}
            </>
          )}
          {session && !ended && (
            <section className="interview">
              <div className="interview-top">
                <h1 ref={heading} tabIndex={-1}>
                  Interview
                </h1>
                <div className="session-meta">
                  <span className="state" role="status">
                    <span className="status-dot" />
                    {slowReply ? "Still preparing the next question…" : state}
                  </span>
                </div>
              </div>
              <div className="conversation-grid">
                <div className="voice-stage">
                  <VoicePresence
                    muted={muted}
                    disabled={!connected || busy}
                    onToggle={() =>
                      void run(async () => {
                        await room.localParticipant.setMicrophoneEnabled(muted);
                        setMuted(!muted);
                      })
                    }
                  />
                </div>
                <div className="conversation">
                  <div className="question">
                    <p className="eyebrow">
                      INTERVIEWER <span aria-hidden="true">↘</span>
                    </p>
                    <h2>
                      {session.current_prompt?.text ||
                        "Getting your conversation ready…"}
                    </h2>
                  </div>
                  <div className="answer">
                    <p className="eyebrow">YOU</p>
                    <p>
                      {[...captions, caption].filter(Boolean).join(" ") ||
                        "Your answer appears here."}
                    </p>
                  </div>
                </div>
              </div>
              <div className="controls">
                <p>Speak naturally. You can interrupt or ask to repeat.</p>
                <div className="turn-controls">
                  <button
                    disabled={!connected || busy}
                    onClick={() => control("repeat")}
                  >
                    Repeat question
                  </button>
                  <button
                    disabled={!connected || busy}
                    onClick={() => control("stop")}
                  >
                    Stop speaking
                  </button>
                </div>
                <div className="session-controls">
                  <button hidden={connected && !error} disabled={busy} onClick={join}>
                    Reconnect
                  </button>
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        // Leave gracefully before the API deletes the LiveKit room.
                        // Deleting it first interrupts the SDK's signal reader.
                        await room.disconnect();
                        const value = await request<Session>(
                          `/api/live-sessions/${session.session_id}/end`,
                          { method: "POST" },
                        );
                        setSession(value);
                      })
                    }
                  >
                    End interview <span aria-hidden="true">↗</span>
                  </button>
                </div>
              </div>
              {audioBlocked && (
                <button
                  className="primary audio-enable"
                  onClick={() =>
                    run(async () => {
                      await room.startAudio();
                      setAudioBlocked(!room.canPlaybackAudio);
                    })
                  }
                >
                  Enable interviewer audio
                </button>
              )}
            </section>
          )}
          {ended && (
            <section className="history">
              <div className="review-heading">
                <h1 ref={heading} tabIndex={-1}>
                  {session.status === "failed"
                    ? "Interview interrupted"
                    : "Interview complete"}
                </h1>
                <button
                  className="primary"
                  onClick={() => {
                    setSession(null);
                    setCandidate(null);
                    setResume(null);
                    setHistory(null);
                    setError("");
                    setState("Not connected");
                    setLobby(false);
                    setMicReady(false);
                    setCaption("");
                    setCaptions([]);
                    finalCaption.current = "";
                  }}
                >
                  Start another interview <span aria-hidden="true">↗</span>
                </button>
              </div>
              <div className="transcript">
                <div className="section-top">
                  <h2>Your conversation.</h2>
                  <span className="tiny-label">TEXT ONLY</span>
                </div>
                {history ? (
                  history.events.filter((event) =>
                    ["question", "candidate", "answer"].includes(event.kind),
                  ).length ? (
                    history.events
                      .filter((event) =>
                        ["question", "candidate", "answer"].includes(
                          event.kind,
                        ),
                      )
                      .map((event, index) => (
                        <article key={index}>
                          <p className="eyebrow">
                            {event.kind === "question" ? "INTERVIEWER" : "YOU"}
                            {event.interrupted ? " · INTERRUPTED" : ""}
                          </p>
                          <p>{event.text}</p>
                        </article>
                      ))
                  ) : (
                    <p className="muted">No spoken turns were saved.</p>
                  )
                ) : (
                  <p className="muted" role="status">
                    Loading your conversation…
                  </p>
                )}
              </div>
            </section>
          )}
        </main>
      </div>
    </RoomContext.Provider>
  );
}
export default App;
