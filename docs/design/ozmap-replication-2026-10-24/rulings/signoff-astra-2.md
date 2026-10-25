# Astra sign-off 2 of rulings P3, P5 and D1 (2026-10-25)

Request: one batched Astra call (gpt-6-astra, high effort, read-only, evidence pack without ops content or sealed ASTs) after repair commit 62285ac, made through a Sonnet relay under A4.13r1.2. The pack held A4.14, owner decisions, signoff-astra.md, the three ruling files with annexes, the request boundary probe scripts and the P5 annex, and the repair diff. D1 was submitted for signature of the text amended under owner decision 4.

Result: P3 signed by Astra A. D1 signed by Astra A on the amended text. P5 not signed: one A4.14.2 blocker. Astra answered in Turkish. The output below is verbatim (scratchpad file signoff2-out.md).

Relay check of the P5 blocker: rulings/evidence/p5-probe/gen_p5.py line 241 reads `established = not final_hits and not final_desc and not owner_markers_final and not external`. The `same_items` value (lines 234 to 240) compares the no auth request with the scrambled auth request and does not enter that decision, as the finding says.

## Verbatim Astra output

## P3
Signed: Astra A P3

Evidence: `bench/ozmap_rep/quota.py::attribution_problem`, `if not account_sha256`, `if not theirs` ve `if theirs != account_sha256` yollarıyla eksik veya farklı hesap kimliğini reddediyor; `coverage_gate` bunu hem owner hem harvested okumalarına uyguluyor. `rulings.py::ANNEX_STATUS`, P3 için `"freshness_and_causal_coverage.status": "established"` gerektiriyor.

Fix: Önceki hesap-hash BLOCKER’ı kapanmıştır.

CHANGE: İmza D5’i veya önerilen 60 dakikalık tazelik kuralını onaylamaz. Manifestteki `"status": "not_established"` korunmalı; nedensel kapsam, tazelik ve persistence/harvesting sertifikasyonu tamamlanmadan bağımlı dispatch açılmamalıdır.

## P5
BLOCKER P5: Sertifikasyon üreticisi, onaylı etkin bağlamla tam eşleşmeyi doğrulamadan `established` üretebiliyor. Onaysız ek talimat veya değiştirilmiş harness girdisi bu denetimden geçebilir; bu, yalnızca yürütmenin durması değil, geçersiz bağlamın geçerli kabul edilmesi yoludur.

Evidence: `rulings/evidence/p5-probe/gen_p5.py::main` içindeki kesin karar:
`established = not final_hits and not final_desc and not owner_markers_final and not external`.
Yakalanan isteğe taranan kaynaklarda bulunmayan bir developer talimatı eklemek veya `user.text` içeriğini değiştirmek bu dört koşulu değiştirmez. `same_items` hesaplanır fakat karara katılmaz; `"harness_input"` eşitliği doğrulanmadan sabit açıklama olarak yazılır. `bench/ozmap_rep/rulings.py::annex_problems` ise bu ekin kabulünde `verdict` ve `route_security_args` değerlerini denetler. Ayrıca `P5-effective-context-evidence.json::provider_block_analysis.residual`, canlı `/models` yanıtının base instructions veya tools içeriğini değiştirebileceğini açıkça kaydeder.

Fix: Onaylı base instructions, bütün ek mesajlar, araç şemaları ve tam harness girdisi için eksiksiz karşılaştırmayı sertifikasyon koşulu yapın; yalnızca açıkça dondurulmuş dönüşümlere izin verin. Canlı model metadata’sının etkisini sabitleyin veya yetkili telemetry sırasında eşdeğerliği doğrulayın. Ek talimat, değiştirilmiş girdi ve araç değişikliği ret testleri ekleyin. Bunlar sağlanana kadar ekin `verdict` değeri `not_established` kalmalıdır.

## D1
Signed: Astra A D1

Evidence: `rulings/D1-auth-attribution.md::Owner amendment`, owner decision 4 kapsamında “the exec route differential is complete attribution evidence” hükmünü getiriyor. `D1-attribution-evidence.json` artık `"status": "complete"` kaydediyor. P5 sınır yakalamalarında boş home için `bearer_source: null`, scrambled home için `"prepared_access_token"` görülüyor; `rulings.py::ANNEX_STATUS`, D1 için `complete` gerektiriyor.

Fix: Değiştirilmiş D1 bakımından ek düzeltme gerekmiyor.

CHANGE: İmza owner decision 4 ile değiştirilmiş metne aittir. Ekteki valid-file kaydı gerçekleşmiş başarılı çağrı değil, uygulanacak denetimdir; canlı scrambled/valid koşulları sağlanmadan `telemetry_certificate` başarılı sayılamaz.
