"""Deterministic relay demonstration; no real model or test execution."""

from pathlib import Path

from akor import Hub, parse


def main() -> None:
    hub = Hub(["lead", "coder"])
    hub.add_ref("R1", "DEMO ONLY. Goal: add a timeout; keep two retries. Units: seconds.")
    hub.add_ref("R2", "DEMO ONLY. src/client.py:42 at demo-rev: request(url), no timeout argument.")
    hub.add_ref("R3", "DEMO ONLY. Synthetic test report: timeout=5 seconds per attempt; retries=2; 3 checks passed.")
    hub.set_task("T1", 1, ["R1"])
    context = {"lead": set(), "coder": set()}
    lines = (Path(__file__).parent / "examples/demo.akor").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines, 1):
        msg = parse(line)
        hub.post(f"m{index}", line, sender=msg.sender)
        packet = hub.prepare(msg.recipient, retained_refs=context[msg.recipient])
        print(packet.render(), end="\n\n")
        # This demo retains each peer's complete transcript in a simulated context.
        context[msg.recipient].update(ref.name for ref in packet.references)
        hub.ack(msg.recipient, packet.ids)
    print("DEMO COMPLETE: 6 messages routed; no model calls or actual code changes.")


if __name__ == "__main__":
    main()
