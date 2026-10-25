from tests.api.test_workflows import client_for, prepare, session

AUTH = {"X-Agent-Secret": "local-interview-agent-change-me"}


def test_live_turns_and_removed_audio_routes(tmp_path, persona, plan, resume_pdf):
    with client_for(tmp_path, persona, plan) as client:
        state = session(client, prepare(client, resume_pdf)["candidate_id"])
        base = "/api/live-sessions/" + state["session_id"]
        assert state["status"] == "waiting" and state["deadline_at"] == 0
        assert client.post(base + "/audio-answers").status_code == 404
        assert client.get(base + "/prompt/audio").status_code == 404
        assert client.post(base + "/agent/events", json={"kind": "ready"}).status_code == 401
        client.post(base + "/agent/events", json={"kind": "ready"}, headers=AUTH).raise_for_status()
        client.post(
            base + "/agent/events", json={"kind": "joined"}, headers=AUTH
        ).raise_for_status()
        body = {
            "prompt_id": state["current_prompt"]["id"],
            "turn_id": "first",
            "text": "Use a unique constraint.",
        }
        first = client.post(base + "/agent/turns", json=body, headers=AUTH)
        assert first.status_code == 200, first.text
        assert first.json()["session"]["question_number"] == 2
        assert client.post(base + "/agent/turns", json=body, headers=AUTH).json() == first.json()
        assert "scoring_guidance" not in first.text
        assert client.post(base + "/end").json()["status"] == "completed"
        assert len(client.get(base + "/history").json()["events"]) == 1
    with client_for(tmp_path, persona, plan) as client:
        assert client.get(base).status_code == 404
        assert client.get(base + "/history").json()["session"]["status"] == "completed"


def test_browser_cannot_submit_transcripts_without_agent_secret(
    tmp_path, persona, plan, resume_pdf
):
    with client_for(tmp_path, persona, plan) as client:
        state = session(client, prepare(client, resume_pdf)["candidate_id"])
        base = "/api/live-sessions/" + state["session_id"]
        assert (
            client.post(
                base + "/agent/turns", json={"prompt_id": "p", "turn_id": "t", "text": "spoof"}
            ).status_code
            == 401
        )
        assert client.post(base + "/voice").status_code == 503
