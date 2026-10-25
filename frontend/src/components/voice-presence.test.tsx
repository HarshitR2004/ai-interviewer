// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
const fixture = vi.hoisted(() => ({
  state: "listening",
  speaking: true,
  audioTrack: { remote: true },
  microphone: { local: true },
  participant: { identity: "candidate" },
  visualizer: vi.fn(),
}));
vi.mock("@livekit/components-react", () => ({
  useVoiceAssistant: () => ({
    audioTrack: fixture.audioTrack,
    state: fixture.state,
  }),
  useLocalParticipant: () => ({
    localParticipant: fixture.participant,
    microphoneTrack: fixture.microphone,
  }),
  useIsSpeaking: () => fixture.speaking,
}));
vi.mock("./agents-ui/agent-audio-visualizer-radial", () => ({
  AgentAudioVisualizerRadial: (props: unknown) => {
    fixture.visualizer(props);
    return <div />;
  },
}));
import { VoicePresence } from "./voice-presence";
afterEach(() => {
  cleanup();
  fixture.visualizer.mockClear();
  fixture.state = "listening";
});
it("feeds the candidate microphone into the radial visualizer while answering", () => {
  const toggle = vi.fn();
  render(<VoicePresence muted={false} disabled={false} onToggle={toggle} />);
  expect(fixture.visualizer).toHaveBeenCalledWith(
    expect.objectContaining({
      state: "speaking",
      audioTrack: expect.objectContaining({ publication: fixture.microphone }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Mute microphone" }));
  expect(toggle).toHaveBeenCalledOnce();
});
it("feeds interviewer audio into the radial visualizer during a question", () => {
  fixture.state = "speaking";
  render(<VoicePresence muted={true} disabled={false} onToggle={() => {}} />);
  expect(fixture.visualizer).toHaveBeenCalledWith(
    expect.objectContaining({
      state: "speaking",
      audioTrack: fixture.audioTrack,
    }),
  );
  expect(screen.getByText(/Interviewer speaking/)).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Unmute microphone" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});
