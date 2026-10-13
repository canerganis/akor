# Codex ölçüm kiti, aşama 1g, Luna hücresi

`docs/design/stage-1g-final-decision.md` aşama D'deki "Luna medium-64 5+5" hücresi. Tek kol var: H (ÖZ/1g metni, cevabın
ilk boş olmayan satırı tam olarak `OZ/1g` olmalı). 10 prompt, her biri 64 iş:

- 5 standart paket: veri seed'leri 2005 ile 2009 (`std_*.txt`), `bench/live/run1g.py` ile aynı kurulum.
- 5 heterojen paket: `bench/live/hetero1g.py` paket 1 ile 5 (`het_p*.txt`): boş dizi, skaler, nesne, iç içe dizi, iş hatası.

Codex'te ayrı sistem alanı olmadığı için kurallar promptun başında `SYSTEM RULES:`, paket `INPUT:` altında gider.
Doğru cevaplar `oracles/` içinde durur, puanlama kayıtları yeniden kurmaz.

## Çalıştır

Repo kökünden:

```bash
python bench/codex_kit_1g/run_codex.py --model gpt-6-luna --effort medium
```

```bash
python bench/codex_kit_1g/score.py bench/codex_kit_1g/results_gpt-6-luna_medium.jsonl
```

Kesilirse aynı komut kaldığı yerden devam eder. Tablo her prompt için: kabul (cevabın tamamı), doğru iş / 64, geçti
(kabul ve 64/64), girdi ve çıktı tokenı, süre (saniye, duvar saati). Son satır kaç prompt geçtiğini söyler.
Bu hücrenin kapısı 10/10 geçmek.

## Elle

Bir prompt dosyasını olduğu gibi gönder, cevabı hiç düzenlemeden `bench/codex_kit_1g/replies/<aynı dosya adı>` olarak
kaydet, sonra `python bench/codex_kit_1g/score.py --replies bench/codex_kit_1g/replies`. Token sayısı bilinmez.

## Okurken

Cevap yalnız `OZ/1g` satırı ve JSONL kayıtları olmalı. Kod bloğu, açıklama ya da başlık eksikliği üründe olduğu gibi
tüm cevabı geçersiz yapar. Codex CLI her çağrıya yaklaşık 24.500 girdi tokenı ekler. Promptları yeniden üretmek için
`.venv/Scripts/python bench/codex_kit_1g/make_prompts.py` (çıktı aynı olmalı).
