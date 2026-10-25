The radial visualizer and its animator are from LiveKit's official Agents UI,
https://github.com/livekit/components-js, commit
65701808b070bfdbba6627a5758dd13988b0141b. See LICENSE in this directory.

Files:

- agent-audio-visualizer-radial.tsx
- ../../hooks/agents-ui/use-agent-audio-visualizer-radial.ts

Integration: Tailwind CSS 4 supplies the upstream utility styles. The application
provides a hot-pink color, 48 bars, and the actual interviewer audio track and state
through useVoiceAssistant within the existing RoomContext. While the candidate
answers, the visualizer uses the local microphone track and speaking state.
A mute/unmute microphone
button is layered over the center; it controls the candidate's microphone.
