# Stage 1g final decision (Astra and Fable, 2026-10-13)

After the C screen failed (stage-1g-screen-evidence.txt), Astra and Fable debated four rounds (stage-1g-debate.md). Astra froze the plan in round 4; Fable confirmed with one objection; Astra dropped the baseline 5/5 rule. Run by bench/live/run1g.py.

## Astra, round 4 (frozen, verbatim)

**Dondurulmuş karar: H önce; yalnız H elenirse G. C kontrolü ve GH deneyi yok. Plan 70 çağrı; G gerekirse en fazla 95.** Haftalık kota açısından Fable’ın imzaladığı sıralı planı seçiyorum.

**Metinler ve parser’lar**

- **H:** Astra Round‑2’deki H metni aynen: C + zorunlu `OZ/1g` başlığı. Profil: `oz1g-header`.
- **G:** G dosyasının bağlayıcı içeriği, yukarıdaki Round‑3 **G bloğudur**, aynen ve başlıksız. Profil: `oz1g-lines`.
- **C:** `oz_batch.SYSTEM`; sahibin bildirdiği live21 bayt eşitliği kabul edilmiştir. Yeni çağrı ayrılmaz.
- **GH:** Round‑3’teki tek cümle değişimiyle tanımlı kalır; bu deneyden çıkarılmıştır.
- **Baseline:** Mevcut `0.8-exec` metni ve parser’ı değiştirilmez.

Round‑3’teki **on maddelik parser sözleşmesi ve yerel kontroller aynen geçerlidir**. Profil çağrı yapılandırmasında seçilir; otomatik algılama, onarım veya biçim değiştirme yoktur.

| Aşama | Çağrılar ve veri seed’leri | Sayı |
|---|---|---:|
| A | Sonnet 5.5–64, H: **1005–1024**; baseline: **1005,1009,1013,1017,1021** | 25 |
| B | H, A’yı geçerse Sonnet–64: beş heterojen paket, **3001–3005** | 5 |
| C | H, A veya B’de elenirse G: aynı 20 standart + aynı beş heterojen paket; baseline yeniden kullanılır | 25 |
| D | Seçilen aday: Haiku 5.5–64 **10+5**, Fable 5.1–64 **5+5**, Luna medium–64 **5+5**, Sonnet–32 **5** | 40 |

D’de standart seed’ler Haiku için **2005–2014**, diğerleri için **2005–2009**; heterojenler yine **3001–3005**. Sonnet–32’de heterojen çağrı yoktur.

Beş heterojen paketin her biri **64 iş** içerir: sırasıyla boş dizi, skaler, nesne, iç içe dizi ve gerçek hata sonuçları. **Her pakette bütün sonuçlar ilgili ailedendir**; böylece çıktı sırasından bağımsız ilk kayıt sınanır. Hata paketinde dört koddan 16’şar iş bulunur. Paketler birlikte sıfır/çok referansı, referans sırasını, izinli `unknown` ve `"error"` ID’sini kapsar.

**Geçiş kapıları**

- Sonnet–64 standart aday kolu: **en az 19/20**; ikinci başarısızlıkta dur. Heterojenler **5/5**, D bütünü **40/40**. Erken başarı ilan edilmez.
- Başarı = parser kabulü **ve bütün işlerin doğruluğu**. Gereksiz hata/unknown, yanlış değer, kesilme veya timeout başarısızlıktır.
- Baseline **5/5** olmalıdır; aksi durumda karşılaştırma sonuçsuzdur, benimseme yapılmaz.
- Sonnet–64 standart iş yükünde, başarısız çağrıların tüketimi dahil: sağlayıcının bildirdiği toplam token/doğrulanmış iş **≤ baseline token/istenen iş × 0,65**. **%35 şart, %40 hedef.** Parasal maliyet/doğrulanmış iş de baseline’dan yüksek olmayacaktır.
- Aynı kapsamda toplam `api_ms`/doğrulanmış iş **≤ baseline `api_ms`/istenen iş**. Ortalama ve medyan ayrıca raporlanır. Beş baseline’ın belirsizliği belirtilir; eşik sonradan gevşetilmez.
- Seed‑1000 o200k sistem+gövde bütçeleri, 32/64 işte: **H ≤1020/1479; G ≤991/1450**. Bunlar sağlayıcı ekonomik kapısının yerine geçmez.

Maliyet/hız kapıları **yalnız Sonnet–64** içindir; D uyumluluk kontrolüdür. Her iki tarafın `C_verified` değeri ve toplam deney harcaması raporlanır.

Çağrılar bağımsız bağlamlarda, eşzamanlılık **1**, bütün retry katmanları **0** ile yürütülür. Metinler, girdiler, oracle, ayarlar ve program ilk çağrıdan önce hash’lenir. Eski beş çağrı sayılmaz. D başarısızsa aday değiştirilmez; benimseme yoktur ve mevcut `0.8-exec` korunur. Erken duruşlar 70/95 tavanlarını azaltabilir.

Bu turda deney veya dosya değişikliği yapılmadı. Yerel okuma `helper_sandbox_lock_failed` nedeniyle engellendi; G’nin dosya yolunu doğrulayamadım, metin referansı yukarıdaki tam bloktur.


## Fable confirmation (verbatim)

Fable: I confirm the frozen plan (H first, G only if H fails, no C or GH, seeds, 64-job single-family heterogeneous packets, Stage D cells, concurrency 1, retry 0, hashed artifacts, Sonnet-64-only cost and speed gates, money cost gate) with one concrete objection.

The "baseline must be 5/5 or nothing is adopted" rule should go: C_requested(0.8-exec) divides by requested jobs, so a baseline packet with a wrong value changes neither that denominator nor the candidate's gate, and the baseline already slipped once in live21 (rep 1, 63/64) and once in live17, so this rule has roughly a one in four chance of voiding 70 calls of the owner's quota over an event unrelated to H. Report baseline failures, count their tokens and time in C_requested as the formula already does, and do not let them block adoption.

## Astra ruling on the objection (verbatim)

**Kaldırıyorum:** Baseline’ın **5/5** olması benimseme koşulu değildir; baseline doğruluk hatası adayın benimsenmesini tek başına engellemez.  
Başarısız baseline çağrılarının token, parasal maliyet ve `api_ms` tüketimi `C_requested` hesabına dahil edilir; hatalar ve `C_verified` ayrıca raporlanır.  
Adayın doğruluk, maliyet ve hız kapıları aynen korunur; **Stage A sürer, ek çağrı gerekmez.**
