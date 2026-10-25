// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const fake = vi.hoisted(() => ({
  room: null as any,
  rpc: vi.fn(),
  microphone: vi.fn(),
  media: vi.fn(),
  micStop: vi.fn(),
}));
vi.mock("@livekit/components-react", async () => {
  const react = await import("react");
  return {
    RoomContext: react.createContext(null),
    RoomAudioRenderer: () => null,
  };
});
vi.mock("livekit-client", () => {
  class Room {
    state = "disconnected";
    canPlaybackAudio = true;
    handlers = new Map<string, Function[]>();
    remoteParticipants = new Map([
      ["agent", { identity: "interviewer", kind: 4 }],
    ]);
    localParticipant = {
      setMicrophoneEnabled: fake.microphone,
      performRpc: fake.rpc,
    };
    constructor() {
      fake.room = this;
    }
    on(name: string, fn: Function) {
      this.handlers.set(name, [...(this.handlers.get(name) || []), fn]);
      return this;
    }
    off(name: string, fn: Function) {
      this.handlers.set(
        name,
        (this.handlers.get(name) || []).filter((f) => f !== fn),
      );
      return this;
    }
    emit(name: string, ...args: unknown[]) {
      for (const fn of this.handlers.get(name) || []) fn(...args);
    }
    async connect() {
      this.state = "connected";
    }
    async disconnect() {
      this.state = "disconnected";
    }
    async startAudio() {}
  }
  return {
    Room,
    ConnectionState: { Connected: "connected", Disconnected: "disconnected" },
    ParticipantKind: { AGENT: 4 },
    RoomEvent: {
      DataReceived: "data",
      Reconnecting: "reconnecting",
      Reconnected: "reconnected",
      Disconnected: "disconnected",
      AudioPlaybackStatusChanged: "audio",
    },
  };
});
import { App } from "./components/interview-app";
const fixedJobDescription =
  "## Artificial Intelligence Intern (Remote)\n\n- **Company:** Medinex Workforce\n\nBuild reliable AI applications with Python and machine learning.";
vi.mock("./components/voice-presence", () => ({
  VoicePresence: () => <div data-testid="radial-voice" />,
}));

const active = {
  session_id: "test",
  status: "active",
  current_prompt: {
    id: "p",
    text: "How would you prevent duplicate bookings?",
  },
  question_number: 1,
  question_count: 2,
  deadline_at: Date.now() / 1000 + 900,
  completion_reason: null,
};
beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  sessionStorage.clear();
  fake.rpc.mockReset();
  fake.microphone.mockReset();
  fake.media.mockReset();
  fake.micStop.mockReset();
  fake.media.mockResolvedValue({ getTracks: () => [{ stop: fake.micStop }] });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: fake.media },
  });
  vi.stubGlobal(
    "AudioContext",
    class {
      async resume() {}
      async close() {}
      createAnalyser() {
        return {
          fftSize: 256,
          frequencyBinCount: 128,
          getByteFrequencyData: (data: Uint8Array) => data.fill(0),
        };
      }
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () => {
        if (path === "/api/candidates") return { candidate_id: "candidate" };
        if (path.endsWith("/voice"))
          return { url: "ws://local", token: "token" };
        if (path.endsWith("/history"))
          return {
            events: [
              { kind: "candidate", text: "I used a unique constraint." },
            ],
            evidence: [],
          };
        if (path.endsWith("/end")) {
          expect(fake.room.state).toBe("disconnected");
          return {
            ...active,
            status: "completed",
            completion_reason: "user_ended",
          };
        }
        return active;
      },
    })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function checkSetupMicrophone() {
  fireEvent.change(screen.getByLabelText("Upload resume (PDF)"), {
    target: {
      files: [new File(["pdf"], "resume.pdf", { type: "application/pdf" })],
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check microphone" }));
  await screen.findByText("Microphone ready");
}

it("shows the fixed role as a readable document with no editable JD field", () => {
  render(<App jobDescription={fixedJobDescription} />);
  expect(
    screen.getByRole("region", { name: "Full job description" }).textContent,
  ).toContain("Medinex Workforce");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(document.querySelector('[name="job_description"]')).toBeNull();
  expect(screen.queryByText("Resume PDF")).toBeNull();
  expect(screen.queryByText(/Your experience\./)).toBeNull();
});

it("prepares, joins, shows captions, controls the agent, and displays saved history", async () => {
  render(<App jobDescription={fixedJobDescription} />);
  fireEvent.change(screen.getByLabelText("Upload resume (PDF)"), {
    target: {
      files: [new File(["pdf"], "resume.pdf", { type: "application/pdf" })],
    },
  });
  await checkSetupMicrophone();
  fireEvent.submit(
    screen.getByRole("button", { name: "Prepare interview" }).closest("form")!,
  );
  await screen.findByText(/Your interview is ready/);
  const preparationCall = vi
    .mocked(fetch)
    .mock.calls.find(([path]) => path === "/api/candidates");
  expect(
    ((preparationCall?.[1] as RequestInit).body as FormData).get("resume"),
  ).toHaveProperty("name", "resume.pdf");
  fireEvent.click(screen.getByRole("button", { name: /Join interview/ }));
  await screen.findByText(active.current_prompt.text);
  await waitFor(() => expect(fake.microphone).toHaveBeenCalledWith(true));
  act(() =>
    fake.room.emit(
      "data",
      new TextEncoder().encode(
        JSON.stringify({
          kind: "caption",
          text: "My answer in progress",
          final: false,
        }),
      ),
      { kind: 4 },
    ),
  );
  expect(screen.getByText("My answer in progress")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "I’m done" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Repeat question" }));
  await waitFor(() =>
    expect(fake.rpc).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "control",
        payload: '{"action":"repeat"}',
      }),
    ),
  );
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "End interview",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "End interview" }));
  await screen.findByText("I used a unique constraint.");
  expect(screen.queryByRole("button", { name: "I’m done" })).toBeNull();
});

it("stops the microphone check and allows another check with icon controls", async () => {
  render(<App jobDescription={fixedJobDescription} />);
  await checkSetupMicrophone();
  const stop = screen.getByRole("button", { name: "Stop microphone check" });
  expect(stop.textContent).toBe("");
  fireEvent.click(stop);
  expect(fake.micStop).toHaveBeenCalledTimes(1);
  expect((screen.getByLabelText("Microphone input level") as HTMLMeterElement).value).toBe(0);
  expect((screen.getByRole("button", { name: /Prepare interview/ }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Check microphone" }));
  await screen.findByRole("button", { name: "Stop microphone check" });
  expect(fake.media).toHaveBeenCalledTimes(2);
});

it("stops a pending check and releases microphone access if permission resolves later", async () => {
  let resolve!: (stream: unknown) => void;
  fake.media.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  render(<App jobDescription={fixedJobDescription} />);
  fireEvent.click(screen.getByRole("button", { name: "Check microphone" }));
  fireEvent.click(screen.getByRole("button", { name: "Stop microphone check" }));
  await act(async () => resolve({ getTracks: () => [{ stop: fake.micStop }] }));
  expect(fake.micStop).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Check microphone" })).toBeTruthy();
  expect(screen.queryByText("Microphone ready")).toBeNull();
});

it("explains microphone failure without starting an interview", async () => {
  fake.media.mockRejectedValue(
    new DOMException("Permission denied", "NotAllowedError"),
  );
  render(<App jobDescription={fixedJobDescription} />);
  fireEvent.click(screen.getByRole("button", { name: "Check microphone" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("alert").textContent).toContain(
    "Microphone access was denied",
  );
  expect(fake.microphone).not.toHaveBeenCalled();
});

it("checks sound on setup then opens a waiting room while preparation is pending", async () => {
  let finish!: (value: unknown) => void;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  vi.mocked(fetch).mockImplementationOnce(() => pending as Promise<Response>);
  render(<App jobDescription={fixedJobDescription} />);
  expect(
    (
      screen.getByRole("button", {
        name: "Prepare interview",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await checkSetupMicrophone();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.submit(
    screen.getByRole("button", { name: "Prepare interview" }).closest("form")!,
  );
  expect(screen.getByText(/Please wait while we prepare/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Prepare interview" }),
  ).toBeNull();
  expect(
    (
      screen.getByRole("button", {
        name: /Join interview/,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.queryByRole("button", { name: /Check microphone/ })).toBeNull();
  expect(screen.getByRole("heading", { name: "Waiting room" })).toBeTruthy();
  expect(fake.micStop).toHaveBeenCalledOnce();
  expect(
    (
      screen.getByRole("button", {
        name: /Join interview/,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await act(async () =>
    finish({ ok: true, json: async () => ({ candidate_id: "private-id" }) }),
  );
  await screen.findByText(/Your interview is ready/);
  expect(
    (
      screen.getByRole("button", {
        name: /Join interview/,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  expect(document.body.textContent).not.toContain("private-id");
});

it("keeps context for retry and hides backend details after preparation fails", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: false,
    status: 500,
    json: async () => ({
      detail: "Model private-model failed for candidate internal-123",
    }),
  } as Response);
  render(<App jobDescription={fixedJobDescription} />);
  fireEvent.change(screen.getByLabelText("Your time"), {
    target: { value: "30" },
  });
  await checkSetupMicrophone();
  fireEvent.submit(
    screen.getByRole("button", { name: "Prepare interview" }).closest("form")!,
  );
  await screen.findByRole("alert");
  expect(document.body.textContent).not.toContain("private-model");
  expect(document.body.textContent).not.toContain("internal-123");
  fireEvent.click(screen.getByRole("button", { name: /Back to setup/ }));
  expect((screen.getByLabelText("Your time") as HTMLSelectElement).value).toBe(
    "30",
  );
  expect(
    screen.getByRole("region", { name: "Full job description" }).textContent,
  ).toContain("Artificial Intelligence Intern");
  expect(
    screen.getByRole("button", { name: "Prepare interview" }),
  ).toBeTruthy();
});
