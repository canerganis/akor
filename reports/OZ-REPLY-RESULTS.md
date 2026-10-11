# ÖZ/6 yanıt biçimi ölçümü

Bu birleşik rapor 6 canlı model çağrısı ve 0 çevrimdışı benchmark model çağrısı içerir.

## Çevrimdışı fixture karşılaştırması

`o200k_base` ve `cl100k_base` kullanıldı. Girdi tarafında yalnız ek yanıt sözleşmesi sayıldı; ortak görev girdisi, kimlikler, provider sarmalı ve yeniden denemeler dışarıda. Çıktı tokenları, açıkça sentetik olarak etiketlenmiş ve JSON’a doldurulmuş fixture metinlerinin tahminidir; model çıktısı veya provider kullanımı değildir.

| İş sayısı | Kimlikler | Durumlar | o200k girdi Δ | o200k çıktı tasarrufu | o200k net tasarruf | cl100k girdi Δ | cl100k çıktı tasarrufu | cl100k net tasarruf |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | short | same | +51 | -6 | -57 | +51 | -5 | -56 |
| 1 | short | mixed isteği; tek iş=0 | +51 | -6 | -57 | +51 | -5 | -56 |
| 1 | long | same | +51 | -2 | -53 | +51 | -1 | -52 |
| 1 | long | mixed isteği; tek iş=0 | +51 | -2 | -53 | +51 | -1 | -52 |
| 4 | short | same | +51 | +15 | -36 | +51 | +16 | -35 |
| 4 | short | mixed | +51 | +9 | -42 | +51 | +10 | -41 |
| 4 | long | same | +51 | +31 | -20 | +51 | +32 | -19 |
| 4 | long | mixed | +51 | +25 | -26 | +51 | +26 | -25 |
| 16 | short | same | +51 | +99 | +48 | +51 | +100 | +49 |
| 16 | short | mixed | +51 | +69 | +18 | +51 | +70 | +19 |
| 16 | long | same | +51 | +163 | +112 | +51 | +164 | +113 |
| 16 | long | mixed | +51 | +133 | +82 | +51 | +134 | +83 |
| 64 | short | same | +51 | +435 | +384 | +51 | +436 | +385 |
| 64 | short | mixed | +51 | +309 | +258 | +51 | +310 | +259 |
| 64 | long | same | +51 | +691 | +640 | +51 | +692 | +641 |
| 64 | long | mixed | +51 | +565 | +514 | +51 | +566 | +515 |

`Girdi Δ` lanes sözleşmesi eksi rows sözleşmesidir. `Net tasarruf`, sözleşme farkı ile fixture çıktı tasarrufunu toplar; pozitif değer lanes lehinedir.

## Canlı gpt-6-luna biçim denemeleri

Her eşleşmiş örnek aynı işleri rows ve lanes biçimlerinde ayrı çağrılarla karşılaştırır. Exact scorer iş sayısı, sıra, durum ve metni kontrol eder; lanes çıktısında receipt’i de doğrular. Sağlayıcının `turn.completed` kullanım değerleri gösterilir; Codex sistem bağlamı ve sarmalı tam-girdi sayılarına dahildir. Bu değerler yalnız sözleşme token hesabıyla karşılaştırılmamalıdır.

| İş sayısı | Kimlikler | Exact scorer | Provider input tokens rows → lanes | Provider output tokens rows → lanes | Input + output toplamı rows → lanes |
|---:|---|---|---:|---:|---:|
| 1 | short | geçti (iki biçim) | 24595 → 24656 | 33 → 39 | 24628 → 24695 |
| 16 | long | geçti (iki biçim) | 25124 → 25511 | 468 → 378 | 25592 → 25889 |
| 64 | short | geçti (iki biçim) | 26484 → 26545 | 1574 → 1262 | 28058 → 27807 |

Reasoning output sayısı `output_tokens` içinde alt alan olarak verildiğinden toplamda ikinci kez eklenmedi; `cached_input_tokens` da `input_tokens` değerine eklenmedi. Provider’ın verdiği `usage` nesnesi ham saklanır; bilinmeyen alanlar yeniden yorumlanmaz.
3 eşleşmiş örnekten genel iyileşme veya model kalitesi sonucu çıkarılamaz.

## Sınırlar

- Çevrimdışı fixture metinleri sentetiktir; hiçbir görev veya araç çalıştırılmadı.
- Token karşılaştırması yalnız `tiktoken 0.14.0` ile `o200k_base` ve `cl100k_base` için yapıldı.
- Tek receipt fixture’ı kullanıldı; başka receipt dizileri az miktarda tokenizer farkı yaratabilir.
- Provider input tokenları Codex CLI’ın gizli sistem bağlamını da kapsar ve sözleşme farkını tek başına ölçmez; provider’ın `usage` alanları ham haliyle JSON’da tutulur.
- Canlı örnek sayısı azdır ve anlamayı, doğruluğu veya üretim kalitesini genellemek için yeterli değildir.

Ham canlı model yanıtları ve tam ölçümler `oz-reply-results.json` içinde saklanır.
