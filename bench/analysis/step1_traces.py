"""Step 1 zero-call trace analysis (preregistration:
docs/design/next-2026-10-23/03-astra-accept-and-step1-prereg.md). Standard library only, no model calls.

    python bench/analysis/step1_traces.py                 # verify the manifest, print the headline totals
    python bench/analysis/step1_traces.py --md OUT.md     # regenerate every table (the results document)
    python bench/analysis/step1_traces.py --csv DIR       # per-call, per-run and per-cell CSV files
    python bench/analysis/step1_traces.py --freeze        # build the manifest (refuses to overwrite)

Order of operations (the preregistration): the path + SHA-256 manifest is frozen first (step1_manifest.json, built
by freeze() from the selectors in the preregistration, before any usage value was parsed). Every other step reads
only files listed there and refuses to run if a file changed.

Frozen accounting. Counters come from `modelUsage` where the corpus retained it. Where it did not, the counter
source is stated per record (see SOURCE_NOTES) and never guessed. Denominator per record:
input (uncached) + cache write + cache read + output, each token once at full weight; thinking is an output subset;
a missing or inseparable counter stays None. Monetary cost is out of scope.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "step1_manifest.json"
PREREG = "docs/design/next-2026-10-23/03-astra-accept-and-step1-prereg.md"
THRESHOLD = 0.25

# ----------------------------------------------------------------------------------------------------------------
# 1. Manifest (frozen before parsing)
# ----------------------------------------------------------------------------------------------------------------


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def select() -> list[dict]:
    """The preregistered selectors. Observation files supply usage; provenance files supply timing/attribution only."""
    out: dict[str, dict] = {}

    def add(p: Path, role: str, stratum: str, group: str, kind: str):
        out[rel(p)] = {"path": rel(p), "role": role, "stratum": stratum, "group": group, "kind": kind}

    data = ROOT / "bench/live/data"

    def jsonl_obs(pattern: str, group: str):
        for p in sorted(data.glob(pattern)):
            stratum = "smoke" if "smoke" in p.name else "main"
            add(p, "observation", stratum, group, "run-jsonl")
            m = p.with_name(p.stem + ".manifest.json")
            if m.exists():
                add(m, "provenance", stratum, group, "run-manifest")

    jsonl_obs("pilot2_*.jsonl", "pilot2")
    jsonl_obs("pilot2q_*.jsonl", "pilot2q")
    jsonl_obs("pilot_k*.jsonl", "pilot_k")
    for n in range(22, 30):
        jsonl_obs(f"live{n}_*.jsonl", f"live{n}")

    for dname in ("pilot_k2", "pilot_k2_smoke"):
        d = data / dname
        if not d.is_dir():
            continue
        stratum = "smoke" if "smoke" in dname else "main"
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if p.name == "transcript.jsonl":
                add(p, "observation", stratum, "pilot_k2-caller", "caller-transcript")
            elif p.name == "calls.jsonl" and "do" in p.relative_to(d).parts:
                add(p, "observation", stratum, "pilot_k2-worker", "worker-ledger")
            else:
                add(p, "provenance", stratum, "pilot_k2-dir", "run-file")

    for base, label in (("bench/step4/live1", "step4-live1"), ("bench/step4/live2", "step4-live2"),
                        ("bench/step4/live3", "step4-live3"), ("bench/o1/live1", "o1-live1")):
        b = ROOT / base
        for p in sorted(b.glob("calls-*.jsonl")):
            add(p, "observation", "main", label, "call-ledger")
        for p in sorted(b.glob("report-live-*.json")) + sorted(b.glob("candidates.jsonl")) + sorted(b.glob("baseline-live.json")):
            add(p, "provenance", "main", label, "report")
        if (b / "baseline").is_dir():
            for p in sorted((b / "baseline").rglob("*")):
                if p.is_file():
                    add(p, "provenance", "main", label, "baseline-capture")

    for base, label in (("bench/probe/boundary-evidence", "boundary-probe"), ("bench/step4/adopt-qual", "adopt-qual")):
        b = ROOT / base
        for p in sorted((b / "calls").glob("*/envelope.json")):
            add(p, "observation", "control", label, "envelope")
            for q in sorted(p.parent.iterdir()):
                if q.is_file() and q.name != "envelope.json":
                    add(q, "provenance", "control", label, "call-file")
        for name in ("ledger.jsonl", "report.json", "report.md"):
            if (b / name).exists():
                add(b / name, "provenance", "control", label, "report")
    return [out[k] for k in sorted(out)]


def manifest_digest(entries: list[dict]) -> str:
    text = "".join(f"{e['sha256']}  {e['path']}\n" for e in sorted(entries, key=lambda e: e["path"]))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def freeze() -> dict:
    entries = select()
    for e in entries:
        e["sha256"] = sha256_file(ROOT / e["path"])
        e["bytes"] = (ROOT / e["path"]).stat().st_size
    return {"preregistration": PREREG,
            "digest_definition": "sha256 over lines '<file sha256>  <path>\\n' sorted by path, all entries (observation and provenance)",
            "digest": manifest_digest(entries), "count": len(entries), "entries": entries}


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def verify_manifest(man: dict) -> list[str]:
    bad = []
    for e in man["entries"]:
        p = ROOT / e["path"]
        if not p.is_file():
            bad.append(f"missing {e['path']}")
        elif sha256_file(p) != e["sha256"]:
            bad.append(f"changed {e['path']}")
    if manifest_digest(man["entries"]) != man["digest"]:
        bad.append("manifest digest does not match its entries")
    return bad


# ----------------------------------------------------------------------------------------------------------------
# 2. Normalised records
# ----------------------------------------------------------------------------------------------------------------

INF = float("inf")


def read_jsonl(path: Path):
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if line:
                out.append((i, json.loads(line)))
    return out


def epoch(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def new_unit(**kw) -> dict:
    u = {"uid": None, "src": None, "loc": None, "stratum": "main", "group": None, "kind": "run", "run_key": None,
         "workload": None, "model": "unrecorded", "size": None, "arm": None, "scenario": "n/a",
         "model_needed": False, "mn_reason": "", "ctr_source": "", "inu": None, "cw": None, "cr": None,
         "in_total": None, "out": None, "think": None, "thinking_source": "", "wall_ms": None, "api_ms": None,
         "ttr_ms": None, "inflight_ms": None, "start": None, "end": None, "failed": False, "resent": False,
         "check_driven": False, "caller_overhead": False, "est_prompt": None, "sys_sha": None, "prompt_sha": None,
         "sys_bytes": None, "sys_est": None, "call_id": None, "resent_origin": False, "attempt": None, "retry_of": None, "outcome": "", "note": "", "queued": None}
    u.update(kw)
    return u


def finish(u: dict) -> dict:
    """Derive in_total when the three input counters are known; never invent one."""
    if u["in_total"] is None and None not in (u["inu"], u["cw"], u["cr"]):
        u["in_total"] = u["inu"] + u["cw"] + u["cr"]
    return u


def usage_from_model_usage(mu):
    """Sum modelUsage over every reported model. None for a counter any model entry lacks."""
    if not isinstance(mu, dict) or not mu:
        return None
    res = {}
    for key, name in (("inputTokens", "inu"), ("cacheCreationInputTokens", "cw"), ("cacheReadInputTokens", "cr"),
                      ("outputTokens", "out"), ("thinkingTokens", "think")):
        vals = [m.get(key) if isinstance(m, dict) else None for m in mu.values()]
        res[name] = sum(vals) if all(type(v) is int and v >= 0 for v in vals) else None
    res["models"] = sorted(mu)
    return res


# ---- 2a. flat run rows: pilot2, pilot2q, live22-29, old pilot_k ------------------------------------------------

def parse_flat(entry, man_by_path) -> list[dict]:
    path = ROOT / entry["path"]
    stem = path.stem
    group = entry["group"]
    mpath = rel(path.with_name(stem + ".manifest.json"))
    mf = json.loads((ROOT / mpath).read_text(encoding="utf-8")) if mpath in man_by_path else {}
    het = bool(mf.get("header"))
    units = []
    for ln, r in read_jsonl(path):
        if group == "pilot_k":
            u = new_unit(uid=f"{entry['path']}:{ln}", src=entry["path"], loc=f"line {ln}", stratum=entry["stratum"],
                         group=group, kind="run", run_key=f"{entry['path']}:{ln}", workload=f"pilot_k-{stem}",
                         model=mf.get("model", "claude-sonnet-5-5"), size=r.get("n"), arm=r.get("arm"),
                         ctr_source="runner-summed modelUsage (pilot_k.py:78-81); cache write and thinking not recorded",
                         in_total=r.get("in"), out=r.get("out"), wall_ms=_ms(r.get("wall_s")))
            u["failed"] = not r.get("valid", True)
            u["caller_overhead"] = False
            u["note"] = f"caller_in={r.get('caller_in')} caller_cache_read={r.get('caller_cache_read')} caller_out={r.get('caller_out')} worker_in={r.get('worker_in')} worker_out={r.get('worker_out')}"
            u["_caller_tokens"] = (r.get("caller_in"), r.get("caller_out"))
            u["_worker_tokens"] = (r.get("worker_in"), r.get("worker_out"))
            units.append(finish(u))
            continue
        pilot = group in ("pilot2", "pilot2q")
        src = ("runner-summed modelUsage over every reported model incl. subagents (pilot2.py:66-71)" if pilot else
               "CLI result.usage via run_live.call (run_live.py:119-127); modelUsage not retained, exact for a single "
               "turn, turn count not stored")
        size = r.get("jobs") if pilot else (r.get("n") or mf.get("n"))
        wl = "pilot2-materials-1g" if pilot else stem
        u = new_unit(uid=f"{entry['path']}:{ln}", src=entry["path"], loc=f"line {ln}", stratum=entry["stratum"],
                     group=group, run_key=f"{entry['path']}:{ln}", workload=wl, model=r.get("model") or mf.get("model", "unrecorded"),
                     size=size, arm=r.get("arm"), scenario="het" if het else "std", ctr_source=src,
                     inu=r.get("in_uncached"), cw=r.get("cache_write"), cr=r.get("cache_read"), in_total=r.get("in"),
                     out=r.get("out"), think=r.get("thinking"), thinking_source="same source as counters",
                     wall_ms=_ms(r.get("wall_s")), api_ms=r.get("api_ms"), est_prompt=r.get("packet_o200k"))
        u["failed"] = bool(r.get("is_error")) or not r.get("valid", True)
        u["outcome"] = "valid" if r.get("valid") else (r.get("error") or "invalid")
        units.append(finish(u))
    return units


def _ms(sec):
    return None if sec is None else round(sec * 1000)


# ---- 2b. pilot_k2: caller transcripts and worker ledgers -------------------------------------------------------

def parse_k2(man) -> list[dict]:
    units = []
    ents = {e["path"]: e for e in man["entries"]}
    for e in man["entries"]:
        if e["role"] != "observation" or e["group"] not in ("pilot_k2-caller", "pilot_k2-worker"):
            continue
        parts = Path(e["path"]).parts
        i = parts.index("data")
        top, tag = parts[i + 1], parts[i + 2]
        base = "/".join(parts[:i + 3])
        spec = json.loads((ROOT / base / "spec.json").read_text(encoding="utf-8"))
        rec_path = f"{base}/record.json"
        rec = json.loads((ROOT / rec_path).read_text(encoding="utf-8"))
        block, contract, arm, n = spec.get("block"), spec.get("contract"), spec.get("arm"), spec.get("n")
        wl = f"pilot_k2-{block}-{contract}"
        common = dict(src=e["path"], stratum=e["stratum"], group=e["group"], run_key=f"{base}", workload=wl, size=n,
                      arm=arm, scenario="n/a", wall_ms=_ms(rec.get("wall_s")))
        if e["group"] == "pilot_k2-caller":
            res = None
            n_res, stamps = 0, []
            for ln, o in read_jsonl(ROOT / e["path"]):
                if o.get("type") == "result":
                    res = (ln, o)
                    n_res += 1
                if o.get("timestamp"):
                    stamps.append(epoch(o["timestamp"]))
            gaps = [b - a for a, b in zip(stamps, stamps[1:]) if a is not None and b is not None]
            if res is None:
                u = new_unit(uid=f"{e['path']}:none", loc="no result event", kind="caller", failed=True,
                             ctr_source="no result event: accounting missing", **common)
                units.append(finish(u)); continue
            ln, o = res
            us = usage_from_model_usage(o.get("modelUsage"))
            models = us["models"] if us else []
            u = new_unit(uid=f"{e['path']}:{ln}", loc=f"line {ln} result.modelUsage", kind="caller",
                         model=",".join(models) or "unrecorded",
                         ctr_source="raw modelUsage (all turns, all models)", thinking_source="raw modelUsage.thinkingTokens",
                         inu=us and us["inu"], cw=us and us["cw"], cr=us and us["cr"], out=us and us["out"],
                         think=us and us["think"], api_ms=o.get("duration_api_ms"), ttr_ms=o.get("time_to_request_ms"),
                         inflight_ms=o.get("duration_ms"), queued=o.get("queued_turn_count"),
                         failed=bool(o.get("is_error")), outcome=o.get("subtype") or "", **common)
            u["caller_overhead"] = arm != "J"
            if n_res > 1:
                u["note"] += f"{n_res} result events (modelUsage is cumulative, the last is used); "
            if gaps and max(gaps) > 120:
                u["note"] += f"largest gap between recorded events {max(gaps):.0f} s; "
            u["_turns"] = o.get("num_turns")
            u["_record_caller"] = (rec.get("caller_in"), rec.get("caller_in_uncached"), rec.get("caller_cache_read"),
                                   rec.get("caller_cache_write"), rec.get("caller_out"))
            u["_verified"] = (rec.get("verified"), rec.get("jobs"))
            units.append(finish(u))
        else:
            doj = Path(e["path"]).parent / "do.jsonl"
            model = "unrecorded"
            if doj.as_posix() in ents:
                for _, d in read_jsonl(ROOT / doj):
                    model = d.get("model") or model
            ends, starts = {}, {}
            for ln, o in read_jsonl(ROOT / e["path"]):
                if o.get("event") == "call_start":
                    starts[o["call_id"]] = (ln, o)
                elif o.get("event") == "call_end":
                    ends[o["call_id"]] = (ln, o)
            for cid, (ln0, s) in starts.items():
                if cid in ends:
                    ln, o = ends[cid]
                    units.append(ledger_unit(o, e, ln, model, kind="worker", **common))
                else:
                    units.append(ledger_unit(s, e, ln0, model, kind="worker", **common))
    return units


def ledger_unit(o, e, ln, model, kind="call", **common) -> dict:
    """One call from an akor.call/1 ledger. usage is the adapter's, derived from the envelope's modelUsage
    (examples/claude_cli_adapter.py:16-30); input_tokens includes the cached counters; reasoning is not recorded."""
    us = o.get("usage") or {}
    raw = us.get("raw") or {}
    complete = o.get("event") == "call_end" and us.get("source") is not None and us.get("input_tokens") is not None
    if complete:
        cr = us.get("cache_read_tokens")
        cw = us.get("cache_write_tokens")
        total = us.get("input_tokens")
        inu = total - cr - cw if None not in (total, cr, cw) else None
        out = us.get("output_tokens")
    else:
        inu = cw = cr = total = out = None
    tev = o.get("token_estimates") or {}
    val = o.get("validation") or {}
    u = new_unit(uid=f"{e['path']}:{ln}", loc=f"line {ln} {o.get('event')}", kind=kind, model=model,
                 ctr_source="adapter call ledger (from envelope modelUsage); reasoning tokens not recorded",
                 inu=inu, cw=cw, cr=cr, in_total=total, out=out,
                 inflight_ms=o.get("elapsed_ms"), start=epoch(o.get("started_at")), end=epoch(o.get("ended_at")),
                 est_prompt=tev.get("prompt"), sys_sha=o.get("system_sha256"), prompt_sha=o.get("prompt_sha256"),
                 sys_bytes=o.get("system_bytes"), sys_est=tev.get("system"), call_id=o.get("call_id"), attempt=o.get("attempt"), retry_of=o.get("retry_of"),
                 outcome=o.get("outcome") or ("no call_end (killed or unrecorded)" if o.get("event") == "call_start" else ""),
                 **common)
    u["resent"] = bool(o.get("retry_of")) or (o.get("attempt") or 1) > 1
    # a call with no call_end was killed after launch; if its capture was recovered the result was used, so it is not
    # wasted work and is not tagged failed (the recovered usage comes from the report, see parse_ledgers)
    u["failed"] = o.get("event") == "call_end" and ((o.get("exit_code") not in (0, None)) or bool(o.get("timed_out"))
                                                   or (o.get("outcome") not in (None, "ok")))
    if val.get("failed_results"):
        u["check_driven"] = True
        u["rejected_results"] = val.get("failed_results")
    u["_job_members"] = [j.get("inbox_job_id") for j in o.get("job_map", [])]
    return finish(u)


# ---- 2c. step4 / O1 call ledgers -------------------------------------------------------------------------------

LEDGER_NAME = re.compile(r"calls-(live\d)-(clean|interrupt|stale|repeat|bump)-(.+)-([0-9a-f]{12})\.jsonl$")


def parse_ledgers(man) -> list[dict]:
    units = []
    ents = {e["path"]: e for e in man["entries"]}
    for e in man["entries"]:
        if e["kind"] != "call-ledger":
            continue
        p = Path(e["path"])
        m = LEDGER_NAME.search(p.name)
        prefix, scenario, stage = m.group(1), m.group(2), m.group(3)
        label = e["group"]
        # the report of the same live run supplies thinking tokens and recovered usage (envelope not in the corpus)
        rep_path = rel(ROOT / p.parent / f"report-live-{prefix}.json")
        report = json.loads((ROOT / rep_path).read_text(encoding="utf-8")) if rep_path in ents else {}
        rows = report.get("thinking_tokens_per_call") or []
        report_models = sorted(set(re.findall(r"claude-[a-z0-9-]+", json.dumps(report))))
        report_model = report_models[0] if len(report_models) == 1 else "unrecorded"
        o1 = label.startswith("o1")
        starts, ends = OrderedDict(), {}
        for ln, o in read_jsonl(ROOT / e["path"]):
            if o["event"] == "call_start":
                starts[o["call_id"]] = (ln, o)
            elif o["event"] == "call_end":
                ends[o["call_id"]] = (ln, o)
        for cid, (ln0, s) in starts.items():
            ln, o = ends.get(cid, (ln0, s))
            common = dict(src=e["path"], stratum=e["stratum"], group=label,
                          run_key=f"{label}:{scenario}", workload=("o1-repair-handoff-20" if o1 else "step4-inspection-handoff-20") + f"/{prefix}",
                          size=len(s.get("job_map", [])), arm=stage, scenario=scenario)
            u = ledger_unit(o, e, ln, report_model, **common)
            u["model_needed"] = o1
            u["mn_reason"] = ("model writes code; checks execute the candidate (o1_tier_a), none recomputes the answer" if o1 else
                              "every check recomputes the full answer (mat_fields/mat_bounds/mat_classify): host-computable")
            # join the report row: (scenario, receipt, stage prefix)
            pre = u["arm"]
            hit = [r for r in rows if r.get("scenario") == scenario and str(r.get("receipt")) == str(s.get("batch_id"))
                   and r["members"] and pre.endswith(r["members"][0].rsplit("_", 1)[0])
                   and r.get("attempt") == s.get("attempt") and len(r["members"]) == len(s.get("job_map", []))]
            if len(hit) > 1 and u["in_total"] is not None:
                hit = [r for r in hit if (r.get("input_tokens"), r.get("output_tokens")) == (u["in_total"], u["out"])]
            if len(hit) == 1:
                r = hit[0]
                if u["in_total"] is not None and (u["in_total"] != r.get("input_tokens") or u["out"] != r.get("output_tokens")):
                    u["note"] += "report tokens differ from ledger; "
                u["think"] = r.get("thinking_tokens")
                u["thinking_source"] = f"{rep_path} thinking_tokens_per_call (retained envelope modelUsage.thinkingTokens)"
                mod = r.get("model")
                if mod:
                    u["model"] = ",".join(mod)
                if u["in_total"] is None and type(r.get("input_tokens")) is int:
                    u["in_total"] = r["input_tokens"]
                    u["out"] = r["output_tokens"]
                    u["ctr_source"] = f"recovered usage from {rep_path} (envelope not retained in corpus); cache split unknown"
                    u["outcome"] = "no call_end; capture recovered, no new call"
            elif len(hit) > 1:
                u["note"] += "ambiguous report join; "
            elif rows:
                u["note"] += "no report row; "
            units.append(u)
    # A resend (retry_of) exists because a check rejected part of the original call's answer: the resend and its origin
    # are check-driven work. The call ledger's own validation is structural, so the origin is identified by retry_of.
    by_id = {u["call_id"]: u for u in units if u["call_id"]}
    for u in units:
        if u["resent"]:
            u["check_driven"] = True
            origin = by_id.get(u["retry_of"])
            if origin is not None:
                origin["resent_origin"] = True
                origin["check_driven"] = True
    return units


# ---- 2d. envelope controls -------------------------------------------------------------------------------------

def parse_envelopes(man) -> list[dict]:
    units = []
    ledgers = {}
    for e in man["entries"]:
        if e["kind"] == "report" and e["path"].endswith("ledger.jsonl"):
            for ln, o in read_jsonl(ROOT / e["path"]):
                if o.get("event") == "end":
                    ledgers[(e["group"], o["call_id"])] = (e["path"], ln, o)
    for e in man["entries"]:
        if e["kind"] != "envelope":
            continue
        p = ROOT / e["path"]
        env = json.loads(p.read_text(encoding="utf-8"))
        meta = json.loads((p.parent / "meta.json").read_text(encoding="utf-8"))
        la, en = meta["launch"], meta["end"]
        us = usage_from_model_usage(env.get("modelUsage"))
        cid = la.get("call_id")
        lg = ledgers.get((e["group"], cid))
        ev = (lg[2].get("evaluation") if lg else None) or {}
        cell_name = la.get("cell") or "size4"
        name = p.parent.name
        u = new_unit(uid=f"{e['path']}", src=e["path"], loc="envelope.json modelUsage", stratum="control",
                     group=e["group"], kind="envelope", run_key=f"{e['group']}/{name}",
                     workload=("boundary-probe" if e["group"] == "boundary-probe" else "adopt-qual"),
                     model=",".join(us["models"]) if us else "unrecorded", size=4,
                     arm=la.get("arm"), scenario=cell_name if e["group"] == "adopt-qual" else f"block{la.get('block')}",
                     model_needed=False,
                     mn_reason="classification: mat_classify recomputes the full answer (host-computable)",
                     ctr_source="raw modelUsage", thinking_source="raw modelUsage.thinkingTokens",
                     inu=us and us["inu"], cw=us and us["cw"], cr=us and us["cr"], out=us and us["out"],
                     think=us and us["think"], api_ms=env.get("duration_api_ms"), ttr_ms=env.get("time_to_request_ms"),
                     inflight_ms=env.get("duration_ms"), wall_ms=round((en.get("ts", 0) - la.get("ts", 0)) * 1000),
                     start=la.get("ts"), end=en.get("ts"), queued=env.get("queued_turn_count"),
                     sys_sha=la.get("system_sha256"), prompt_sha=la.get("prompt_sha256"),
                     failed=bool(env.get("is_error")) or (ev.get("entirely_correct") is False),
                     outcome=str(ev.get("outcome") or env.get("subtype") or ""))
        u["_sys_bytes_unknown"] = True
        units.append(finish(u))
    return units


# ----------------------------------------------------------------------------------------------------------------
# 3. Attribution: split billed input into fixed per-call input and packet input (regression on billed totals)
# ----------------------------------------------------------------------------------------------------------------

def ols(xs, ys):
    n = len(xs)
    if n < 3 or len(set(xs)) < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    b = sxy / sxx
    return {"n": n, "a": my - b * mx, "b": b, "r2": (sxy * sxy / (sxx * syy)) if syy else 1.0}


def fit_groups(units):
    """Per (group, model, arm-family) fit  in_total = a + b * estimated_prompt_tokens. Used only when n>=5 and R^2>=0.99."""
    g = defaultdict(list)
    for u in units:
        if u["in_total"] is not None and u["est_prompt"] is not None and u["inu"] is not None:
            fam = u["arm"] if u["group"].startswith("live") or u["group"] in ("pilot_k2-caller",) else "*"
            g[(u["workload"].split("/")[0], u["model"], u["stratum"], fam)].append(u)
    fits = {}
    for k, lst in g.items():
        f = ols([u["est_prompt"] for u in lst], [u["in_total"] for u in lst])
        if f and f["n"] >= 5 and f["r2"] >= 0.99:
            fits[k] = f
    return fits


def fit_key(u):
    fam = u["arm"] if u["group"].startswith("live") or u["group"] in ("pilot_k2-caller",) else "*"
    return (u["workload"].split("/")[0], u["model"], u["stratum"], fam)


TOKEN_CATS = ("thinking", "visible_out", "packet_in", "fixed_in", "input_unsplit")


def split_tokens(u, fits):
    """Per-call categories. thinking and visible_out come straight from counters. packet_in = slope * estimate (a
    measured-total regression, an estimate); fixed_in is the remainder of the billed input: H plus the CLI's own
    framing, which the corpus cannot separate (explicitly unattributed residual)."""
    c = {k: None for k in TOKEN_CATS}
    if u["out"] is not None and u["think"] is not None:
        c["thinking"] = u["think"]
        c["visible_out"] = u["out"] - u["think"]
    if u["in_total"] is not None:
        f = fits.get(fit_key(u)) if u["est_prompt"] is not None else None
        if f:
            pk = min(u["in_total"], max(0.0, f["b"] * u["est_prompt"]))
            c["packet_in"] = pk
            c["fixed_in"] = u["in_total"] - pk
        else:
            c["input_unsplit"] = u["in_total"]
    return c


def tag_failed_resent(u):
    return bool(u["failed"] or u["resent"] or u["resent_origin"])


def denom(u):
    return u["in_total"] + u["out"] if u["in_total"] is not None and u["out"] is not None else None


# ----------------------------------------------------------------------------------------------------------------
# 4. Cells, run breakdowns, time partition
# ----------------------------------------------------------------------------------------------------------------

VARIABLE = {"thinking": "reasoning effort (CLI --effort)",
            "visible_out": None,           # the deliverable itself
            "packet_in": None,             # the job payload itself
            "fixed_in": None,              # H + CLI framing, inseparable: no single named variable can be assigned
            "input_unsplit": None,
            "failed_resent": "retry and re-ask policy",
            "check_driven": "retry and re-ask policy",
            "caller_overhead": "delegation mode",
            "avoidable_waiting": "scheduling (concurrency of independent calls)"}
CAT_STATUS = {"thinking": "counter", "visible_out": "counter minus counter", "packet_in": "estimate (regression)",
              "fixed_in": "unattributed residual (H plus CLI framing, inseparable)",
              "input_unsplit": "unattributed (no split evidence)"}


def cell_key(u):
    return (u["workload"], u["model"], u["size"], u["arm"], u["scenario"], u["stratum"])


def aggregate_cell(units, fits):
    cells = OrderedDict()
    for u in units:
        cells.setdefault(cell_key(u), []).append(u)
        if u["kind"] == "call":                      # ledger runs: also the all-stages cell of the same workload/size/scenario
            k = cell_key(u)
            cells.setdefault((k[0], k[1], k[2], "* (all stages)", k[4], k[5]), []).append(u)
    out = []
    for k, lst in cells.items():
        d_tot = 0
        d_known = 0
        cats = {c: [0, 0] for c in TOKEN_CATS}       # sum over known, count unknown
        tags = {"failed_resent": [0, 0], "check_driven": [0, 0], "caller_overhead": [0, 0]}
        for u in lst:
            dn = denom(u)
            if dn is None:
                d_known += 0
                for c in cats:
                    cats[c][1] += 1
                for t in tags:
                    tags[t][1] += 1
                continue
            d_tot += dn
            d_known += 1
            sp = split_tokens(u, fits)
            for c in cats:
                if sp[c] is None:
                    cats[c][1] += 1
                else:
                    cats[c][0] += sp[c]
            if tag_failed_resent(u):
                tags["failed_resent"][0] += dn
            if u["check_driven"]:
                tags["check_driven"][0] += dn
            if u["caller_overhead"] and u["kind"] == "caller":
                tags["caller_overhead"][0] += dn
        o = {"cell": k, "calls": len(lst), "calls_with_denominator": d_known, "denominator": d_tot, "cats": cats,
             "tags": tags, "model_needed": all(u["model_needed"] for u in lst), "mn_reason": lst[0]["mn_reason"],
             "units": lst}
        out.append(o)
    return out


def share(cell, name):
    """(share, status) status 'known' only when every call with a denominator has this category attributed."""
    if cell["denominator"] == 0:
        return None, "no denominator"
    if name in cell["cats"]:
        total, unknown = cell["cats"][name]
        known_calls = cell["calls_with_denominator"] - unknown
        if known_calls == 0:
            return None, "unknown"
        if unknown or cell["calls_with_denominator"] != cell["calls"]:
            return total / cell["denominator"], "partial"
        return total / cell["denominator"], "known"
    total, unknown = cell["tags"][name]
    if cell["calls_with_denominator"] != cell["calls"]:
        return total / cell["denominator"], "partial"
    return total / cell["denominator"], "known"


def run_groups(units):
    runs = OrderedDict()
    for u in units:
        runs.setdefault((u["run_key"], u["stratum"]), []).append(u)
    return runs


def union_ms(intervals):
    iv = sorted((a, b) for a, b in intervals if a is not None and b is not None and b > a)
    tot, cur = 0.0, None
    for a, b in iv:
        if cur is None or a > cur[1]:
            if cur:
                tot += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        tot += cur[1] - cur[0]
    return tot * 1000


def partition_run(lst):
    """Time partition of one run's end-to-end wall.
    active   = measured critical-path work: model API time (api_ms) plus measured pre-request harness time (ttr_ms) of
               single-process runs; for ledger-only calls (no API split recorded) the call's in-flight interval, taken
               as one unsplit measurement; worker calls nested inside a caller are inside the caller's wall (union, never summed).
    waiting  = avoidable waiting: only a measured queue (queued_turn_count) or an interval proven idle and avoidable;
               no source records one, so it is 0 and the idle gaps stay unresolved.
    unresolved = wall minus active (process start/exit, CLI internals, host work between calls, gaps)."""
    kinds = {u["kind"] for u in lst}
    wall = None
    active = None
    note = ""
    if kinds <= {"run", "envelope"}:
        u = lst[0]
        wall = u["wall_ms"]
        if wall is not None and u["api_ms"] is not None:
            active = min(wall, u["api_ms"] + (u["ttr_ms"] or 0))
            note = "api_ms + time_to_request_ms"
        elif wall is not None:
            note = "api_ms not recorded"
    elif kinds <= {"call"}:
        iv = [(u["start"], u["end"]) for u in lst if u["start"] is not None and u["end"] is not None]
        starts = [u["start"] for u in lst if u["start"] is not None]
        ends = [u["end"] for u in lst if u["end"] is not None]
        missing = any(u["end"] is None for u in lst)
        if starts and ends and not missing:
            wall = (max(ends) - min(starts)) * 1000
            active = union_ms(iv)
            note = "span first start to last end; run end-to-end wall (incl. host work after the last call) is not recorded"
        elif starts:
            note = "a call has no end timestamp: span unknown"
            ends2 = [u["start"] + u["inflight_ms"] / 1000 for u in lst if u["start"] and u["inflight_ms"]]
    else:  # caller + worker
        callers = [u for u in lst if u["kind"] == "caller"]
        wall = callers[0]["wall_ms"] if callers else None
        if callers and callers[0]["api_ms"] is not None and wall is not None:
            wk = [(u["start"], u["end"]) for u in lst if u["kind"] == "worker" and u["start"] is not None and u["end"] is not None]
            active = min(wall, callers[0]["api_ms"] + (callers[0]["ttr_ms"] or 0) + union_ms(wk))
            note = "caller api_ms + time_to_request_ms + worker in-flight (nested in the caller's tool wait, union)"
    unresolved = wall - active if wall is not None and active is not None else None
    return {"wall_ms": wall, "active_ms": active, "avoidable_ms": 0 if active is not None else None,
            "unresolved_ms": unresolved, "note": note}


# ----------------------------------------------------------------------------------------------------------------
# 5. Host-computable scan
# ----------------------------------------------------------------------------------------------------------------

CHECK_CLASS = {
    # name: (recomputes_full_answer, why)
    "mat_fields": (True, "v == [r[f] for f in FIELDS]: the answer is a pure function of the ref text"),
    "mat_bounds": (True, "v == bounds_of(r): Decimal arithmetic on the ref"),
    "mat_classify": (True, "v == status_of(bounds_of(r)): Decimal arithmetic on the ref"),
    "mat_classify_interval": (True, "interval recomputed from the record and label from the goal limits"),
    "json_type": (False, "structural type test"),
    "o1_source": (False, "byte-length test of the candidate source"),
    "o1_policy": (False, "AST policy test of the candidate; does not produce the answer"),
    "o1_tier_a": (False, "runs the candidate against executable expected rows; the host can judge code but not write it"),
}
CHECK_SRC = {"mat_fields": "bench/step4/workflow.py", "mat_bounds": "bench/step4/workflow.py",
             "mat_classify": "bench/step4/workflow.py", "mat_classify_interval": "bench/step4/workflow.py",
             "json_type": "oz_accept registry", "o1_source": "bench/o1/workflow.py", "o1_policy": "bench/o1/workflow.py",
             "o1_tier_a": "bench/o1/workflow.py"}


def line_of(path: str, needle: str):
    try:
        for i, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
            if needle in line:
                return i
    except OSError:
        pass
    return None


def host_scan(man) -> list[dict]:
    rows = []
    paths = {e["path"] for e in man["entries"]}
    for wf in ("bench/step4/inspection-handoff-20-v1", "bench/step4/inspection-handoff-20-v2",
               "bench/step4/inspection-handoff-20-v3", "bench/o1/repair-handoff-20-v1"):
        w = json.loads((ROOT / wf / "workflow.json").read_text(encoding="utf-8"))
        g = json.loads((ROOT / wf / "graph.json").read_text(encoding="utf-8"))
        n_nodes = defaultdict(int)
        for n in g["nodes"]:
            n_nodes[n["op"]] += 1
        for opname, spec in w["model_ops"].items():
            checks = [c["check"] for c in spec.get("checks", [])]
            hit = [c for c in checks if CHECK_CLASS.get(c, (False,))[0]]
            ln = line_of(CHECK_SRC.get(checks[0], "") if checks and CHECK_SRC.get(checks[0], "").endswith(".py") else "x", f"Check('{checks[0]}'") if checks else None
            loc = f"{CHECK_SRC.get(checks[0], '?')}:{ln}" if ln else (CHECK_SRC.get(checks[0], "?") if checks else "?")
            rows.append({"scope": wf.replace("bench/", ""), "op": f"{opname}@{spec.get('version')}", "nodes": n_nodes.get(opname, 0),
                         "checks": ", ".join(checks), "flag": bool(hit),
                         "why": "; ".join(f"{c}: {CHECK_CLASS[c][1]}" for c in hit) if hit else
                                "no check recomputes the answer: " + "; ".join(f"{c}: {CHECK_CLASS.get(c, (False, '?'))[1]}" for c in checks),
                         "locator": f"{wf}/workflow.json model_ops; check at {loc}"})
        for host_op in sorted(o for o in n_nodes if o.startswith("host.classify")):
            rows.append({"scope": wf.replace("bench/", ""), "op": host_op, "nodes": n_nodes[host_op], "checks": "(host op)",
                         "flag": False, "why": "already a host operation (v3): no model call", "locator": f"{wf}/graph.json"})
    ln = line_of("bench/live/live2.py", "MAT_D = {")
    for key, text in (("e", "extract six fields"), ("b", "interval bounds"), ("m", "missing field names"), ("v", "inside/outside/unknown")):
        rows.append({"scope": "pilot/1g materials jobs (pilot2, pilot2q, live22-29 H and 0.8-exec arms, pilot_k2 blocks A-C)",
                     "op": f"materials.{key} ({text})", "nodes": 0, "checks": "live6.check oracle (strict compare to expected)",
                     "flag": True, "why": "the oracle compares to the value the host derives from the ref text; the job is exactly computable",
                     "locator": f"bench/live/live2.py:{ln} (MAT_D), oracle bench/live/live6.py:{line_of('bench/live/live6.py', 'def check(job, value, native)')}"})
    rows.append({"scope": "live23-live29 heterogeneous 64-job packets", "op": "hetero1g families P1-P5", "nodes": 0,
                 "checks": "judge() against expected",
                 "flag": True, "why": "module docstring: each expected result follows from the op text and the refs alone, no judgment",
                 "locator": "bench/live/hetero1g.py:1-5"})
    ln = line_of("bench/probe/boundary.py", "classify")
    rows.append({"scope": "boundary-probe and adopt-qual (classification arms A, B, C, q4)", "op": "classify", "nodes": 0,
                 "checks": "mat_classify / member-wise compare", "flag": True,
                 "why": "classification of a Decimal interval against fixed limits", "locator": "bench/step4/workflow.py mat_classify; bench/probe/boundary.py"})
    return rows


# ----------------------------------------------------------------------------------------------------------------
# 6. Audit of the two prior claims
# ----------------------------------------------------------------------------------------------------------------

def audit(units, fits, man):
    res = {}
    o1 = [u for u in units if u["group"] == "o1-live1" and u["stratum"] == "main"]
    size4 = [u for u in o1 if u["size"] == 4 and u["think"] is not None]
    sz = [(u["think"], u["scenario"], u["arm"], u["src"], u["loc"], u["in_total"], u["out"]) for u in size4]
    res["o1_thinking_size4"] = sorted(sz)
    res["o1_thinking_all"] = sorted([(u["size"], u["think"], u["scenario"], u["arm"]) for u in o1 if u["think"] is not None])
    # claim 2: fixed per-call input
    claim2 = []
    for k, f in sorted(fits.items()):
        claim2.append((k, f))
    res["fits"] = claim2
    # prefix evidence: fixed bytes of H
    sysb = defaultdict(set)
    for u in units:
        if u["sys_bytes"]:
            sysb[(u["group"], u["sys_sha"])].add(u["sys_bytes"])
    res["system_bytes"] = {f"{k[0]}:{(k[1] or '')[:8]}": sorted(v) for k, v in sysb.items()}
    ledgers = [u for u in units if u["group"] in ("step4-live1", "step4-live2", "step4-live3", "o1-live1") and u["in_total"] is not None
               and u["inu"] is not None]
    res["cache_mix"] = {
        "calls": len(ledgers),
        "cr_values": sorted({u["cr"] for u in ledgers}),
        "cr603": sum(1 for u in ledgers if u["cr"] == 603),
        "sum_cw": sum(u["cw"] for u in ledgers), "sum_cr": sum(u["cr"] for u in ledgers),
    }
    return res


# ----------------------------------------------------------------------------------------------------------------
# 7. Completeness
# ----------------------------------------------------------------------------------------------------------------

def completeness(units):
    g = OrderedDict()
    for u in units:
        k = (u["group"], u["stratum"], u["kind"], u["ctr_source"].split(";")[0][:70])
        s = g.setdefault(k, {"n": 0, "inu": 0, "cw": 0, "cr": 0, "out": 0, "think": 0, "total": 0, "wall": 0, "api": 0,
                             "failed": 0, "nodenom": 0})
        s["n"] += 1
        for f in ("inu", "cw", "cr", "out", "think"):
            if u[f] is not None:
                s[f] += 1
        if u["in_total"] is not None:
            s["total"] += 1
        if u["wall_ms"] is not None or u["inflight_ms"] is not None:
            s["wall"] += 1
        if u["api_ms"] is not None:
            s["api"] += 1
        if u["failed"]:
            s["failed"] += 1
        if denom(u) is None:
            s["nodenom"] += 1
    return g


# ----------------------------------------------------------------------------------------------------------------
# 8. Cross-checks (dedup of aggregate and child usage)
# ----------------------------------------------------------------------------------------------------------------

def crosschecks(units, man):
    out = {}
    # pilot_k2.jsonl aggregate rows vs children (transcript + worker ledgers); aggregates are never added
    agg = {}
    for e in man["entries"]:
        if e["path"].endswith("pilot_k2.jsonl") or e["path"].endswith("pilot_k2_smoke.jsonl"):
            for ln, o in read_jsonl(ROOT / e["path"]):
                agg[o["tag"]] = (e["path"], ln, o)
    by_tag = defaultdict(list)
    for u in units:
        if u["group"] in ("pilot_k2-caller", "pilot_k2-worker"):
            by_tag[u["run_key"].split("/")[-1]].append(u)
    mism, ok, miss = [], 0, 0
    for tag, lst in by_tag.items():
        a = agg.get(tag)
        if not a:
            miss += 1
            continue
        o = a[2]
        cal = [u for u in lst if u["kind"] == "caller"]
        wk = [u for u in lst if u["kind"] == "worker"]
        c_in = sum(u["in_total"] or 0 for u in cal)
        c_out = sum(u["out"] or 0 for u in cal)
        w_in = sum(u["in_total"] or 0 for u in wk)
        w_out = sum(u["out"] or 0 for u in wk)
        if (c_in, c_out, w_in, w_out) == (o.get("caller_in"), o.get("caller_out"), o.get("worker_in"), o.get("worker_out")):
            ok += 1
        else:
            mism.append((tag, (c_in, c_out, w_in, w_out), (o.get("caller_in"), o.get("caller_out"), o.get("worker_in"), o.get("worker_out"))))
    out["k2_aggregate_vs_children"] = {"runs": len(by_tag), "match": ok, "mismatch": mism, "no_aggregate": miss}
    # duplicate call ids across ledger files
    seen = defaultdict(list)
    for u in units:
        if u["group"] in ("step4-live1", "step4-live2", "step4-live3", "o1-live1"):
            seen[u["uid"]].append(u["src"])
    out["duplicate_uids"] = [k for k, v in seen.items() if len(v) > 1]
    # report totals vs ledger sums
    rep = {}
    for e in man["entries"]:
        if e["kind"] == "report" and Path(e["path"]).name.startswith("report-live-"):
            r = json.loads((ROOT / e["path"]).read_text(encoding="utf-8"))
            tot = (r.get("totals") or {}).get("tokens_known")
            lbl = e["group"]
            s = sum((u["in_total"] or 0) + (u["out"] or 0) for u in units if u["group"] == lbl and u["in_total"] is not None
                    and u["out"] is not None)
            rep[lbl] = (tot, s)
    out["report_totals_vs_ledgers"] = rep
    # waiting evidence
    q = [u for u in units if u["queued"]]
    out["queued_turns_nonzero"] = len(q)
    statuses = defaultdict(int)
    for e in man["entries"]:
        if e["kind"] == "caller-transcript":
            for _, o in read_jsonl(ROOT / e["path"]):
                if o.get("type") == "rate_limit_event":
                    statuses[(o.get("rate_limit_info") or {}).get("status")] += 1
    out["rate_limit_events"] = dict(statuses)
    return out


# ----------------------------------------------------------------------------------------------------------------
# 9. Build everything
# ----------------------------------------------------------------------------------------------------------------

def build():
    man = load_manifest()
    bad = verify_manifest(man)
    if bad:
        raise SystemExit("manifest verification failed:\n" + "\n".join(bad[:20]))
    by_path = {e["path"] for e in man["entries"]}
    units = []
    for e in man["entries"]:
        if e["kind"] == "run-jsonl" and e["role"] == "observation":
            if e["path"].endswith("pilot_k2.jsonl") or e["path"].endswith("pilot_k2_smoke.jsonl"):
                continue          # aggregates of the transcripts and ledgers: cross-check only, never added
            units.extend(parse_flat(e, by_path))
    units.extend(parse_k2(man))
    units.extend(parse_ledgers(man))
    units.extend(parse_envelopes(man))
    # model-needed classification of the flat and k2 workloads: host-computable by the scan
    for u in units:
        if u["group"] in ("pilot2", "pilot2q", "pilot_k", "pilot_k2-caller", "pilot_k2-worker") or u["group"].startswith("live2"):
            u["model_needed"] = False
            u["mn_reason"] = "materials / heterogeneous jobs: the oracle recomputes the full answer (host-computable)"
    fits = fit_groups(units)
    cells = aggregate_cell(units, fits)
    runs = run_groups(units)
    return man, units, fits, cells, runs


def qualify(cells):
    """Apply the actionable rule to every (cell, category). Returns the table rows."""
    rows = []
    for c in cells:
        stratum = c["cell"][5]
        names = list(TOKEN_CATS) + ["failed_resent", "check_driven", "caller_overhead"]
        for name in names:
            sh, status = share(c, name)
            if sh is None:
                continue
            meets = sh >= THRESHOLD
            var = VARIABLE.get(name)
            reasons = []
            if not meets:
                continue
            if stratum != "main":
                reasons.append(f"stratum {stratum}: descriptive/control only")
            if not c["model_needed"]:
                reasons.append("not a model-needed job (host-computable)")
            if status != "known":
                reasons.append(f"attribution {status}")
            if name in CAT_STATUS and CAT_STATUS[name].startswith(("unattributed", "estimate")):
                reasons.append(CAT_STATUS[name])
            if var is None:
                reasons.append("no single named variable moves it (deliverable or payload or inseparable residual)")
            rows.append({"cell": c["cell"], "category": name, "share": sh, "status": status, "qualifies": not reasons,
                         "variable": var, "reasons": reasons})
    return rows


# ----------------------------------------------------------------------------------------------------------------
# 10. Output
# ----------------------------------------------------------------------------------------------------------------

def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def headline(units, cells, man):
    main = [u for u in units if u["stratum"] == "main"]
    d = lambda lst: sum(denom(u) for u in lst if denom(u) is not None)
    return {
        "manifest_digest": man["digest"], "manifest_files": man["count"],
        "observation_files": sum(1 for e in man["entries"] if e["role"] == "observation"),
        "units": len(units), "units_main": len(main),
        "denominator_main": d(main), "denominator_smoke": d([u for u in units if u["stratum"] == "smoke"]),
        "denominator_control": d([u for u in units if u["stratum"] == "control"]),
        "cells": len(cells),
        "o1_calls": sum(1 for u in units if u["group"] == "o1-live1"),
        "o1_denominator": d([u for u in units if u["group"] == "o1-live1"]),
    }


def cmd_csv(outdir: Path, units, cells, runs, fits):
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "per_call.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["uid", "source", "locator", "stratum", "group", "kind", "run", "workload", "model", "size", "arm",
                    "scenario", "model_needed", "counter_source", "input_uncached", "cache_write", "cache_read",
                    "input_total", "output", "thinking", "denominator", "visible_out", "packet_in_est", "fixed_in",
                    "input_unsplit", "wall_ms", "api_ms", "inflight_ms", "failed", "resent", "check_driven", "outcome", "note"])
        for u in units:
            sp = split_tokens(u, fits)
            w.writerow([u["uid"], u["src"], u["loc"], u["stratum"], u["group"], u["kind"], u["run_key"], u["workload"],
                        u["model"], u["size"], u["arm"], u["scenario"], u["model_needed"], u["ctr_source"], u["inu"],
                        u["cw"], u["cr"], u["in_total"], u["out"], u["think"], denom(u), sp["visible_out"],
                        None if sp["packet_in"] is None else round(sp["packet_in"], 1),
                        None if sp["fixed_in"] is None else round(sp["fixed_in"], 1), sp["input_unsplit"], u["wall_ms"],
                        u["api_ms"], u["inflight_ms"], u["failed"], u["resent"], u["check_driven"], u["outcome"], u["note"]])
    with open(outdir / "per_run.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "stratum", "calls", "denominator", "failed_resent_tokens", "check_driven_tokens",
                    "caller_overhead_tokens", "wall_ms", "active_ms", "avoidable_ms", "unresolved_ms", "partition_note"])
        for (rk, st), lst in runs.items():
            p = partition_run(lst)
            dn = [denom(u) for u in lst]
            f_ = sum(denom(u) for u in lst if tag_failed_resent(u) and denom(u) is not None)
            c_ = sum(denom(u) for u in lst if u["check_driven"] and denom(u) is not None)
            o_ = sum(denom(u) for u in lst if u["caller_overhead"] and u["kind"] == "caller" and denom(u) is not None)
            w.writerow([rk, st, len(lst), sum(x for x in dn if x is not None) if any(x is not None for x in dn) else None,
                        f_, c_, o_, p["wall_ms"], p["active_ms"], p["avoidable_ms"], p["unresolved_ms"], p["note"]])
    with open(outdir / "per_cell.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["workload", "model", "size", "arm", "scenario", "stratum", "model_needed", "calls", "denominator"] +
                   [f"{c}_share" for c in TOKEN_CATS] + ["failed_resent_share", "check_driven_share", "caller_overhead_share"])
        for c in cells:
            w.writerow(list(c["cell"]) [:5] + [c["cell"][5], c["model_needed"], c["calls"], c["denominator"]] +
                       [("" if share(c, n)[0] is None else round(share(c, n)[0], 4)) for n in list(TOKEN_CATS) +
                        ["failed_resent", "check_driven", "caller_overhead"]])


def short_cell(k):
    return f"{k[0]}; {k[1].replace('claude-', '')}; n={k[2]}; {k[3]}; {k[4]}"


def fnum(x, nd=0):
    if x is None:
        return "unknown"
    return f"{x:,.{nd}f}"


def time_cells(units, runs):
    """Aggregate run partitions into time cells (flat/envelope/k2 runs share their units' cell; a ledger run is its own cell)."""
    out = OrderedDict()
    for (rk, st), lst in runs.items():
        p = partition_run(lst)
        u = lst[0]
        if u["kind"] == "call":
            key = (u["workload"], u["model"], "run", "all stages", u["scenario"], st)
        else:
            key = cell_key(u)
        c = out.setdefault(key, {"runs": 0, "wall": 0.0, "active": 0.0, "unresolved": 0.0, "unknown": 0})
        c["runs"] += 1
        if p["wall_ms"] is None or p["active_ms"] is None:
            c["unknown"] += 1
        else:
            c["wall"] += p["wall_ms"]
            c["active"] += p["active_ms"]
            c["unresolved"] += p["unresolved_ms"]
    return out


def render(man, units, fits, cells, runs) -> str:
    L = []
    w = L.append
    h = headline(units, cells, man)
    q = qualify(cells)
    cc = crosschecks(units, man)
    au = audit(units, fits, man)
    scan = host_scan(man)
    tcells = time_cells(units, runs)

    w("# Step 1 results: zero-call trace analysis (2026-10-23)")
    w("")
    w(f"Preregistration: [03-astra-accept-and-step1-prereg.md](03-astra-accept-and-step1-prereg.md). No model call was made and nothing was "
      f"committed. This file is generated: `python bench/analysis/step1_traces.py --md docs/design/next-2026-10-23/step1-results.md` "
      f"regenerates every number below from the frozen manifest, and `--csv bench/analysis/step1_out` writes the full per-call, per-run and per-cell tables (`per_call.csv` has one row per record with its source locator).")
    w("")

    # ---------------- conclusion first
    qualifying = [r for r in q if r["qualifies"]]
    w("## 1. Conclusion")
    w("")
    if not qualifying:
        w("**No demonstrated actionable bottleneck.**")
    else:
        w("**Qualifying categories exist; see section 9.**")
    w("")
    o1c = [c for c in cells if c["cell"][0].startswith("o1") and c["cell"][5] == "main"]
    mx_think = max((share(c, "thinking")[0] or 0, c) for c in o1c)
    w(f"The rule (prereg item 3) needs a category of at least 25% of billed tokens or elapsed time, inside one workload/model/size/arm/scenario "
      f"cell, on a model-needed job, movable by one named variable, with known attribution. Of {len(cells)} cells, "
      f"{sum(1 for c in cells if c['model_needed'])} are model-needed (per-stage cells plus the all-stages cells), and all of them are O1 repair cells "
      f"(`o1-repair-handoff-20/live1`). Every other cell is a materials or heterogeneous-packet job whose check recomputes the full answer, so it is host-computable "
      f"(section 8) and cannot qualify.")
    w("")
    w("In the O1 cells:")
    w("")
    w(f"1. Thinking is at most {pct(mx_think[0])} of billed tokens in any one cell, below 25%. Effort does not qualify (it qualifies only through thinking).")
    w("2. Avoidable waiting is 0 ms demonstrated. No source records a queue or rate-limit wait (section 7), and the dependency order core, adapter is a DAG edge, not waiting. Scheduling does not qualify.")
    fr = sum(c["tags"]["failed_resent"][0] + c["tags"]["check_driven"][0] for c in o1c if c["cell"][3] != "* (all stages)")
    w(f"3. Failed, resent or check-driven calls are {fr:,} tokens in O1 (the interrupted call was recovered from its capture and its result was used, so it is not wasted work).")
    o1fix = sorted(share(c, "fixed_in")[0] for c in o1c if share(c, "fixed_in")[0] is not None)
    o1pk = sorted(share(c, "packet_in")[0] for c in o1c if share(c, "packet_in")[0] is not None)
    w(f"4. Two categories are at or above 25% but cannot qualify. Packet input ({pct(o1pk[0])} to {pct(o1pk[-1])}, an estimate) is the job payload itself, "
      f"with no variable that moves it without changing the job. Fixed per-call input ({pct(o1fix[0])} to {pct(o1fix[-1])}) is H plus the CLI's own framing and the corpus cannot separate "
      f"them, so it is an unattributed residual, which the rule says cannot establish qualification (sections 5.2 and 9).")
    w("")
    w("What the traces do show, outside the rule's reach:")
    w("")
    hk = [c for c in cells if share(c, "thinking")[0] is not None and share(c, "thinking")[0] >= THRESHOLD and c["cell"][5] == "main"
          and not c["model_needed"]]
    hv = sorted(share(c, "thinking")[0] for c in hk)
    by_model = defaultdict(int)
    for c in hk:
        by_model[c["cell"][1].replace("claude-", "")] += 1
    w(f"1. Thinking is {pct(hv[0])} to {pct(hv[-1])} of billed tokens in {len(hk)} cells ({', '.join(f'{v} {k}' for k, v in sorted(by_model.items()))}), "
      f"but only on host-computable jobs. The movable variable there is not effort, it is moving the job to the host (the authoring rule). They fail the rule only because the job is not model-needed. "
      f"Workloads: {', '.join(sorted({c['cell'][0] for c in hk}))}.")
    cd_cells = [c for c in cells if c["cell"][5] == "main" and not c["model_needed"] and share(c, "check_driven")[0] is not None
                and share(c, "check_driven")[0] >= THRESHOLD and c["cell"][3] == "* (all stages)"]
    if cd_cells:
        cv = sorted(share(c, "check_driven")[0] for c in cd_cells)
        w(f"2. Check-driven rework (resent calls plus the call each resend names) is {pct(cv[0])} to {pct(cv[-1])} of billed tokens in {len(cd_cells)} step4 all-stages cells "
          f"({', '.join(sorted({c['cell'][0] for c in cd_cells}))}), again on host-computable jobs.")
    co_cells = [c for c in cells if c["cell"][5] == "main" and share(c, "caller_overhead")[0] is not None and share(c, "caller_overhead")[0] >= THRESHOLD]
    if co_cells:
        ov = sorted(share(c, "caller_overhead")[0] for c in co_cells)
        w(f"3. Measured caller overhead is {pct(ov[0])} to {pct(ov[-1])} of run tokens in the {len(co_cells)} delegating cells of pilot_k2, on materials jobs. This describes the stored runs; the settled same-model comparison is not reopened.")
    w("4. The one measurement that would decide the O1 fixed-input question is a split of H from the CLI framing. No call in the corpus varies H alone, so it cannot be made from these traces. It would cost a handful of calls with a cut-down H, which this step may not make.")
    w("5. If the fixed per-call input is read as H by definition, then in every O1 cell it is 25.7% to 56.2% and the single variable is H length. Section 9 lists those cells so the decision does not depend on how this report words it.")
    w("")

    # ---------------- manifest
    w("## 2. Frozen manifest")
    w("")
    w(f"Digest `{man['digest']}` (SHA-256 over the lines `<file sha256>  <path>` sorted by path, all {man['count']} entries, raw file bytes). "
      f"Full list with per-file SHA-256: `bench/analysis/step1_manifest.json`. It was built by `--freeze` from the selectors in the preregistration before any usage value was parsed. "
      f"Every analysis run re-hashes every file and refuses to continue on a mismatch.")
    w("")
    gtab = OrderedDict()
    for e in man["entries"]:
        g = gtab.setdefault((e["group"], e["stratum"]), {"obs": 0, "prov": 0, "bytes": 0})
        g["obs" if e["role"] == "observation" else "prov"] += 1
        g["bytes"] += e["bytes"]
    w(md_table(["group", "stratum", "observation files", "provenance files", "bytes"],
               [[k[0], k[1], v["obs"], v["prov"], f"{v['bytes']:,}"] for k, v in gtab.items()]))
    w("")
    w("Observation files supply usage. Provenance files (run manifests, reports, candidates, ledgers, request and metadata files, baseline captures) supply timing, model identity and recovered usage, never a second observation. "
      "Smoke runs (`*smoke*`, `pilot_k2_smoke/`) are a separate descriptive stratum and never qualify a bottleneck. The boundary-probe and adopt-qual envelopes are the `control` stratum. "
      "`pilot_k2.jsonl` and `pilot_k2_smoke.jsonl` are aggregates of the transcripts and worker ledgers in the directories next to them; they are cross-checked and never added (section 3). "
      "Excluded by selector: `deliveries/` under O1 (published artifacts), fixtures, and live2 to live21 plus the gate and effort files. "
      "`step4/live1/baseline/captures` are hashed as provenance but not parsed: they are not a selector observation file.")
    w("")

    # ---------------- completeness
    w("## 3. Accounting completeness")
    w("")
    comp = completeness(units)
    w(md_table(["group", "stratum", "kind", "counter source (first clause)", "records", "uncached in", "cache write", "cache read", "total in",
                "output", "thinking", "wall or in-flight", "api ms", "no denominator", "failed"],
               [[k[0], k[1], k[2], k[3], v["n"], v["inu"], v["cw"], v["cr"], v["total"], v["out"], v["think"], v["wall"], v["api"], v["nodenom"], v["failed"]]
                for k, v in comp.items()]))
    w("")
    w("Counts are records with the counter known. A record with no denominator has no known total input or output. The sources differ in what they retained:")
    w("")
    w("1. Raw `modelUsage` retained and summed over every reported model here: caller transcripts (`result.modelUsage`) and control envelopes. Thinking is `modelUsage.thinkingTokens`.")
    w("2. Runner-summed `modelUsage` (`pilot2.py:66-71`), stored as flat fields: pilot2 and pilot2q. `modelUsage` itself was not kept, so it cannot be re-derived here.")
    w("3. CLI `result.usage` through `run_live.call` (`run_live.py:119-127`): live22 to live29. This is not `modelUsage`. It equals it for a single tool-less turn, but the turn count was not stored, so that equality is assumed, not shown. Counters are used as stored and the source is named in every row.")
    w("4. Adapter call ledgers (step4, O1, worker ledgers), which derive usage from the envelope's `modelUsage` (`examples/claude_cli_adapter.py:16-30`) but do not record thinking. Thinking for step4 live2 and live3 and for O1 comes from `thinking_tokens_per_call` in the run report (`bench/step4/step4.py:416-438`, `bench/o1/o1.py:363-397`), which read the retained CLI envelope; the envelopes are not in the corpus. step4 live1 has no thinking at all.")
    w("5. Old `pilot_k_*.jsonl` rows hold only total input and output (caller plus worker). Cache write, cache read and thinking are unknown.")
    w("")
    w("Missing-accounting records, retained as such:")
    w("")
    miss = [u for u in units if u["kind"] in ("call", "worker") and u["outcome"].startswith("no call_end")]
    w(md_table(["locator", "run", "stage", "size", "what is known"],
               [[f"{u['src']} ({u['loc']})", u["run_key"], u["arm"], u["size"],
                 (f"total in {u['in_total']}, out {u['out']} recovered from the run report; cache split and wall unknown" if u["in_total"] is not None else "nothing (no call_end, no report row): excluded from every denominator")]
                for u in miss]))
    w("")
    w("Deduplication checks (aggregate versus child usage):")
    w("")
    k2 = cc["k2_aggregate_vs_children"]
    w(f"1. `pilot_k2.jsonl` aggregates against transcripts plus worker ledgers: {k2['match']} of {k2['match'] + len(k2['mismatch'])} runs match exactly on caller and worker input and output "
      f"({k2['no_aggregate']} smoke runs have no aggregate row). The aggregate rows are not added; only the children are.")
    w("2. The caller transcript's per-message usage is a child of its `result.modelUsage` aggregate; only `modelUsage` is used. Worker calls run in separate processes, so caller `modelUsage` and worker ledger usage do not overlap and are added.")
    w(f"3. Duplicate call identities across ledger files: {len(cc['duplicate_uids'])}.")
    rows = []
    for lbl, (rep, led) in cc["report_totals_vs_ledgers"].items():
        rows.append([lbl, f"{rep:,}" if rep is not None else "n/a", f"{led:,}", "match" if rep == led else f"ledger lacks {rep - led:,}"])
    w("4. Run report `totals.tokens_known` against the sum of ledger calls (plus recovered usage):")
    w("")
    w(md_table(["run", "report tokens_known", "ledger sum", "result"], rows))
    w("")
    w("   The step4 live1 difference is the killed interrupt-extract call, which has no recovery row in that report.")
    w("")

    # ---------------- corpus totals
    w("## 4. Corpus totals and denominators")
    w("")
    tot = OrderedDict()
    for u in units:
        k = (u["group"], u["stratum"])
        t = tot.setdefault(k, {"n": 0, "D": 0, "known": 0, "in": 0, "out": 0, "think": 0, "thinkn": 0})
        t["n"] += 1
        d = denom(u)
        if d is not None:
            t["D"] += d
            t["known"] += 1
            t["in"] += u["in_total"]
            t["out"] += u["out"]
        if u["think"] is not None and d is not None:
            t["think"] += u["think"]
            t["thinkn"] += 1
    w(md_table(["group", "stratum", "records", "with denominator", "denominator (in+out)", "input", "output", "thinking (where known)", "records with thinking"],
               [[k[0], k[1], v["n"], v["known"], f"{v['D']:,}", f"{v['in']:,}", f"{v['out']:,}", f"{v['think']:,}", v["thinkn"]] for k, v in tot.items()]))
    w("")
    w(f"Total denominator: main {h['denominator_main']:,}, smoke {h['denominator_smoke']:,}, control {h['denominator_control']:,} tokens, {h['units']} records, {h['cells']} cells.")
    w("")

    # ---------------- audit
    w("## 5. Audit of the two prior claims")
    w("")
    w("### 5.1 O1 thinking, 584 to 1,186 tokens per size-4 call")
    w("")
    s4 = [u for u in units if u["group"] == "o1-live1" and u["size"] == 4]
    w(md_table(["scenario", "op", "locator (ledger)", "thinking", "output", "billed in+out", "thinking / output", "thinking / billed", "thinking source"],
               [[u["scenario"], u["arm"], f"{u['src']} ({u['loc']})", u["think"], u["out"], denom(u),
                 pct(u["think"] / u["out"]) if u["think"] is not None else "n/a", pct(u["think"] / denom(u)) if u["think"] is not None else "n/a", u["thinking_source"][:60]] for u in s4]))
    w("")
    ths = [u["think"] for u in s4 if u["think"] is not None]
    verdict1 = "CONFIRMED" if (ths and min(ths) == 584 and max(ths) == 1186 and len(ths) == len(s4)) else "NOT REPRODUCED"
    w(f"Verdict: **{verdict1}**. All {len(s4)} size-4 O1 calls carry a thinking value, minimum {min(ths):,}, maximum {max(ths):,}. "
      f"The values come from the O1 run report (`bench/o1/live1/report-live-live1.json`, `thinking_tokens_per_call`), not from the call ledgers, which do not record thinking; "
      f"the report read the retained envelope, which is outside the corpus. Report input and output tokens equal the ledger's for every joined call. "
      f"Size-1 O1 calls: {', '.join(str(u['think']) if u['think'] is not None else 'unknown' for u in units if u['group'] == 'o1-live1' and u['size'] == 1)}.")
    w("")
    w("### 5.2 About 2,000 H tokens per call as cache write or cache read")
    w("")
    led = [u for u in units if u["group"] in ("step4-live1", "step4-live2", "step4-live3", "o1-live1") and u["inu"] is not None]
    fx = []
    for u in led:
        sp = split_tokens(u, fits)
        if sp["fixed_in"] is not None:
            fx.append((sp["fixed_in"], u))
    fvals = [a for a, _ in fx]
    fread = sum(min(u["cr"], a) for a, u in fx)
    ftot = sum(fvals)
    pq = [u for u in units if u["group"] == "pilot2q"]
    pq603, pqn = sum(1 for u in pq if u["cr"] == 603), len(pq)
    w("Measured: per-call input that does not scale with the prompt. For each ledger group the billed input total is regressed on the call's own prompt-size estimate (o200k tokens, from the ledger); "
      "the intercept is the per-call input paid whatever the packet.")
    w("")
    w(md_table(["fit group", "model", "calls", "intercept (tokens per call)", "slope (billed per estimated token)", "R squared"],
               [[k[0], k[1].replace("claude-", ""), f["n"], f"{f['a']:,.0f}", f"{f['b']:.3f}", f"{f['r2']:.4f}"] for k, f in au["fits"]]))
    w("")
    sysb = au["system_bytes"]
    ests = sorted({u["sys_est"] for u in led if u["sys_est"]})
    byts = sorted({u["sys_bytes"] for u in led if u["sys_bytes"]})
    shas = sorted({(u["sys_sha"] or "")[:8] for u in led})
    w(f"Per-call fixed input in the {len(fx)} step4 and O1 ledger calls with a regression: minimum {min(fvals):,.0f}, maximum {max(fvals):,.0f}, mean {ftot / len(fvals):,.0f}. "
      f"Of it, {pct(fread / ftot)} was paid as cache read and {pct(1 - fread / ftot)} as cache write over those calls (assuming the fixed input is the cached prefix, which the counters cannot confirm). The H text itself is {', '.join(map(str, byts))} bytes "
      f"(system sha `{', '.join(shas)}`; o200k estimate {', '.join(map(str, ests))} tokens, an estimate not a billed count).")
    w("")
    w(f"Verdict: **PARTLY SUPPORTED, NOT AS H.** About 2,000 tokens of fixed input per call is real and stable ({min(fvals):,.0f} to {max(fvals):,.0f}). It is not H. "
      f"A token covers at least one byte, so H cannot exceed {max(byts):,} billed tokens, and its o200k estimate is {max(ests)}. The rest of the fixed input, at least {min(fvals) - max(byts):,.0f} tokens, "
      f"is the CLI's own request framing, which the same calls pay with `--tools ''`, an empty settings source and a custom `--system-prompt`. "
      f"A 603-token block is the smallest cache read in the corpus (`cr = 603` in {au['cache_mix']['cr603']} of {au['cache_mix']['calls']} ledger calls, and in {pq603} of {pqn} pilot2q calls whose system text was cut down per call), "
      f"so it is read whatever H says and is CLI framing, not H. The corpus has no call that varies H alone, so the H share of the fixed input is bounded (0 to {max(byts):,} tokens) but not measured.")
    w("")
    w("Other fixed intercepts for context (different system prompts, so not comparable): " + "; ".join(
        f"{k[0]} {k[1].replace('claude-', '')} {f['a']:,.0f}" for k, f in au["fits"] if not k[0].startswith(("o1", "step4"))) + ".")
    w("")

    # ---------------- per-call tables
    w("## 6. Per-call breakdowns")
    w("")
    w("Denominator per call = uncached input + cache write + cache read + output, each once. Thinking is a subset of output. Visible output = output minus thinking. "
      "Packet input is the regression estimate described in 5.2 (slope times the call's own estimate). Fixed input is the remainder of the billed input: H plus CLI framing, inseparable. "
      "`unknown` means the corpus does not have the counter. Flat per-run families (pilot2, pilot2q, live22 to live29, old pilot_k) have one record per process and "
      "are in `per_call.csv` with their line locators; the cell tables in section 7 aggregate them.")
    w("")

    def call_table(sel):
        rows = []
        for u in sel:
            sp = split_tokens(u, fits)
            rows.append([f"{u['src']} ({u['loc']})", u["scenario"], u["arm"], u["size"], fnum(u["in_total"]), fnum(u["cw"]), fnum(u["cr"]),
                         fnum(u["out"]), fnum(u["think"]), fnum(denom(u)), fnum(sp["visible_out"]), fnum(sp["packet_in"]), fnum(sp["fixed_in"]),
                         fnum(u["inflight_ms"]), ("resent " if u["resent"] else "") + ("rejected-in-part " if u["resent_origin"] else "") + ("check-driven " if u["check_driven"] else "") + ("failed " if u["failed"] else "") + u["outcome"][:34]])
        return md_table(["locator", "scenario", "stage", "members", "input", "cache write", "cache read", "output", "thinking", "denominator", "visible out",
                         "packet in (est)", "fixed in", "in-flight ms", "tags and outcome"], rows)

    w("### 6.1 O1 repair (the only model-needed workload)")
    w("")
    w(call_table([u for u in units if u["group"] == "o1-live1"]))
    w("")
    for lbl in ("step4-live1", "step4-live2", "step4-live3"):
        w(f"### 6.{ {'step4-live1': 2, 'step4-live2': 3, 'step4-live3': 4}[lbl] } {lbl} (host-computable, not model-needed)")
        w("")
        w(call_table([u for u in units if u["group"] == lbl]))
        w("")
    w("### 6.5 Control envelopes (boundary probe and adopt-qual, control stratum)")
    w("")
    rows = []
    for u in units:
        if u["kind"] != "envelope":
            continue
        rows.append([u["src"], u["workload"], u["arm"], u["scenario"], fnum(u["cw"]), fnum(u["cr"]), fnum(u["out"]), fnum(u["think"]), fnum(denom(u)),
                     fnum(u["wall_ms"]), fnum(u["api_ms"]), "failed" if u["failed"] else "ok"])
    w(md_table(["locator", "workload", "arm", "cell", "cache write", "cache read", "output", "thinking", "denominator", "wall ms", "api ms", "outcome"], rows))
    w("")
    w("### 6.6 Caller-cost runs (pilot_k2): per-run breakdown")
    w("")
    w("One row per run (caller transcript plus its worker ledger calls). Caller overhead is tagged only on delegating arms (K0, K1f, K1r); in arm J the caller does the work itself. "
      "This is a description of the stored runs, not a re-test of the settled same-model comparison.")
    w("")
    rows = []
    for (rk, st), lst in runs.items():
        if lst[0]["group"] not in ("pilot_k2-caller", "pilot_k2-worker"):
            continue
        cal = [u for u in lst if u["kind"] == "caller"]
        wk = [u for u in lst if u["kind"] == "worker"]
        cd = sum(denom(u) or 0 for u in cal)
        wd = sum(denom(u) or 0 for u in wk)
        p = partition_run(lst)
        rows.append([rk.replace("bench/live/data/", ""), st, lst[0]["arm"], lst[0]["size"], len(wk), fnum(cd), fnum(wd), fnum(cd + wd),
                     pct(cd / (cd + wd)) if (cd + wd) and wk else "n/a (no delegation)", fnum(sum(u["think"] or 0 for u in cal)), fnum(p["wall_ms"]), fnum(p["active_ms"]), fnum(p["unresolved_ms"])])
    w(md_table(["run", "stratum", "arm", "jobs", "worker calls", "caller tokens", "worker tokens", "run denominator", "caller share", "caller thinking", "wall ms", "active ms", "unresolved ms"], rows))
    w("")

    w("### 6.7 Ledger runs (step4 and O1): per-run breakdown")
    w("")
    w("Failed or resent, check-driven and caller-overhead tokens are overlapping tags, never added to each other or to the categories. No ledger run has a caller.")
    w("")
    rows = []
    for (rk, st), lst in runs.items():
        if lst[0]["kind"] != "call":
            continue
        p = partition_run(lst)
        dn = sum(denom(u) or 0 for u in lst)
        rows.append([rk, len(lst), sum(1 for u in lst if denom(u) is None), fnum(dn),
                     fnum(sum(denom(u) or 0 for u in lst if tag_failed_resent(u))),
                     fnum(sum(denom(u) or 0 for u in lst if u["check_driven"])),
                     fnum(p["wall_ms"]), fnum(p["active_ms"]), fnum(p["unresolved_ms"]), p["note"][:60]])
    w(md_table(["run", "calls", "calls without denominator", "denominator", "failed or resent tokens", "check-driven tokens", "span ms", "active ms", "unresolved ms", "note"], rows))
    w("")

    # ---------------- per-cell
    w("## 7. Per-cell token and time breakdowns")
    w("")
    w("A cell is workload, model, size (jobs per call), arm, scenario, stratum. Every cell is listed. Shares are of the cell's billed tokens; a value followed by `*` is partial "
      "(some call in the cell lacks the counter). `unknown` means no call has it. `fixed` and `packet` need a prompt-size estimate and a regression with R squared of at least 0.99 and at least 5 calls; otherwise the whole input is `unsplit`. "
      "Tags (failed or resent, check-driven, caller overhead) overlap the categories and each other and are never added.")
    w("")
    rows = []
    for c in cells:
        k = c["cell"]
        def sh(name):
            v, st = share(c, name)
            return "unknown" if v is None else pct(v) + ("*" if st == "partial" else "")
        rows.append([k[0], k[1].replace("claude-", ""), k[2], k[3], k[4], k[5], "yes" if c["model_needed"] else "no", c["calls"], f"{c['denominator']:,}",
                     sh("thinking"), sh("visible_out"), sh("packet_in"), sh("fixed_in"), sh("input_unsplit"), sh("failed_resent"), sh("check_driven"), sh("caller_overhead")])
    w(md_table(["workload", "model", "jobs/call", "arm", "scenario", "stratum", "model-needed", "calls", "denominator", "thinking", "visible out", "packet (est)",
                "fixed (H+CLI)", "input unsplit", "failed or resent", "check-driven", "caller overhead"], rows))
    w("")
    w("### 7.1 Time partition")
    w("")
    w("End-to-end wall is partitioned into active critical-path work, avoidable waiting and unresolved time, per run, then summed per cell without summing overlapping calls. "
      "Active = model API time plus measured pre-request harness time for single-process runs; for ledger runs the union of call in-flight intervals; for caller runs the caller's API and pre-request time plus the union of its nested worker calls. "
      f"Avoidable waiting = measured queue or proven avoidable idle time. No source records one: queued turns nonzero in {cc['queued_turns_nonzero']} records, rate-limit events by status {cc['rate_limit_events']}, so it is 0 ms demonstrated everywhere. "
      "Unresolved = wall minus active: process start and exit, CLI internals, host work and gaps between calls, none of which any source attributes. Ledger runs have no end-to-end wall in the corpus (the run report holds only the whole live run), "
      "so their wall is the span from the first call start to the last call end and host work outside that span is not in it. Runs missing a timestamp or API split are counted in `runs unknown` and excluded from the sums.")
    w("")
    rows = []
    for k, c in tcells.items():
        rows.append([k[0], k[1].replace("claude-", ""), k[2], k[3], k[4], k[5], c["runs"], c["unknown"], fnum(c["wall"] / 1000, 1) if c["wall"] else "unknown",
                     pct(c["active"] / c["wall"]) if c["wall"] else "unknown", "0.0%" if c["wall"] else "unknown", pct(c["unresolved"] / c["wall"]) if c["wall"] else "unknown"])
    w(md_table(["workload", "model", "jobs/call", "arm", "scenario", "stratum", "runs", "runs unknown", "wall s (known runs)", "active", "avoidable waiting", "unresolved"], rows))
    w("")
    unres = [(k, c) for k, c in tcells.items() if c["wall"] and c["unresolved"] / c["wall"] >= THRESHOLD]
    mn_t = [k for k, c in unres if any(cc_["model_needed"] and cc_["cell"][:5] == k[:5] for cc_ in cells)]
    w(f"{len(unres)} of {len(tcells)} time cells have unresolved time at or above 25% of wall. It is unattributed by construction, so it cannot qualify. "
      f"None of the O1 time cells reach it ({', '.join(pct(c['unresolved'] / c['wall']) for k, c in tcells.items() if k[0].startswith('o1') and c['wall'])} unresolved; the interrupt run has no end timestamp for its killed call).")
    odd = [u for u in units if u["kind"] == "caller" and "largest gap" in u["note"]]
    for u in odd:
        w("")
        w(f"Outlier kept in the sums: `{u['src']}` ({u['loc']}), wall {fnum(u['wall_ms'] / 1000, 1)} s against {fnum(u['api_ms'] / 1000, 1)} s of API time; {u['note'].strip('; ')}. "
          f"It is unresolved time with no recorded cause and it alone takes its cell's unresolved share to {pct(1 - (tcells[cell_key(u)]['active'] / tcells[cell_key(u)]['wall']))}.")
    w("")

    # ---------------- host scan
    w("## 8. Host-computable scan")
    w("")
    w("Every model operation in the corpus workloads, with its checks. A flag means a check recomputes the operation's full answer from the same input, so the host can produce the answer without a model call and the model call only costs tokens.")
    w("")
    w(md_table(["scope", "model op", "model nodes in graph", "checks", "flag: check recomputes the full answer", "why", "locator"],
               [[r["scope"], r["op"], r["nodes"] if r["nodes"] else "n/a", r["checks"], "FLAGGED" if r["flag"] else "no", r["why"], r["locator"]] for r in scan]))
    w("")
    fl = [r for r in scan if r["flag"]]
    w(f"{len(fl)} of {len(scan)} rows are flagged. The only unflagged model operations are the two O1 repair ops, whose checks run the candidate code against executable expected rows; "
      "the host can judge code but not write it. The step4 v3 pack already moved classification to the host (`host.classify@1`); extract and bounds are still model operations in v3 and are flagged here. "
      "Code-domain pilot jobs (`pefv`) are not in this corpus.")
    w("")

    # ---------------- qualification
    w("## 9. Actionable rule applied to every cell")
    w("")
    n_meet = len(q)
    reason_count = defaultdict(int)
    for r in q:
        for x in r["reasons"]:
            reason_count[x] += 1
    w(f"{n_meet} (cell, category) pairs have a share of at least 25%. Disposition by reason (a pair can have several):")
    w("")
    w(md_table(["reason it does not qualify", "pairs"], [[k, v] for k, v in sorted(reason_count.items(), key=lambda kv: -kv[1])] + [["qualifies", len(qualifying)]]))
    w("")
    tm_av = 0     # no source records a queue or a proven avoidable idle interval (section 7.1)
    tm_un_mn = [(k, c) for k, c in tcells.items() if c["wall"] and k[0].startswith("o1") and c["unresolved"] / c["wall"] >= THRESHOLD]
    w(f"Time categories ({len(tcells)} time cells, section 7.1): avoidable waiting at or above 25% in {tm_av} cells (it is 0 ms everywhere). "
      f"Unresolved time is at or above 25% in {len(unres)} cells and in {len(tm_un_mn)} of the O1 time cells; it is unattributed, so it cannot qualify under any reading. "
      f"Scheduling therefore has no demonstrated target.")
    w("")
    w("### 9.1 Pairs at or above 25% in model-needed cells (all of them)")
    w("")
    rows = [[short_cell(r["cell"]), r["category"], pct(r["share"]), r["status"], r["variable"] or "none", "; ".join(r["reasons"]) or "QUALIFIES"]
            for r in q if next(c for c in cells if c["cell"] == r["cell"])["model_needed"]]
    w(md_table(["cell", "category", "share", "attribution", "single variable", "why not"], rows))
    w("")
    w("### 9.2 Thinking, failed or resent, check-driven and caller overhead at or above 25% in the other cells")
    w("")
    rows = [[short_cell(r["cell"]), r["cell"][5], r["category"], pct(r["share"]), r["status"], "; ".join(r["reasons"])]
            for r in q if r["category"] in ("thinking", "failed_resent", "check_driven", "caller_overhead")
            and not next(c for c in cells if c["cell"] == r["cell"])["model_needed"]]
    w(md_table(["cell", "stratum", "category", "share", "attribution", "why not"], rows))
    w("")
    w("Input categories at or above 25% in the host-computable cells (packet, fixed, unsplit) are in `per_cell.csv`. They are not model-needed, so none can qualify.")
    w("")
    w("### 9.3 Final list")
    w("")
    if qualifying:
        w(md_table(["cell", "category", "share", "single-variable candidate"], [[short_cell(r["cell"]), r["category"], pct(r["share"]), r["variable"]] for r in qualifying]))
    else:
        w("Qualifying categories: none. **No demonstrated actionable bottleneck.**")
    w("")
    w("Conditional reading (not a qualification): if Astra defines the fixed per-call input as H, these O1 cells are at or above 25% and the single variable would be H length (the system text) or, for the size-1 cells, batch size (jobs per call):")
    w("")
    rows = [[short_cell(c["cell"]), pct(share(c, "fixed_in")[0])] for c in cells if c["model_needed"] and c["cell"][5] == "main" and share(c, "fixed_in")[0] is not None
            and share(c, "fixed_in")[0] >= THRESHOLD]
    w(md_table(["cell", "fixed per-call input share"], rows))
    w("")

    # ---------------- ambiguities
    w("## 10. Ambiguities resolved and gaps")
    w("")
    amb = [
        "Model-needed. The preregistration says qualification needs a model-needed job but not how that is decided. I used the host-computable scan: a job is model-needed only if no check recomputes its full answer. By that test the only model-needed workload is O1 repair, which matches the signed note that O1 is the only workflow that needs the model.",
        "Control and smoke strata. Item 1 says the boundary and adopt-qual envelopes are 'historical boundary and qualification controls only' and smoke runs are 'a separate descriptive stratum'. I report their cells but they cannot qualify. They would fail the model-needed condition anyway, because classification is host-computable.",
        "H attribution. The corpus never varies H alone, so H cannot be separated from the CLI's own request framing. I split billed input into packet input (regression slope on the ledger's own prompt estimate, an estimate from measured totals) and a fixed remainder labelled H plus CLI framing, which I treat as an unattributed residual. The prereg's rule that unknown attribution cannot qualify is applied to it. If Astra reads that remainder as H, section 9.3 lists the cells.",
        "Cache read versus cache write inside the fixed input is shown only at whole-call level (section 5.2). A per-call split of H into cache write and cache read would assume the system block precedes the packet, which the counters cannot confirm.",
        "Counter source. live22 to live29 hold CLI `usage` counters, not `modelUsage`; pilot2 holds runner-summed `modelUsage`; ledgers hold adapter counters derived from `modelUsage`. Each is used as stored and named in every row. The runner passes `--tools ''`, so one turn is expected and `usage` should equal `modelUsage`, but `num_turns` was not stored, so that is an expectation, not a check.",
        "Thinking for step4 live2, live3 and O1 comes from the run report, joined to the ledger by scenario, receipt, stage, attempt and member count (and tokens where the first join was not unique). step4 live1 has no thinking source. Calls that were killed and recovered (no `call_end`) have total input and output from the report and no cache split.",
        "Tags. 'Failed' = a call_end with a nonzero exit, timeout or non-ok outcome, an errored or invalid flat run, or an envelope whose evaluation was not entirely correct. 'Resent' = attempt above 1 or a `retry_of`. 'Check-driven' = resent calls and the original call each resend names in `retry_of` (the call ledger's own validation is structural and shows no rejection, so the origin is identified through the resend); its tokens are counted whole although only the rejected members were wasted. A call killed and recovered from its capture is not failed (its result was used). Caller overhead = all caller tokens on delegating arms.",
        "Time. Ledger runs have no recorded end-to-end wall, so their wall is the call span; the whole live run's start and finish are in the report but cover all scenarios together. Avoidable waiting is 0 because no source records a queue or backoff, and independent-call serialization is a replay hypothesis (the step4 and O1 stages are DAG-ordered: bounds needs the extracted fields, classification needs the checked interval, adapter needs the accepted core), not a measurement.",
        "Smoke strata are in the corpus tables under their own stratum and in no share used for a conclusion.",
        "Digest scope. The manifest digest covers all 858 entries, observation and provenance, over raw bytes. A checkout that rewrites line endings would change it.",
    ]
    for i, a in enumerate(amb, 1):
        w(f"{i}. {a}")
    w("")
    return "\n".join(L) + "\n"



def main(argv):
    if "--freeze" in argv:
        if MANIFEST.exists():
            raise SystemExit("manifest already frozen; refusing to overwrite")
        man = freeze()
        MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(man["count"], man["digest"])
        return 0
    man, units, fits, cells, runs = build()
    if "--csv" in argv:
        cmd_csv(Path(argv[argv.index("--csv") + 1]), units, cells, runs, fits)
    if "--md" in argv:
        Path(argv[argv.index("--md") + 1]).write_text(render(man, units, fits, cells, runs), encoding="utf-8")
    h = headline(units, cells, man)
    for k, v in h.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
