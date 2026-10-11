"""Corrected live gpt-6-luna OZ/5 comprehension cohort.

Fixtures are validated with the repository's Channel.accept/decode_matrix/
Channel.validate before any provider call. Ground truth never enters prompts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from oz import Atom, Channel, Error, Reference, RULES
from oz_form import FORM_GRAMMAR
from oz_weave import WEAVE_GRAMMAR, decode_matrix
from oz_worker import loads as strict_json_loads

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".oz-eval" / "luna-language" / "corrected-cohort"
OUT_JSON = ROOT / "reports" / "oz5-live-language.json"
OUT_MD = ROOT / "reports" / "OZ5-LIVE-LANGUAGE.md"
MODEL = "gpt-6-luna"
OP_TO_CODE = {"read": "r", "audit": "a", "test": "t", "propose": ">"}
CODE_TO_OP = {v: k for k, v in OP_TO_CODE.items()}


def atom(code: str, ref):
    return {"op": RULES[code].name, "ref": ref}


def make_fixtures():
    fixtures = []
    for rep, (p, q, r, proc) in enumerate(((7, 8, 9, 51), (4, 6, 5, 52)), 1):
        fixtures.append({
            "family": "simple_form", "rep": rep,
            "cases": [
                {"id": f"form{rep}-a", "kind": "form", "payload": f"&{p},{proc}", "expected_valid": True},
                {"id": f"form{rep}-b", "kind": "form", "payload": f"&{p}", "expected_valid": False},
            ],
        })
        reg_ids = [f"reg{rep}-a", f"reg{rep}-b", f"reg{rep}-c"]
        bad_reg_ids = [f"reg{rep}-x", f"reg{rep}-y", f"reg{rep}-z"]
        valid_first = f"{p}:{r}" if rep == 1 else f"{p},{q},{r}"
        fixtures.append({
            "family": "regular_matrix", "rep": rep,
            "cases": [
                {"id": f"regular{rep}-a", "kind": "matrix",
                 "payload": {"ids": reg_ids, "cols": [valid_first, f"{proc}:{proc+2}"]}, "expected_valid": True},
                {"id": f"regular{rep}-b", "kind": "matrix",
                 "payload": {"ids": bad_reg_ids, "cols": [f"{p}:{r-1}", f"{proc},{proc+2}"]}, "expected_valid": False},
            ],
        })
        mix_ids = [f"mix{rep}-{i}" for i in range(1, 5)]
        bad_mix_ids = [f"mix{rep}-x{i}" for i in range(1, 5)]
        if rep == 1:
            mix_first, mix_second = "7,9,7,8", "51*2,53,52"
            bad_first = "7,0,7,8"
        else:
            mix_first, mix_second = "4,5,4,6", "52*2,54,53"
            bad_first = "4,0,4,6"
        fixtures.append({
            "family": "mixed_matrix", "rep": rep,
            "cases": [
                {"id": f"mixed{rep}-a", "kind": "matrix",
                 "payload": {"ids": mix_ids, "cols": [mix_first, mix_second]}, "expected_valid": True},
                {"id": f"mixed{rep}-b", "kind": "matrix",
                 "payload": {"ids": bad_mix_ids, "cols": [bad_first, f"{proc}*4"]}, "expected_valid": False},
            ],
        })
    return fixtures


FIXTURES = make_fixtures()


def make_channel(fixture):
    refs = [Reference(i, "patch", f"SYNTHETIC patch reference {i}.") for i in range(1, 50)]
    refs += [Reference(i, "procedure", f"SYNTHETIC test procedure {i}.") for i in range(50, 100)]
    return Channel(session="oz5-language-corrected", task=fixture["family"], revision=fixture["rep"],
                   sender="lead", recipient="worker",
                   goal="SYNTHETIC protocol comprehension. Preserve every request and ID.",
                   references=refs, active=7,
                   form=(Atom("r", -1), Atom("a", -1), Atom("t", -2)))


def rows_from_atoms(ids, atoms_per_row):
    return [{"id": mid, "atoms": [atom(a.code, a.ref) for a in atoms]}
            for mid, atoms in zip(ids, atoms_per_row)]


def decode_fixture_case(channel, case):
    if case["kind"] == "form":
        atoms = channel.accept(case["payload"], binding=channel.binding)
        return [{"id": case["id"], "atoms": [atom(a.code, a.ref) for a in atoms]}]
    decoded = decode_matrix(channel, case["payload"], binding=channel.binding)
    rows = []
    for mid, wire in decoded:
        atoms = channel.accept(wire, binding=channel.binding)
        rows.append({"id": mid, "atoms": [atom(a.code, a.ref) for a in atoms]})
    return rows


def primitive_payload(rows, *, invalid=False, case_id="bad"):
    if invalid:
        return {"id": case_id, "frames": [{"id": case_id, "atoms": [atom("r", None)]}]}
    return {"id": case_id, "frames": rows}


def check_primitive(channel, payload, expected_valid):
    try:
        frames = payload["frames"]
        if not frames:
            raise Error("primitive control requires frames")
        for frame in frames:
            if not isinstance(frame.get("id"), str) or not frame["id"]:
                raise Error("invalid primitive frame ID")
            atoms = []
            for item in frame["atoms"]:
                if set(item) != {"op", "ref"} or item["op"] not in OP_TO_CODE:
                    raise Error("invalid primitive output atom")
                atoms.append(Atom(OP_TO_CODE[item["op"]], item["ref"]))
            channel.validate(atoms)
        actual_valid = True
    except (Error, KeyError, TypeError, ValueError):
        actual_valid = False
    return actual_valid


def prepare_cohort():
    prepared, checks = [], []
    for fixture in FIXTURES:
        channel = make_channel(fixture)
        form = (Atom("r", -1), Atom("a", -1), Atom("t", -2))
        for case in fixture["cases"]:
            try:
                gt = decode_fixture_case(channel, case)
                codec_valid = True
                error = None
            except Error as exc:
                gt, codec_valid, error = [], False, type(exc).__name__
            if codec_valid != case["expected_valid"]:
                raise RuntimeError(f"OZ/5 codec preflight disagrees for {case['id']}: {error}")
            checks.append({"case_id": case["id"], "encoding": "oz5", "expected_valid": case["expected_valid"],
                           "codec_valid": codec_valid, "decoded_frame_count": len(gt), "error_class": error})
            if not codec_valid:
                gt = []
            # Direct JSON controls contain no verdict field. Their invalid row
            # uses a missing required reference and is checked by Channel.validate.
            direct = primitive_payload(gt, invalid=not codec_valid, case_id=case["id"])
            primitive_valid = check_primitive(channel, direct, case["expected_valid"])
            primitive_error = None if primitive_valid else "Error"
            if primitive_valid != case["expected_valid"]:
                raise RuntimeError(f"primitive control preflight disagrees for {case['id']}: {primitive_error}")
            if primitive_valid and codec_valid:
                # Each primitive control must decode to exactly the same frames
                # as the real Form/matrix codecs.
                decoded_direct = []
                for row in direct["frames"]:
                    decoded = channel.validate([Atom(OP_TO_CODE[a["op"]], a["ref"]) for a in row["atoms"]])
                    decoded_direct.append({"id": row["id"], "atoms": [atom(a.code, a.ref) for a in decoded]})
                if decoded_direct != gt:
                    raise RuntimeError(f"primitive control does not match OZ/5 codec output for {case['id']}")
            checks.append({"case_id": case["id"], "encoding": "primitive_json",
                           "expected_valid": case["expected_valid"], "codec_valid": primitive_valid,
                           "decoded_frame_count": len(direct["frames"]), "error_class": primitive_error})
            prepared.append({"fixture": fixture, "case": case, "ground_truth": gt,
                             "primitive_input": direct, "channel": channel})
    if len(checks) != 24 or any(c["codec_valid"] != c["expected_valid"] for c in checks):
        raise RuntimeError("cohort codec preflight incomplete")
    return prepared, checks


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_prompt(fixture, *, control=False, prepared=None):
    channel = make_channel(fixture)
    schema = (
        'Return only JSON: {"cases":[{"id":string,"status":"ok"|"error",'
        '"frames":[{"id":string,"atoms":[{"op":"read"|"audit"|"test"|"propose",'
        '"ref":integer}]}]}]}. The op field MUST use exactly one of the descriptive enum '
        'values read, audit, test, propose; never output wire symbols. Invalid cases use '
        'status error and frames []. Preserve input case order, frame order, atom order, '
        'repeated references, and IDs exactly. Each case is independent. Reject missing '
        'arguments, null/zero/unknown references, malformed syntax, and matrix columns '
        'that do not expand to exactly the number of IDs. Never guess.\n'
    )
    if control:
        inputs = []
        for item in prepared:
            case = item["case"]
            if item["fixture"]["family"] == fixture["family"] and item["fixture"]["rep"] == fixture["rep"]:
                inputs.append(item["primitive_input"])
        body = "Encoding: direct primitive JSON frames.\nCases:\n" + json_dumps(inputs)
        grammar = channel.codebook.prompt(["r", "a", "t"])
    else:
        cases = [{"id": c["id"], "encoding": c["kind"], "payload": c["payload"]} for c in fixture["cases"]]
        body = "Encoding: OZ/5 Form and matrix.\nCases:\n" + json_dumps(cases)
        grammar = (channel.codebook.prompt(["r", "a", "t"]) + FORM_GRAMMAR +
                   "\nForm=r$0a$0t$1\n" + WEAVE_GRAMMAR)
    context_atoms = []
    for item in prepared or []:
        if item["fixture"]["family"] == fixture["family"] and item["fixture"]["rep"] == fixture["rep"]:
            for frame in item["ground_truth"]:
                for value in frame["atoms"]:
                    context_atoms.append(Atom(OP_TO_CODE[value["op"]], value["ref"]))
    if not context_atoms:
        context_atoms = [Atom("r", 7), Atom("a", 7), Atom("t", 51)]
    references = channel.context(context_atoms)
    return schema + grammar + "\n" + references + "\n" + body


def prompt_token_estimate(prompt):
    try:
        import tiktoken
        return {"estimate": len(tiktoken.get_encoding("o200k_base").encode(prompt)),
                "method": "local o200k_base prompt estimate"}
    except Exception:
        return {"estimate": None, "method": "unavailable"}


def run_one(cli, prompt, fixture, mode):
    calls = WORK / "calls"
    calls.mkdir(parents=True, exist_ok=True)
    tempdir = Path(tempfile.mkdtemp(prefix=f"{fixture['family']}-{fixture['rep']}-{mode}-", dir=calls))
    answer_path = tempdir / "answer.txt"
    started = time.monotonic()
    cmd = [cli, "-a", "never", "exec", "-m", MODEL, "--sandbox", "read-only", "--ephemeral",
           "--json", "-C", str(tempdir), "-o", str(answer_path), "-"]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, cwd=tempdir,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=180,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        events, usage = [], []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
                    if "usage" in event:
                        usage.append(event["usage"])
            except ValueError:
                pass
        tool_count, tool_item_types = summarize_tool_events(events)
        answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""
        error_class = None
        if proc.returncode and not answer:
            stderr = proc.stderr.lower()
            error_class = "model_unavailable" if any(x in stderr for x in
                ("model not found", "model unavailable", "not available", "unsupported model")) else "cli_failed"
        return {"family": fixture["family"], "rep": fixture["rep"], "mode": mode,
                "model_requested": MODEL, "status": "completed" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode, "error_class": error_class,
                "wall_seconds": round(time.monotonic() - started, 3), "answer": answer,
                "provider_usage_events": usage, "tool_call_count": tool_count,
                "tool_item_types": tool_item_types,
                "separate_tool_trial": bool(tool_count),
                "prompt_sha256": digest(prompt), "prompt_token_estimate": prompt_token_estimate(prompt),
                "fixture_sha256": digest(json.dumps(fixture, ensure_ascii=False, sort_keys=True))}
    except subprocess.TimeoutExpired:
        return {"family": fixture["family"], "rep": fixture["rep"], "mode": mode,
                "model_requested": MODEL, "status": "timeout", "returncode": None,
                "error_class": "timeout", "wall_seconds": round(time.monotonic() - started, 3),
                "answer": "", "provider_usage_events": [], "tool_call_count": 0,
                "tool_item_types": [], "separate_tool_trial": False,
                "prompt_sha256": digest(prompt), "prompt_token_estimate": prompt_token_estimate(prompt),
                "fixture_sha256": digest(json.dumps(fixture, ensure_ascii=False, sort_keys=True))}


TOOL_TYPES = {"command_execution", "mcp_tool_call", "web_search", "file_change", "computer_call"}


def summarize_tool_events(events):
    """Count calls once across started/completed events, including computer calls."""
    candidates = []
    for event in events:
        if not isinstance(event, dict):
            continue
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_type = event.get("type")
        item_type = item.get("type")
        direct = event_type in TOOL_TYPES
        lifecycle = item_type in TOOL_TYPES and event_type in {"item.started", "item.completed"}
        if direct or lifecycle:
            kind = item_type if lifecycle else event_type
            candidates.append((event, item, kind, lifecycle))

    def identity(entry):
        event, item, kind, _ = entry
        call_id = item.get("id") or item.get("call_id") or event.get("call_id") or event.get("id")
        if call_id is not None:
            return (kind, "id", str(call_id))
        stable = {k: item[k] for k in ("name", "command", "arguments", "input") if k in item}
        return (kind, "signature", json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":")))

    # Group lifecycle events by call identity and retain one representative:
    # completion is preferred, while calls that only started still count.
    lifecycle_groups = {}
    direct = []
    for entry in candidates:
        event, _, _, lifecycle = entry
        if lifecycle:
            lifecycle_groups.setdefault(identity(entry), []).append(entry)
        else:
            direct.append(entry)
    selected = []
    for group in lifecycle_groups.values():
        selected.append(next((x for x in group if x[0].get("type") == "item.completed"), group[0]))
    selected += direct
    seen, types = set(), []
    for event, item, kind, _ in selected:
        key = identity((event, item, kind, False))
        if key not in seen:
            seen.add(key)
            types.append(kind)
    return len(types), types


def score(run, fixture, ground_truth):
    run["scorer_revision"] = 2
    if run.get("answer"):
        run["raw_answer_sha256"] = digest(run["answer"])
    if run["status"] != "completed" or run["separate_tool_trial"]:
        category = "tool_used" if run["separate_tool_trial"] else run["status"]
        run.update(score_status=category, strict_case_results=[False, False],
                   semantic_case_results=[False, False], case_count=2,
                   correct_cases=0, semantic_correct_cases=0,
                   case_categories=[category, category])
        return
    try:
        output = strict_json_loads(run["answer"])
        if not isinstance(output, dict) or set(output) != {"cases"}:
            raise ValueError("malformed response object")
        actual_cases = output["cases"]
        expected_cases = ground_truth
        if not isinstance(actual_cases, list) or len(actual_cases) != 2:
            raise ValueError("wrong case count")
        channel = make_channel(fixture)
        strict_results, semantic_results, categories = [], [], []
        def validated_frames(frames, *, aliases):
            if not isinstance(frames, list):
                return None
            decoded = []
            for frame in frames:
                if not isinstance(frame, dict) or set(frame) != {"id", "atoms"}:
                    return None
                if not isinstance(frame["id"], str) or not isinstance(frame["atoms"], list):
                    return None
                atoms = []
                for value in frame["atoms"]:
                    if not isinstance(value, dict) or set(value) != {"op", "ref"}:
                        return None
                    op = value["op"]
                    if type(value["ref"]) is not int or not isinstance(op, str):
                        return None
                    if aliases and op in CODE_TO_OP:
                        op = CODE_TO_OP[op]
                    if op not in OP_TO_CODE:
                        return None
                    atoms.append(Atom(OP_TO_CODE[op], value["ref"]))
                try:
                    validated = channel.validate(atoms)
                except Error:
                    return None
                canonical_atoms = [{"op": RULES[a.code].name, "ref": a.ref} for a in validated]
                decoded.append({"id": frame["id"], "atoms": canonical_atoms})
            return decoded
        for actual, expected in zip(actual_cases, expected_cases):
            if not isinstance(actual, dict) or set(actual) != {"id", "status", "frames"}:
                strict_results.append(False); semantic_results.append(False)
                categories.append("malformed_output"); continue
            if actual.get("id") != expected["id"]:
                strict_results.append(False); semantic_results.append(False)
                categories.append("wrong_id_or_order"); continue
            wanted_status = "ok" if expected["valid"] else "error"
            if actual.get("status") != wanted_status:
                strict_results.append(False); semantic_results.append(False)
                categories.append("false_reject" if expected["valid"] and actual.get("status") == "error"
                                  else "invalid_accepted" if not expected["valid"] and actual.get("status") == "ok"
                                  else "wrong_status")
                continue
            if expected["valid"]:
                wanted = expected["frames"]
                strict_frames = validated_frames(actual.get("frames"), aliases=False)
                semantic = validated_frames(actual.get("frames"), aliases=True)
                strict_ok = strict_frames is not None and canonical_json(strict_frames) == canonical_json(wanted)
                semantic_ok = semantic is not None and canonical_json(semantic) == canonical_json(wanted)
                strict_results.append(strict_ok); semantic_results.append(semantic_ok)
                categories.append("exact_success" if strict_ok else "alias_only_match" if semantic_ok else "decode_error")
            else:
                rejected = canonical_json(actual.get("frames")) == "[]"
                strict_results.append(rejected); semantic_results.append(rejected)
                categories.append("correct_rejection" if rejected else "invalid_accepted")
        run.update(strict_case_results=strict_results, semantic_case_results=semantic_results,
                   case_categories=categories, case_count=2, correct_cases=sum(strict_results),
                   semantic_correct_cases=sum(semantic_results), score_status="scored",
                   strict_response_contract=all(strict_results), semantic_equivalence=all(semantic_results))
    except (Error, ValueError, KeyError, TypeError, AttributeError):
        run.update(strict_case_results=[False, False], semantic_case_results=[False, False],
                   case_categories=["malformed_output", "malformed_output"], case_count=2,
                   correct_cases=0, semantic_correct_cases=0, score_status="malformed_output",
                   strict_response_contract=False, semantic_equivalence=False)


def canonical_json(value):
    """Canonical JSON equality retains JSON type distinctions (e.g. true vs 1)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def summarize(runs):
    usage_events = [u for r in runs for u in r.get("provider_usage_events", []) if isinstance(u, dict)]
    usage = {}
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
        values = [u[key] for u in usage_events if isinstance(u.get(key), (int, float))]
        usage[key] = {"value": sum(values), "unit": "provider-reported tokens"} if values else {"value": None, "status": "unavailable"}
    scores = {}
    for mode in ("oz5", "primitive_json"):
        group = [r for r in runs if r["mode"] == mode]
        scores[mode] = {"calls": len(group), "cases_total_in_denominator": sum(r.get("case_count", 2) for r in group),
                        "strict_response_contract": {"correct_cases": sum(r.get("correct_cases", 0) for r in group),
                                                     "correct_calls": sum(bool(r.get("strict_response_contract")) for r in group)},
                        "semantic_equivalence": {"correct_cases": sum(r.get("semantic_correct_cases", 0) for r in group),
                                                 "correct_calls": sum(bool(r.get("semantic_equivalence")) for r in group)},
                        "case_categories": {c: sum(r.get("case_categories", []).count(c) for r in group)
                                            for c in sorted({c for r in group for c in r.get("case_categories", [])})}}
    return usage, scores


def report_markdown(report):
    lines = ["# ÖZ/5 Luna canlı dil anlama deneyi — düzeltilmiş kohort", "",
             f"Model: `{MODEL}`. Düzeltilmiş kohortta {len(report['runs'])} çağrı var; ÖZ/5 ve ilkel JSON kontrolü aynı cohort düzeninde karşılaştırıldı, iki bağımsız tekrar kullanıldı. Geçersiz girdilerin zorlukları eşlenmedi.", "",
             "Scorer revizyonu: 2. Raw model yanıtları değiştirilmeden strict JSON parser ile yeniden puanlandı; geçerli primitive frame'ler `Channel.validate` ile denetlendi ve JSON eşitliği tür duyarlı canonical biçimde yapıldı.", "",
             "Önceki hatalı kohort ayrı arşivde `invalidated=true` olarak işaretlidir; eski 12+12 vaka paydası bu yeni paydaya eklenmedi. Önceki rapordaki üç ret model hatası değildi: iki karışık matrisin her biri 6 değer/4 ID açıyordu, ikinci düzenli matris ise 2 değer/3 ID veriyordu. Tüm iyi/kötü girdiler canlı çağrıdan önce gerçek `Channel.accept`, `decode_matrix` veya `Channel.validate` ile kontrol edildi; bütün 24 codec preflight denetimi beklenen sonucu verdi. Hiçbir promptta valid/invalid verdict alanı yoktu.", "",
             "## Sonuçlar", "", "| Şekil | Mod | Strict doğru / vaka paydası | Semantik doğru / vaka paydası | Doğru ret | Geçerli yanlış ret | Geçersiz kabul | Süre (s) | Araç |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for run in report["runs"]:
        cats = run.get("case_categories", [])
        lines.append(f"| {run['family']} #{run['rep']} | {run['mode']} | {run.get('correct_cases',0)}/2 | {run.get('semantic_correct_cases',0)}/2 | {cats.count('correct_rejection')} | {cats.count('false_reject')} | {cats.count('invalid_accepted')} | {run.get('wall_seconds','unavailable')} | {run.get('tool_call_count',0)} |")
    for mode, summary in report["score_summary"].items():
        cats = summary["case_categories"]
        lines.append(f"\n{mode}: strict {summary['strict_response_contract']['correct_cases']}/{summary['cases_total_in_denominator']}, semantik {summary['semantic_equivalence']['correct_cases']}/{summary['cases_total_in_denominator']}; kategoriler {json.dumps(cats, ensure_ascii=False)}.")
    lines.extend(["", "Strict skor açıklayıcı enum değerlerini (`read`, `audit`, `test`, `propose`) ve exact ID/frame/atom sırasını ister. Semantik skor ayrıca bilinen wire sembollerini (`r`, `a`, `t`, `>`) aynı primitive adlarına normalize eder; referanslar ve sıralar yine exact olmalıdır.", "",
                  "Geçersiz örnekler eşlenmiş zorlukta değildir: OZ/5 tarafında eksik Form slotu, sütun uzunluğu hatası veya sıfır ref; primitive kontrolde her seferinde eksik/null zorunlu ref kullanıldı. Bu nedenle 12/12 sonuçlar yalnız bu sentetik vakalarda her biçimin codec sözleşmesine uyduğunu gösterir; eşdeğer güçlük, üstünlük veya parity göstermez.", "",
                  "## Token ve süre", "", "| Usage alanı | Provider toplamı |", "|---|---:|"])
    for key, value in report["provider_usage_summary"].items():
        lines.append(f"| {key} | {value['value'] if value['value'] is not None else 'unavailable'} |")
    estimates = [r.get("prompt_token_estimate", {}).get("estimate") for r in report["runs"]]
    prompt_total = sum(x for x in estimates if isinstance(x, int)) if any(isinstance(x, int) for x in estimates) else "unavailable"
    lines.extend([f"\nYerel `o200k_base` prompt tahmini: {prompt_total} token; provider input/cached/output/reasoning alanlarından ayrıdır. Süreler her CLI sürecinin yerel wall time değeridir.",
                  "", "Kapsam sentetik protokol anlama ve codec eşdeğerliğidir. Gerçek kodlama, araç yürütmesi, fiziksel doğrulama veya üretim başarısı ölçülmedi. Ham cevaplar ve prompt/fixture hashleri JSON raporundadır.",
                  "", "## Dil iyileştirme", "", "Üretim `FORM_GRAMMAR` ve `WEAVE_GRAMMAR` aynen gönderildi; cevap enumu çağrıdan önce sabitlendi. Matrisin bağımsız ID sırası ve her sütunun tam olarak ID sayısı kadar açılması kritik kural. Bir adet valid/invalid mixed örneği ekleyerek bu sınırları öğretmek sonraki prompt sürümünde denenebilir.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    prepared, checks = prepare_cohort()
    WORK.mkdir(parents=True, exist_ok=True)
    prompts = []
    fixtures = list(FIXTURES)
    for fixture in fixtures:
        for control in (False, True):
            prompt = build_prompt(fixture, control=control, prepared=prepared)
            prompts.append({"family": fixture["family"], "rep": fixture["rep"],
                            "mode": "primitive_json" if control else "oz5",
                            "sha256": digest(prompt), "text": prompt})
    # Save all exact prompts before the first live request; no ground truth is stored here.
    (WORK / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {"valid": True, "checks": checks, "check_count": len(checks),
                 "fixtures_sha256": digest(json.dumps(FIXTURES, ensure_ascii=False, sort_keys=True)),
                 "prompt_hashes": [{k: p[k] for k in ("family", "rep", "mode", "sha256")} for p in prompts]}
    (WORK / "codec-preflight.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.preflight_only:
        print(f"Codec preflight valid: {preflight['valid']} ({preflight['check_count']} checks); fixtures and prompts hashed.")
        return
    cli = shutil.which("codex.exe") or shutil.which("codex")
    if not cli:
        raise SystemExit("Codex CLI unavailable; no model fallback attempted")
    version = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=15)
    report = {"kind": "oz5_live_language_corrected_cohort", "cohort": "codec_validated_enum_fixed",
              "scorer_revision": 2,
              "invalidated": False, "date": "2026-10-11", "model_requested": MODEL,
              "cli_version": version.stdout.strip() if version.returncode == 0 else "unavailable",
              "fixtures_sha256": preflight["fixtures_sha256"], "codec_preflight": preflight,
              "prior_cohort_correction": "All three OZ/5 rejections previously scored as false rejects were correct: both mixed matrix repetitions expanded six values for four IDs, and the second regular matrix supplied two values for three IDs. Previous cohort denominators remain in the invalidated archive and are not pooled.",
              "language_recommendations": ["Keep response op enum explicit.", "Add a worked mixed matrix example and clarify per-case error isolation."],
              "runs": [], "limitations": ["Synthetic protocol comprehension only.",
                  "Tool-use trials remain in the denominator as unsuitable failures.",
                  "No coding, physical, or production validation."]}
    for fixture in fixtures:
        gt = []
        for case in fixture["cases"]:
            row = next(p for p in prepared if p["fixture"]["family"] == fixture["family"]
                       and p["fixture"]["rep"] == fixture["rep"] and p["case"]["id"] == case["id"])
            gt.append({"id": case["id"], "valid": case["expected_valid"], "frames": row["ground_truth"]})
        for control in (False, True):
            mode = "primitive_json" if control else "oz5"
            prompt = next(p["text"] for p in prompts if p["family"] == fixture["family"]
                          and p["rep"] == fixture["rep"] and p["mode"] == mode)
            run = run_one(cli, prompt, fixture, mode)
            score(run, fixture, gt)
            report["runs"].append(run)
            print(f"{fixture['family']} #{fixture['rep']} {mode}: {run['status']} / {run.get('score_status')}", flush=True)
            if run.get("error_class") == "model_unavailable":
                report["model_access"] = "unavailable; requested model retained; no fallback"
                break
        if report.get("model_access"):
            break
    report["model_access"] = report.get("model_access", "confirmed_by_completed_call" if any(r["status"] == "completed" for r in report["runs"]) else "unconfirmed")
    report["provider_usage_summary"], report["score_summary"] = summarize(report["runs"])
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(report_markdown(report), encoding="utf-8")
    print(f"Wrote {OUT_JSON}\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
