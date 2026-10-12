# Codex ölçüm kiti

Claude modellerinde kullanılan iş setinin aynısı: 16 malzeme kaydı × 4 işlem, her tekrarda farklı kayıtlar,
kesin doğru cevaplar (`oracles/`). İki kol: `0.8-exec` (aynı işi yapan eski sürüm) ve `S1c` (şu anki ÖZ formu).
32 ve 64 iş, 3 tekrar, toplam 12 prompt (`prompts/`).

Codex'te ayrı bir sistem alanı olmadığı için ÖZ kuralları promptun başında `SYSTEM RULES:` başlığı altında,
iş gövdesi `INPUT:` altında gider.

## Otomatik (önerilen)

Repo kökünden, her model için:

```bash
python bench/codex_kit/run_codex.py --model gpt-6-luna --effort medium
```

```bash
python bench/codex_kit/score.py bench/codex_kit/results_gpt-6-luna.jsonl
```

Aynısını `gpt-6-astra` ve Sol için de çalıştır (model adını Codex'teki adıyla ver). Kesilirse aynı komut kaldığı
yerden devam eder. Tablo: geçerli cevap, doğru iş, girdi, çıktı, toplam token, 0.8'e göre fark, medyan süre.

## Elle

Bir prompt dosyasının içeriğini olduğu gibi gönder, cevabı hiç düzenlemeden `bench/codex_kit/replies/<aynı dosya adı>`
olarak kaydet. Sonra:

```bash
python bench/codex_kit/score.py --replies bench/codex_kit/replies
```

Elle yapınca token sayısı bilinmez, sadece doğruluk ölçülür.

## Okurken

Codex CLI her çağrıya kendi talimatından yaklaşık 24.500 girdi tokenı ekler. Bu yüzden toplamdaki yüzde fark
küçük görünür; önce doğruluğa ve çıktı tokenına bak. Cevap sadece JSONL satırları olmalı; kod bloğu ya da açıklama
içeren cevap üründe olduğu gibi geçersiz sayılır.
