"use client";
import {
  useVoiceAssistant,
  useLocalParticipant,
  useIsSpeaking,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import { AgentAudioVisualizerRadial } from "./agents-ui/agent-audio-visualizer-radial";
import { MicIcon } from "./mic-icon";

export function VoicePresence({
  muted,
  disabled,
  onToggle,
}: {
  muted: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const { audioTrack, state } = useVoiceAssistant();
  const { localParticipant, microphoneTrack } = useLocalParticipant();
  const speaking = useIsSpeaking(localParticipant);
  const showMicrophone =
    state !== "speaking" && !muted && speaking && microphoneTrack;
  return (
    <div className="voice-presence">
      <div className="voice-orbit" aria-hidden="true" />
      <AgentAudioVisualizerRadial
        className="radial-voice"
        size="lg"
        radius={80}
        barCount={48}
        color="#ff2d89"
        audioTrack={
          showMicrophone
            ? {
                participant: localParticipant,
                publication: microphoneTrack,
                source: Track.Source.Microphone,
              }
            : audioTrack
        }
        state={showMicrophone ? "speaking" : state}
        aria-hidden="true"
      />
      <button
        className={`mic-core ${muted ? "is-muted" : ""}`}
        aria-label={muted ? "Unmute microphone" : "Mute microphone"}
        aria-pressed={muted}
        disabled={disabled}
        onClick={onToggle}
      >
        <MicIcon muted={muted} />
      </button>
      {(state === "speaking" || muted) && (
        <span className="voice-caption">
          {[state === "speaking" ? "Interviewer speaking" : "", muted ? "Microphone muted" : ""].filter(Boolean).join(" · ")}
        </span>
      )}
    </div>
  );
}
