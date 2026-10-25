# Astra A freeze sign-off (2026-10-25)

Two Astra calls (gpt-6-astra, high effort, read-only; ledger rows astra signoff-freeze and signoff-freeze-r2, Astra 19 and 20 of 30 under A4.13r2), made directly by the driver. Evidence pack: A4, A4.13, A4.14, owner decisions, freeze manifest (ops file hashes collapsed into one digest), build notes, closure ledger and the seven closure reviews, ruling sign-offs, live telemetry evidence. No ops content, no sealed AST. Codex primary used_percent 2 before both calls; Claude weekly 77 percent.

Round 1 raised BLOCKER P5-FREEZE (below, verbatim). Driver check: freeze.json hashes .py, .md, .json and .txt files after CRLF to LF normalization (run.freeze_record), so the model catalog is 719c75b7 there, while the signed P5 binding is the raw byte hash 1d39994d (config.MODEL_CATALOG_SHA256, checked per launch by effective_context.launch_problems). Both hash the same 474123 byte file, confirmed by computing both. Round 2 sent that evidence and the code paths. Round 2 answer is verbatim below.

## Round 1 answer (verbatim)

BLOCKER P5-FREEZE: The frozen model catalog differs from the catalog explicitly approved by both P5 signatories, yet live certification reports success.

**Evidence:** `signoff-opus-3.md` binds `bench/ozmap_rep/model-catalog.json` to SHA256 `1d39994d11492a3c692c060c621e5c0f01213e18f06fcb5407fcd7d824ebd536` and requires a new signature for a changed catalog. Astra’s P5 signature covers that same repair-2 catalog. The supplied freeze instead records `719c75b77ed02c783263f8fe62532ecd0abc1d1ccf2c34b12e5d221d509995a1`.

Nevertheless, the supplied transcript reports `verify-freeze` passing and:

`telemetry --mode live --claude-weekly-percent 77` → `{"telemetry": true, "problems": []}`.

The affected path is `isolation.verify_launch → effective_context.launch_problems`, whose stated purpose includes binding the catalog to the approved context. This discrepancy leaves successful certification attached to catalog bytes outside the supplied P5 approval; it is not merely a refused-launch scenario.

**Fix:** Reconcile the exact catalog bytes and hashes. If the pack contains a transcription error, provide the corrected hash evidence. Otherwise restore the approved bytes or obtain renewed P5 certification and signatures for the changed catalog, then bind and verify the corrected freeze. Preserve existing telemetry and establish its applicability before using it to authorize evaluation.

## Round 2 answer (verbatim)

Signed: Astra A

P5-FREEZE kapanmıştır: `1d39994d…` ham dosyanın, `719c75b7…` aynı içeriğin CRLF→LF normalizasyonundan sonraki hash’idir. `effective_context.launch_problems` her Codex çağrısından önce imzalanmış ham hash’i ayrıca denetler; mevcut telemetry bu onaylı kataloğa bağlıdır.

Sunulan kapanış doğrulamaları, imzalı ruling bağları ve telemetry kanıtları temelinde freeze, A4, A4.13 ve A4.14 ile tutarlıdır; açık A4.14.2 blocker görmüyorum. Değerlendirme dalgaları, kota, kimlik doğrulama ve çağrı sınırı kontrolleri sağlandığında başlayabilir.

İnceleme yalnızca sunulan pakete dayanır; testleri bağımsız çalıştırmadım.

Signed: Astra A
