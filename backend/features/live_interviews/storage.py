"""Short SQLite transactions; never call a provider while a transaction is open."""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from . import graph
from .models import Decision, EngineError


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class SQLiteRepository:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self) -> None:
        def setup():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.executescript("""
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS creations (
                        event_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                        session_id TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS events (
                        session_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        payload_hash TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                        PRIMARY KEY(session_id, event_id)
                    );
                    CREATE TABLE IF NOT EXISTS decisions (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        source_version INTEGER NOT NULL, assessment TEXT NOT NULL,
                        disposition TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS commands (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        state_version INTEGER NOT NULL, payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending'
                    );
                    CREATE TABLE IF NOT EXISTS audio_receipts (
                        session_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        payload_hash TEXT NOT NULL, result TEXT,
                        PRIMARY KEY(session_id, event_id)
                    );
                """)

        await asyncio.to_thread(setup)

    async def transaction(self, operation):
        def run():
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN IMMEDIATE")
                return operation(db)

        try:
            return await asyncio.to_thread(run)
        except sqlite3.OperationalError as exc:
            raise EngineError(503, "Interview storage is temporarily unavailable.") from exc

    @staticmethod
    def load(db, session_id: str) -> dict:
        row = db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise EngineError(404, "Interview session not found.")
        return json.loads(row["state"])

    @staticmethod
    def save(db, state: dict, expected: int) -> None:
        state["version"] = expected + 1
        count = db.execute(
            "UPDATE sessions SET version=?, state=? WHERE id=? AND version=?",
            (state["version"], encode(state), state["session_id"], expected),
        ).rowcount
        if count != 1:
            raise EngineError(409, "Interview changed; reload before retrying.")

    @staticmethod
    def command(db, state: dict) -> None:
        payload = (
            {"kind": "speak", "prompt": state["current_prompt"]}
            if state["current_prompt"]
            else {"kind": "close", "status": state["status"]}
        )
        db.execute(
            "INSERT INTO commands(id, session_id, state_version, payload) VALUES(?,?,?,?)",
            (uuid4().hex, state["session_id"], state["version"], encode(payload)),
        )

    @staticmethod
    def existing(db, session_id, event_id, payload_hash):
        row = db.execute(
            "SELECT * FROM events WHERE session_id=? AND event_id=?", (session_id, event_id)
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise EngineError(409, "Event ID was already used for different input.")
        return json.loads(row["result"]) if row["result"] else {"status": row["status"]}

    @staticmethod
    def finish_event(db, session_id, event_id, result):
        db.execute(
            "UPDATE events SET status=?, result=? WHERE session_id=? AND event_id=?",
            (result["status"], encode(result), session_id, event_id),
        )

    @staticmethod
    def invalidate(db, session_id, status):
        db.execute(
            "UPDATE events SET status=?, result=? WHERE session_id=? AND status='processing'",
            (status, encode({"status": status}), session_id),
        )
        db.execute(
            "UPDATE commands SET status='superseded' WHERE session_id=? AND status='pending'",
            (session_id,),
        )
        # Audio intake can still be transcribing when a session closes.
        if status != "superseded":
            db.execute(
                "UPDATE audio_receipts SET result=? WHERE session_id=? AND result IS NULL",
                (encode({"status": status}), session_id),
            )

    async def create(self, request, source: dict | None, now: float) -> dict | None:
        def operation(db):
            row = db.execute(
                "SELECT * FROM creations WHERE event_id=?", (request.event_id,)
            ).fetchone()
            fingerprint = digest(request.model_dump())
            if row:
                if row["payload_hash"] != fingerprint:
                    raise EngineError(409, "Creation event ID was reused with different input.")
                return graph.public_session(self.load(db, row["session_id"]))
            if source is None:
                return None
            state = graph.new_session(uuid4().hex, request.candidate_id, source, now)
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)", (state["session_id"], 1, encode(state))
            )
            db.execute(
                "INSERT INTO creations VALUES(?,?,?)",
                (request.event_id, fingerprint, state["session_id"]),
            )
            self.command(db, state)
            return graph.public_session(state)

        return await self.transaction(operation)

    async def get(self, session_id: str) -> dict:
        return await self.transaction(lambda db: self.load(db, session_id))

    async def accept(self, session_id, event, now, *, audio=False):
        def operation(db):
            state = self.load(db, session_id)
            if (
                not audio
                and db.execute(
                    "SELECT 1 FROM audio_receipts WHERE session_id=? AND event_id=?",
                    (session_id, event.event_id),
                ).fetchone()
            ):
                raise EngineError(409, "Event ID belongs to an audio submission.")
            fingerprint = digest({"kind": "answer", **event.model_dump()})
            previous = self.existing(db, session_id, event.event_id, fingerprint)
            if previous is not None:
                return None, previous
            if state["status"] != "active" or now >= state["deadline_at"]:
                raise EngineError(409, "Interview is no longer accepting answers.")
            if event.prompt_id != state["current_prompt"]["id"]:
                raise EngineError(409, "This prompt is no longer current.")
            active = state["active_answer_event"]
            if event.replaces_event_id:
                if active != event.replaces_event_id:
                    raise EngineError(409, "Only the pending answer can be corrected.")
                self.finish_event(db, session_id, active, {"status": "superseded"})
            elif active:
                raise EngineError(409, "An answer to this prompt is already being assessed.")
            db.execute(
                "INSERT INTO events VALUES(?,?,?,'processing',NULL)",
                (session_id, event.event_id, fingerprint),
            )
            expected = state["version"]
            state["answer_version"] += 1
            state["active_answer_event"] = event.event_id
            state["answers"].append(
                {
                    **event.model_dump(),
                    "revision": state["answer_version"],
                    "accepted_at": now,
                    "question_id": state["current_prompt"]["question_id"],
                }
            )
            self.save(db, state, expected)
            return state, None

        return await self.transaction(operation)

    async def claim_audio(self, session_id, event_id, prompt_id, fingerprint, now):
        def operation(db):
            state = self.load(db, session_id)
            row = db.execute(
                "SELECT * FROM audio_receipts WHERE session_id=? AND event_id=?",
                (session_id, event_id),
            ).fetchone()
            if row:
                if row["payload_hash"] != fingerprint:
                    raise EngineError(409, "Audio event ID was reused with different input.")
                return json.loads(row["result"]) if row["result"] else {"status": "processing"}
            if db.execute(
                "SELECT 1 FROM events WHERE session_id=? AND event_id=?", (session_id, event_id)
            ).fetchone():
                raise EngineError(409, "Event ID already belongs to another submission.")
            if (
                state["status"] != "active"
                or now >= state["deadline_at"]
                or state["current_prompt"]["id"] != prompt_id
            ):
                raise EngineError(409, "This prompt is no longer current.")
            db.execute(
                "INSERT INTO audio_receipts VALUES(?,?,?,NULL)", (session_id, event_id, fingerprint)
            )
            return None

        return await self.transaction(operation)

    async def complete_audio(self, session_id, event_id, result):
        def operation(db):
            db.execute(
                "UPDATE audio_receipts SET result=? WHERE session_id=? AND event_id=? AND result IS NULL",
                (encode(result), session_id, event_id),
            )
            row = db.execute(
                "SELECT result FROM audio_receipts WHERE session_id=? AND event_id=?",
                (session_id, event_id),
            ).fetchone()
            return json.loads(row["result"])

        return await self.transaction(operation)

    async def commit(self, snapshot: dict, event_id: str, decision: Decision, now, unavailable):
        def operation(db):
            session_id = snapshot["session_id"]
            state = self.load(db, session_id)
            valid = (
                state["status"] == "active"
                and state["version"] == snapshot["version"]
                and state["answer_version"] == snapshot["answer_version"]
                and state["active_answer_event"] == event_id
                and state["current_prompt"]["id"] == snapshot["current_prompt"]["id"]
            )
            db.execute(
                "INSERT INTO decisions VALUES(?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    session_id,
                    event_id,
                    snapshot["version"],
                    encode(
                        {"decision": decision.model_dump(), "assessment_unavailable": unavailable}
                    ),
                    "accepted" if valid else "stale",
                ),
            )
            if not valid:
                row = db.execute(
                    "SELECT result FROM events WHERE session_id=? AND event_id=?",
                    (session_id, event_id),
                ).fetchone()
                return json.loads(row["result"]) if row and row["result"] else {"status": "stale"}
            if not unavailable:
                state["evidence"].append(
                    {
                        "event_id": event_id,
                        "question_id": state["current_prompt"]["question_id"],
                        "evidence": decision.evidence,
                        "missing_evidence": decision.missing_evidence,
                    }
                )
            action = graph.transition(state, decision, now)
            state["progression"].append({"action": action, "event_id": event_id})
            self.save(db, state, snapshot["version"])
            self.invalidate(db, session_id, "superseded")
            result = {
                "status": "completed",
                "action": action,
                "assessment_unavailable": unavailable,
                "session": graph.public_session(state),
            }
            self.finish_event(db, session_id, event_id, result)
            self.command(db, state)
            return result

        return await self.transaction(operation)

    async def end(self, session_id: str, event, now: float) -> dict:
        def operation(db):
            state = self.load(db, session_id)
            fingerprint = digest({"kind": "end", **event.model_dump()})
            previous = self.existing(db, session_id, event.event_id, fingerprint)
            if previous is not None:
                return previous
            if state["status"] == "active":
                expected = state["version"]
                graph.close(state)
                self.save(db, state, expected)
                self.invalidate(db, session_id, "cancelled")
                self.command(db, state)
            result = {"status": "completed", "session": graph.public_session(state)}
            db.execute(
                "INSERT INTO events VALUES(?,?,?,'completed',?)",
                (session_id, event.event_id, fingerprint, encode(result)),
            )
            return result

        return await self.transaction(operation)

    async def close_unfinished(self, now: float, *, restart=False) -> None:
        def operation(db):
            for row in db.execute("SELECT state FROM sessions").fetchall():
                state = json.loads(row["state"])
                if state["status"] != "active" or (not restart and now < state["deadline_at"]):
                    continue
                expected = state["version"]
                graph.close(state, "interrupted" if restart else "completed")
                self.save(db, state, expected)
                self.invalidate(db, state["session_id"], state["status"])
                self.command(db, state)

        await self.transaction(operation)
