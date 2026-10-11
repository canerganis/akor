"""AKOR/1: small, provider-neutral agent messages and an in-memory relay.

No model calls, command execution, network access, or automatic tool actions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Callable, Iterable

VERSION = "AKOR/1"
MAX_LINE_BYTES = 8192
MAX_REF_BYTES = 65536
ID = r"[A-Za-z][A-Za-z0-9_-]{0,31}"
HEADER = re.compile(rf"([a-z]+) ({ID}) ({ID})>({ID}) (\{{.*\}})")
FIELDS = {
    "do": {"goal"},
    "fact": {"claim", "state"},
    "ask": {"q"},
    "need": {"ids"},
    "offer": {"change"},
    "review": {"on", "verdict", "reason"},
    "block": {"why"},
    "done": {"result", "check"},
    "stop": {"why"},
}


class ProtocolError(ValueError):
    """Malformed or semantically invalid protocol input."""


class StateError(ProtocolError):
    """Missing, conflicting, stale, or unauthorized relay state."""


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(ID, value) is not None


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate key: {key}")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise ProtocolError(f"invalid JSON constant: {value}")


def _id_list(value: object, name: str, *, nonempty: bool = False) -> None:
    if (not isinstance(value, list) or len(value) > 32
            or any(not identifier(item) for item in value)
            or len(set(value)) != len(value) or (nonempty and not value)):
        raise ProtocolError(f"{name} must contain unique IDs (maximum 32)")


def _validate(op: str, task: str, sender: str, recipient: str, body: dict) -> str:
    if op not in FIELDS or not all(map(identifier, (task, sender, recipient))):
        raise ProtocolError("unknown operation or invalid header")
    if not isinstance(body, dict):
        raise ProtocolError("body must be a JSON object")
    required = FIELDS[op] | {"v"}
    if not required <= body.keys() or body.keys() - required - {"refs"}:
        raise ProtocolError(f"{op} requires {sorted(required)}; only refs is optional")
    if type(body["v"]) is not int or not 1 <= body["v"] <= 2**31 - 1:
        raise ProtocolError("v must be a positive 32-bit integer")
    for key in FIELDS[op] - {"ids"}:
        if not isinstance(body[key], str) or not body[key].strip():
            raise ProtocolError(f"{key} must be a nonempty string")
    if "refs" in body:
        _id_list(body["refs"], "refs")
    if op == "need":
        _id_list(body["ids"], "ids", nonempty=True)
    if op == "fact":
        if body["state"] not in {"observed", "inferred", "unknown"}:
            raise ProtocolError("fact state must be observed, inferred, or unknown")
        if body["state"] == "observed" and not body.get("refs"):
            raise ProtocolError("an observed fact requires evidence refs")
    if op == "review":
        if body["verdict"] not in {"pass", "fail"} or not identifier(body["on"]):
            raise ProtocolError("review needs verdict pass/fail and a message ID in on")
    if op == "done":
        if body["check"] not in {"passed", "failed", "not_run"}:
            raise ProtocolError("done check must be passed, failed, or not_run")
        if body["check"] != "not_run" and not body.get("refs"):
            raise ProtocolError("test outcomes require evidence refs")
    try:
        canonical = compact(body)
        wire = f"{op} {task} {sender}>{recipient} {canonical}"
        if len(wire.encode("utf-8")) > MAX_LINE_BYTES:
            raise ProtocolError("message exceeds 8192 bytes; use a reference")
    except (UnicodeError, TypeError, ValueError) as exc:
        raise ProtocolError(str(exc)) from exc
    return canonical


@dataclass(frozen=True, init=False)
class Message:
    op: str
    task: str
    sender: str
    recipient: str
    _body: str

    def __init__(self, op: str, task: str, sender: str, recipient: str, body: dict):
        canonical = _validate(op, task, sender, recipient, body)
        for key, value in (("op", op), ("task", task), ("sender", sender),
                           ("recipient", recipient), ("_body", canonical)):
            object.__setattr__(self, key, value)

    @property
    def body(self) -> dict:
        return json.loads(self._body)

    def wire(self) -> str:
        return f"{self.op} {self.task} {self.sender}>{self.recipient} {self._body}"

    def as_dict(self) -> dict:
        return dict(op=self.op, task=self.task, sender=self.sender,
                    recipient=self.recipient, body=self.body)


def parse(line: str) -> Message:
    if not isinstance(line, str):
        raise ProtocolError("message must be text")
    try:
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ProtocolError("message exceeds 8192 bytes")
    except UnicodeError as exc:
        raise ProtocolError("invalid UTF-8 text") from exc
    match = HEADER.fullmatch(line)
    if not match:
        raise ProtocolError("expected: op task sender>recipient {JSON}")
    op, task, sender, recipient, raw = match.groups()
    try:
        body = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError(str(exc)) from exc
    return Message(op, task, sender, recipient, body)


@dataclass(frozen=True)
class Reference:
    name: str
    text: str
    sha256: str


@dataclass(frozen=True)
class Packet:
    ids: tuple[str, ...]
    references: tuple[Reference, ...]
    messages: tuple[Message, ...]
    related: tuple[tuple[str, Message], ...] = ()

    def render(self) -> str:
        if not self.ids:
            return ""
        lines = [VERSION]
        lines += [f"ref {r.name} {compact(r.text)}" for r in self.references]
        lines += [f"seen {mid} {msg.wire()}" for mid, msg in self.related]
        lines += [f"{mid} {msg.wire()}" for mid, msg in zip(self.ids, self.messages)]
        return "\n".join(lines)

    def as_dict(self) -> dict:
        result = {
            "version": VERSION,
            "references": {r.name: r.text for r in self.references},
            "messages": [dict(id=mid, **msg.as_dict())
                         for mid, msg in zip(self.ids, self.messages)],
        }
        if self.related:
            result['related'] = [dict(id=mid, **msg.as_dict()) for mid, msg in self.related]
        return result


class Hub:
    """Single-process reference relay. The caller owns authentication and tools.

    ACK means processed, never 'the model permanently remembers this'. The
    adapter declares refs physically present in the next model input; the
    conservative default resends all references required for pending work.
    """

    def __init__(self, peers: Iterable[str]):
        self.peers = frozenset(peers)
        if not self.peers or not all(map(identifier, self.peers)):
            raise ProtocolError("peers must be valid IDs")
        self._refs: dict[str, Reference] = {}
        self._tasks: dict[str, tuple[int, tuple[str, ...]]] = {}
        self._messages: dict[str, Message] = {}
        self._acked: set[str] = set()
        self._delivered: set[str] = set()

    def add_ref(self, name: str, text: str) -> Reference:
        if not identifier(name) or not isinstance(text, str) or not text.strip():
            raise ProtocolError("reference needs a valid ID and nonempty text")
        try:
            raw = text.encode("utf-8")
        except UnicodeError as exc:
            raise ProtocolError("reference must be UTF-8") from exc
        if len(raw) > MAX_REF_BYTES:
            raise ProtocolError("reference exceeds 65536 bytes; split it")
        ref = Reference(name, text, hashlib.sha256(raw).hexdigest())
        if name in self._refs and self._refs[name] != ref:
            raise StateError(f"immutable reference conflict: {name}; use a new ID")
        self._refs[name] = ref
        return ref

    def set_task(self, task: str, revision: int, context_refs: Iterable[str]) -> None:
        refs = tuple(context_refs)
        if not identifier(task) or type(revision) is not int or not 1 <= revision <= 2**31 - 1:
            raise ProtocolError("invalid task or revision")
        _id_list(list(refs), "context_refs", nonempty=True)
        if any(ref not in self._refs for ref in refs):
            raise StateError("task context reference is missing")
        if task in self._tasks:
            previous = self._tasks[task]
            if previous == (revision, refs):
                return
            if revision <= previous[0]:
                raise StateError("task revisions must increase")
            if any(m.task == task and mid not in self._acked
                   for mid, m in self._messages.items()):
                raise StateError("process pending messages before revising a task")
        self._tasks[task] = (revision, refs)

    def post(self, message_id: str, line: str, *, sender: str) -> str:
        """Assign a stable transport ID; retries with identical contents are no-ops."""
        if not identifier(message_id):
            raise ProtocolError("invalid message ID")
        msg = parse(line)
        if sender != msg.sender or sender not in self.peers or msg.recipient not in self.peers:
            raise StateError("sender binding or recipient mismatch")
        if message_id in self._messages:
            if self._messages[message_id] != msg:
                raise StateError("message ID reused with different contents")
            return message_id
        if msg.task not in self._tasks or msg.body["v"] != self._tasks[msg.task][0]:
            raise StateError("unknown task or stale revision; request current task context")
        missing = set(msg.body.get("refs", [])) - self._refs.keys()
        if missing:
            raise StateError(f"unresolved refs: {','.join(sorted(missing))}; request them with need")
        if msg.op == "review":
            original = self._messages.get(msg.body["on"])
            if (original is None or original.op not in {"offer", "done"}
                    or original.task != msg.task or original.body["v"] != msg.body["v"]
                    or original.recipient != msg.sender
                    or msg.body["on"] not in self._delivered
                    or msg.recipient != original.sender):
                raise StateError("review must target an offer/done addressed to this reviewer at this revision")
        self._messages[message_id] = msg
        return message_id

    def prepare(self, peer: str, *, retained_refs: Iterable[str] = (),
                max_bytes: int | None = None, max_tokens: int | None = None,
                count_tokens: Callable[[str], int] | None = None) -> Packet:
        """Return only unprocessed messages and required reference definitions.

        Limits apply to this packet, excluding the system prompt and model output.
        No truncation occurs. Failed preparation changes no delivery state.
        """
        if peer not in self.peers:
            raise StateError("unknown peer")
        for limit in (max_bytes, max_tokens):
            if limit is not None and (type(limit) is not int or limit < 0):
                raise ProtocolError("budgets must be nonnegative integers")
        if max_tokens is not None and count_tokens is None:
            raise ProtocolError("token budget requires a real tokenizer callback")
        retained = set(retained_refs)
        if not retained <= self._refs.keys():
            raise StateError("retained refs must already exist in this session")
        pending = [(mid, m) for mid, m in self._messages.items()
                   if m.recipient == peer and mid not in self._acked]
        needed: dict[str, None] = {}
        related: dict[str, Message] = {}
        for _, msg in pending:
            for name in (*self._tasks[msg.task][1], *msg.body.get("refs", [])):
                needed[name] = None
            if msg.op == 'review':
                original_id = msg.body['on']
                original = self._messages[original_id]
                related[original_id] = original
                for name in original.body.get('refs', []):
                    needed[name] = None
        packet = Packet(tuple(mid for mid, _ in pending),
                        tuple(self._refs[name] for name in needed if name not in retained),
                        tuple(msg for _, msg in pending), tuple(related.items()))
        rendered = packet.render()
        if max_bytes is not None and len(rendered.encode("utf-8")) > max_bytes:
            raise StateError("packet exceeds byte budget; split context or pending work")
        if max_tokens is not None and count_tokens(rendered) > max_tokens:
            raise StateError("packet exceeds token budget; split context or pending work")
        self._delivered.update(packet.ids)
        return packet

    def ack(self, peer: str, message_ids: Iterable[str]) -> None:
        ids = tuple(message_ids)
        if peer not in self.peers or any(
            mid not in self._delivered or self._messages[mid].recipient != peer for mid in ids
        ):
            raise StateError("ACK must name messages actually delivered to this peer")
        self._acked.update(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or decode AKOR/1 messages")
    parser.add_argument("command", choices=("validate", "decode"))
    parser.add_argument("file", type=Path, help="UTF-8 file with one agent message per line")
    args = parser.parse_args()
    try:
        messages = []
        for number, line in enumerate(args.file.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                messages.append(parse(line))
            except ProtocolError as exc:
                raise ProtocolError(f"line {number}: {exc}") from exc
        if not messages:
            raise ProtocolError("file contains no messages")
        if args.command == "decode":
            print(json.dumps([msg.as_dict() for msg in messages], ensure_ascii=False, indent=2))
        else:
            print(f"OK: {len(messages)} messages; syntax only, not evidence verification")
        return 0
    except (OSError, UnicodeError, ProtocolError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
