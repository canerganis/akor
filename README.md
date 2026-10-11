# AKOR

**Ajanlar için Kısa Orkestrasyon Dili — paket 0.2.0 / protokoller AKOR/1 ve ÖZ/1.**

**Yeni: [ÖZ/1](OZ.md), sembolik ajan dili.** `a`, `?3`, `+8.` gibi kısa anlam atomlarını çözer; bağlam ve sözlük maliyetine göre alıcı gösterimini seçer. Durum mesajları için ek model çağrısı gerektirmeyen bir aktarım yolu sağlar. Codex → Claude arasındaki 12 örneklik canlı kodlama/çözümleme denemesi geçti. Ayrıntılar ve ölçüm sınırları [ÖZ raporunda](reports/OZ-RESULTS.md).

AKOR, farklı modellerin görev, bulgu, soru, öneri ve sonuçları kısa, denetlenebilir mesajlarla paylaşması için hazırlanmış bağımsız bir prototiptir. Modelin sistem talimatına eklenen küçük bir dil tanımı ve Python ile yazılmış bir mesaj aktarıcısından oluşur. Modelin verilen biçimi takip etmesi gerekir. Aşağıda önceki AKOR/1 metin biçimi anlatılır; yeni ÖZ/1 dili ayrı modüldür. Canlı pilot yalnız ÖZ/1 için yapıldı.

## Bir mesaj nasıl görünür?

```text
do T1 lead>coder {"v":1,"goal":"Zaman aşımını düzelt.","refs":["R1"]}
ask T1 coder>lead {"v":1,"q":"Sınır her deneme için mi toplam süre için mi?"}
offer T1 lead>coder {"v":1,"change":"Her denemede 5 saniye; iki tekrar korunsun."}
done T1 coder>lead {"v":1,"result":"Değişiklik hazır.","check":"not_run"}
```

`do`: görev. `T1`: görev kimliği. `lead>coder`: gönderici ve alıcı. `v`: görevin bağlam revizyonu. `R1`: ortak görev tanımı, kısıtlar veya kanıtın değişmez referansı. İçerik Türkçe, İngilizce veya başka bir dilde olabilir.

| Komut | Anlamı | Gövdenin zorunlu alanları (`v` dışında) |
|---|---|---|
| `do` | Görev ver | `goal` |
| `fact` | Bulgu veya çıkarım bildir | `claim`, `state` |
| `ask` | Belirsizliği sor | `q` |
| `need` | Eksik referansı iste | `ids` |
| `offer` | Değişiklik öner | `change` |
| `review` | Belirli bir öneriyi/sonucu incele | `on`, `verdict`, `reason` |
| `block` | Engeli bildir | `why` |
| `done` | Sonucu ve kontrol durumunu bildir | `result`, `check` |
| `stop` | Durma isteğini bildir | `why` |

`fact.state`: `observed`, `inferred`, `unknown`. Gözlem bir kanıt referansı gerektirir; referansın bulunması iddianın doğru olduğunu ispatlamaz. `done.check`: `passed`, `failed`, `not_run`. Yapılmayan test açıkça `not_run` olur. `review.on`, incelenen mesajın kimliğidir; `verdict` değeri `pass` veya `fail` olur.

## Token nereden azalır?

- Uzun üstveri alanları yerine kısa ve sabit bir başlık kullanılır.
- Tam konuşma dökümü yerine işlenmemiş mesajlar ilgili ajana gider.
- Uzun ortak bilgi değişmez referanslarla paylaşılır. Tanım alıcının mevcut bağlamındaysa yeniden eklenmeyebilir.
- Görev bağlamı, gerekli kanıtlar ve incelemenin hedefi eksikse paket bunları içerir. Yeni veya bağlamı özetlenmiş model oturumunda referans tanımları yeniden gönderilir.
- Ajanlardan yeni bilgi vermeleri, önemli belirsizlikleri sormaları ve tamamlanan görevde durmaları istenir.

Bu son davranış kuralları model talimatıdır. Aktarıcı içerik kalitesini veya modelin durmasını zorla garanti etmez. Sayılar, birimler, dosya konumları, olumsuz koşullar ve belirsizlikler kısaltma uğruna silinmez.

Karakter sayısı token sayısı değildir. Bu projede gerçek token sayımı için [OpenAI'nin tiktoken kütüphanesi](https://github.com/openai/tiktoken) kullanıldı. Sonuçlar yalnız seçilen tokenizer ve örnekler için geçerlidir.

## Hemen dene

Çekirdek Python 3.10+ ve standart kütüphaneyi kullanır; model hesabı veya API anahtarı istemez.

```powershell
cd C:\Users\can02\Projects\akor
python demo.py
python -m akor validate examples/demo.akor
python -m akor decode examples/demo.akor
python -m unittest discover -s tests -v
```

Demo, iki sahte ajanın altı mesajını aktarır. İçindeki test sonuçları açıkça işaretlenmiş sentetik örneklerdir; demo gerçek model çağırmaz veya dosya düzeltmez.

İsteğe bağlı yerel paket kurulumu: `python -m pip install .`. Kurulumdan sonra `akor validate examples/demo.akor` komutu da kullanılabilir. Bu klasörün dışından import etmek için paketi kurabilir veya modülü kendi projenize ekleyebilirsiniz.

## Kendi ajan sistemine bağla

1. [prompts/agent.txt](prompts/agent.txt) içeriğini her ajanın sistem talimatına ekle. Kullanılan model, ajan kimliği, görev ve yetkiler adaptör tarafından belirlenir.
2. Her çalışma oturumu için bir `Hub` oluştur. Görevin amacını, kısıtlarını ve güncel kararlarını kısa bir referansa yaz; `set_task` ile bağla.
3. Modelden gelen her satırı `post` ile doğrula. Göndericiyi modelin iddiasından değil kendi oturumundan belirle; tekrar denemede aynı mesaj kimliğini kullan.
4. `prepare` çıktısını ilgili modele ver. Mesaj işlendiğinde `ack` çağır. Başarısız model çağrısında ACK verme; aynı paket yeniden hazırlanabilir.
5. Hedef model oturumunda gerçekten bulunan referanslar biliniyorsa `retained_refs` belirt. Emin değilsen varsayılan boş değeri koru.

```python
from akor import Hub

hub = Hub(["lead", "coder"])
hub.add_ref("R1", "Amaç: zaman aşımı ekle. İki tekrar korunsun. Birim: saniye.")
hub.set_task("T1", 1, ["R1"])

hub.post("m1", 'do T1 lead>coder {"v":1,"goal":"İstemciyi incele.","refs":["R1"]}',
         sender="lead")
packet = hub.prepare("coder", max_bytes=16384)
model_input = packet.render()  # Kendi model adaptörüne gönder.
# Model çağrısı ve cevabın işlenmesi başarıyla tamamlandıktan sonra:
# hub.ack("coder", packet.ids)
```

Gerçek tokenizer ile paket bütçesi de uygulanabilir:

```python
packet = hub.prepare("coder", max_tokens=1200, count_tokens=your_token_counter)
```

Bu bütçe yalnız paketi kapsar. Sistem talimatı, model çıktısı, araç çağrıları ve düşünme tokenleri ayrı bütçelenir. Bütçe aşılırsa içerik sessizce kesilmez; hata döner. `need` mesajını karşılamak, kaynağı doğrulamak ve modele gerekli içeriği vermek adaptörün sorumluluğudur.

Adaptör için arayüz sözleşmesi [PROTOCOL.md](PROTOCOL.md) içinde. Hazır OpenAI, Claude, Gemini, CrewAI veya LangGraph bağlantısı eklenmedi; çekirdek bunlardan bağımsızdır.

## Ölçüm ve sınırlar

İngilizce kod ve Türkçe malzeme verisi olmak üzere iki sentetik konuşma, `o200k_base` ve `cl100k_base` ile sayıldı. Her format aynı alanları, referansları ve içeriği taşıyor. Karşılaştırmada hem kısa JSON nesnesi hem daha ekonomik JSON dizisi var. Dil talimatı ve gerekli bağlamı her çağrıda yeniden sayan ölçüm ayrıca raporlanıyor.

Sonuçlar ve yöntem: [reports/RESULTS.md](reports/RESULTS.md). Ham sayımlar: [reports/token-counts.json](reports/token-counts.json).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
.\.venv\Scripts\python.exe benchmark.py --output reports/token-counts.json
```

Ölçüm bağımlılığı yalnız proje içindeki sanal ortama kurulur. Tokenizer ilk çalışmada sözlük dosyalarını indirebilir; bunlar `.token-cache` altında tutulur. Örnek içerik bir model sağlayıcısına gönderilmez.

Bu sürümde aktarım bellektedir; süreç kapanınca kaybolur. Ağ taşıma katmanı, kalıcı kuyruk, sağlayıcı adaptörleri, eşzamanlı erişim kilitleri ve araç yetkilendirmesi uygulayan bir servis değildir. `do`, `review pass` veya `done` tek başına araç çalıştırmaz, kullanıcı izni vermez ya da görevi kapatmaz. Ajanlar ve kaynaklar güvenilmeyen içerik olarak ele alınır.

İlk canlı pilotta aynı görevleri kısa düz yazı, JSON ve AKOR ile çalıştırıp başarı oranı, yanlış anlama, düzeltme turu, gecikme ve sağlayıcının toplam kullanımını karşılaştırmak gerekir. Daha düşük mesaj tokeni tek başına daha düşük toplam maliyet veya daha iyi sonuç anlamına gelmez.
