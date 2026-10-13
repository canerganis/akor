# OZ/1: a meaning language for agents

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

This document describes the base atom language as of 0.2.0. For the current macros, the default 256-candidate search, batch input selection and the persistent queue, see [OZ/2](OZ2.md). The old search limit and the reports below belong to the historical release.

OZ is a symbolic language that combines defined concepts instead of regenerating words and JSON fields. For example, `a7` asks for a predefined review operation on a patch. If the active target is already 7, `a` is enough. `+8.` reports that test report 8 passed and completes the assigned step.

The alphabet of this language was not chosen for visual density. The inspiration taken from writing systems such as Egyptian, Chinese and cuneiform is that a sign carries a defined concept and that signs combine in a regular way. In OZ this idea is applied with a shared vocabulary, composition rules and explicit context; historical alphabets are not copied. The codebook approach may look like cryptography, but OZ is not encryption.

## Working structure

`oz.py` does three things:

1. **Resolves meaning:** It turns symbols into exact operations and references. No separate model call is made for this.
2. **Chooses the representation:** It counts the input text, including the receiver's symbol vocabulary and the required context. Among the supported representations it picks the cheaper one.
3. **Separates unnecessary calls:** It splits information requests, test status, blockers, step completion and stop requests out as host events. Waking another agent only to record these events is not needed.

The sending model's instructions, thinking time, tool use and provider message wrappers have their own cost. This module does not claim total savings by ignoring them. Human readability is not a selection criterion; correct preservation of meaning and measured token cost are the selection criteria.

## Vocabulary and grammar

| Form | Exact meaning |
|---|---|
| `aN` | Review patch N; preserve the public API; run the related tests; report errors |
| `rN` | Read source N; preserve numbers, units, constraints and uncertainties |
| `tN` | Request execution of the test procedure in N; do not claim a result |
| `>N` | Propose plan N; do not count it as implemented |
| `=N` | Report the sourced observation in N |
| `~N` | Report the hypothesis in N as an inference |
| `?N` | Request the definition of N; do not guess unknown content |
| `+N` | Report the successful result of test report N |
| `-N` | Report the failed result of test report N |
| `!N` | Report that progress is not possible because of N |
| `.` | Assigned step finished; does not mean test success or general approval |
| `/` | Stop request |
| `:text` | Carry new information that is not in the vocabulary, verbatim |

`N` is a reference id between 1 and 9999 with no leading zero. Example: `a7?3` is two atoms. No space or separator is needed. `a`, `r`, `t`, `>` may drop N only if the target equals the active reference. The reference of evidence and status atoms is never dropped: a bare `+`, `=`, `~`, `!`, `?` is invalid. `.` and `/` can only be the last atom.

A frame carries at most 64 atoms and 8192 UTF-8 bytes. Larger content is split. A frame that starts with `:` is entirely plain text; the signs after it are not interpreted as commands. This way new measurements, proper names, negative conditions and unusual details are not lost. The language should not be thought of as a system that turns all new information into a single sign: the meaning of a short sign must exist in the vocabulary or in the context that was sent.

## Who carries the context?

Routing information is kept by the host, outside the text the model produces: session, task, revision, sender, receiver, vocabulary version and reference contents. These are included in the SHA-256 fingerprint bound to the channel. A frame is not accepted with another channel's fingerprint.

This does not make the model's context free. The goal and sources needed to understand the task must be present in the real model input. References are provided with the source location and the full content. A new `Channel` is created for new context. The fingerprint is not verification or encryption; verifying the transport, fixing the message id, filtering retries and checking authorization are the adapter's responsibility.

`+8` is accepted only if 8 is a test report and its recorded status is `passed`. Success cannot be produced from `not_run`. This check audits the consistency of the record; it does not prove that the source text is correct or that a test was actually run. The host verifies the source.

## Usage

```powershell
cd C:\Users\can02\Projects\akor
python -X utf8 -m examples.oz_demo
python -m unittest discover -s tests -v
```

```python
from oz import Atom, Channel, Reference, prompt

channel = Channel(
    session="s1", task="T1", revision=1,
    sender="lead", recipient="worker",
    goal="Yamayı incele; API değişmesin.", active=7,
    references=[Reference(7, "patch", "Rev abc: timeout ekleyen yama.")],
)

agent_system_instructions = prompt()  # For the sender to produce this language.
wire = channel.encode([Atom("a", 7)])  # a
atoms = channel.accept(wire, binding=channel.binding)
request_for_receiver = channel.describe(atoms)
```

Choose the cheapest spelling among the bounded candidates with a real tokenizer:

```python
import tiktoken

enc = tiktoken.get_encoding("o200k_base")
count = lambda text: len(enc.encode(text, disallowed_special=()))
wire = channel.encode(atoms, counters=[count])
packet = channel.prepare(atoms, counters=[count])
model_input = packet["text"]
```

`encode` tries the spellings of the same meaning with the active reference kept and with it dropped. It evaluates at most 4096 candidates. If several tokenizers are given, it minimizes the highest token count first, then the total. Variables beyond the limit are written out explicitly. This is not a claim of a mathematical minimum over all possible languages.

`prepare` does not treat the vocabulary as free: it compares the symbolic input, including the needed atom definitions and the grammar, with the explicit meaning the program produces. In short, fresh contexts, the explicit meaning usually wins. The symbolic `wire` is obtained in both cases. In API sessions where a long shared context is stored, earlier tokens may be counted again; the adapter must track the provider's usage separately.

For a status message, pass it to the host without calling the receiving model:

```python
decision = channel.dispatch(wire, binding=channel.binding)
host_events = decision["host_events"]
if decision["needs_model"]:
    # Give only the atoms that need a decision or work to the relevant model.
    pass
```

`dispatch` runs no tool, grants no permission and makes no decision on the user's behalf. For example, applying a stop request or fetching a missing source is the host's job. If the next work step needs new reasoning, the host may call the model again.

## Verification and continuation

[Measurement report](reports/OZ-RESULTS.md), [raw token counts](reports/oz-token-counts.json), [live pilot](reports/oz-live.json).

```powershell
.\.venv\Scripts\python.exe -X utf8 oz_benchmark.py
python -X utf8 oz_live_eval.py --live
```

The last command consumes real model usage. Only synthetic examples are sent to the existing Codex and Claude CLI sessions; no key file is created and no global setting is changed. Encoding and decoding are tested in separate provider processes. Test traces stay in `.oz-eval/`; the report keeps only the needed answers and usage information. Without the opt-in `--live`, only the test prompt is printed.

The existing Orchestra Board and other applications were not changed automatically. The path to integrate into the package: sender instruction → short OZ output → host verification/event transfer → receiver input when needed. In production, success, correction rounds, total usage and latency should be compared on the same tasks. The core is independent; the scope of the live pilot is 12 synthetic examples.
