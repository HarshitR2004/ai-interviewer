"""Pure transitions. Models propose actions; these rules authorize them."""

from uuid import uuid4

from .models import Decision


def question(state: dict) -> dict:
    return state["questions"][state["question_index"]]


def prompt(state: dict, text: str) -> dict:
    current = question(state)
    return {"id": uuid4().hex, "question_id": current["id"], "text": text}


def new_session(session_id: str, candidate_id: str, source: dict, now: float) -> dict:
    questions = []
    for section_index, section in enumerate(source["plan"]["sections"]):
        for question_index, item in enumerate(section["questions"]):
            questions.append(
                {
                    **item,
                    "id": f"s{section_index + 1}q{question_index + 1}",
                    "section_index": section_index,
                    "section_minutes": section["minutes"],
                    "competency": section["competency"],
                }
            )
    state = {
        "session_id": session_id,
        "candidate_id": candidate_id,
        "plan_snapshot": source,
        "questions": questions,
        "status": "active",
        "version": 1,
        "answer_version": 0,
        "question_index": 0,
        "follow_up_count": 0,
        "used_prepared_followups": [],
        "section_started_at": now,
        "deadline_at": now + source["settings"]["duration"] * 60,
        "answers": [],
        "evidence": [],
        "progression": [],
        "active_answer_event": None,
    }
    state["current_prompt"] = prompt(state, questions[0]["question"])
    return state


def close(state: dict, status: str = "completed") -> None:
    state["status"] = status
    state["current_prompt"] = None
    state["active_answer_event"] = None


def fallback(state: dict) -> Decision:
    used = state["used_prepared_followups"]
    for text in question(state)["follow_ups"]:
        if text not in used and state["follow_up_count"] < 2:
            return Decision(action="follow_up", next_question=text)
    return Decision(action="advance")


def transition(state: dict, decision: Decision, now: float) -> str:
    current = question(state)
    section_expired = now >= state["section_started_at"] + current["section_minutes"] * 60
    action = decision.action
    if now >= state["deadline_at"]:
        action = "finish"
    elif action in {"clarify", "follow_up"} and (state["follow_up_count"] >= 2 or section_expired):
        action = "advance"

    if action == "finish":
        close(state)
    elif action in {"clarify", "follow_up"}:
        state["follow_up_count"] += 1
        text = decision.next_question
        state["current_prompt"] = prompt(state, text)
        if text in current["follow_ups"]:
            state["used_prepared_followups"].append(text)
    else:
        index = state["question_index"] + 1
        if section_expired:
            while index < len(state["questions"]) and (
                state["questions"][index]["section_index"] == current["section_index"]
            ):
                index += 1
        if index >= len(state["questions"]):
            close(state)
            action = "finish"
        else:
            state["question_index"] = index
            state["follow_up_count"] = 0
            state["used_prepared_followups"] = []
            if question(state)["section_index"] != current["section_index"]:
                state["section_started_at"] = now
            state["current_prompt"] = prompt(state, question(state)["question"])
    state["active_answer_event"] = None
    return action


def public_session(state: dict) -> dict:
    return {
        "session_id": state["session_id"],
        "candidate_id": state["candidate_id"],
        "status": state["status"],
        "state_version": state["version"],
        "answer_version": state["answer_version"],
        "current_prompt": state["current_prompt"],
        "question_number": state["question_index"] + 1,
        "question_count": len(state["questions"]),
        "follow_up_count": state["follow_up_count"],
        "deadline_at": state["deadline_at"],
        "progression": state["progression"],
    }
