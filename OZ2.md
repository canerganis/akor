# ÖZ/2: birleşik anlamlar ve kalıcı aktarım

Güncel 0.4.0 çalışma alanı, otomatik paketleme, öncül sonuçlarının aktarımı ve Worker adaptörü için [kullanım kılavuzuna](USAGE.md) bak. Aşağıdaki dil sözleşmesi korunur; kuyruk API'si geriye uyumlu genişletildi.

Paket 0.3.0. [ÖZ/1](OZ.md) atomları korunur; `r` artık prosedürü de kaynak olarak okuyabilir. Büyük ASCII harfleri yalnız kanal sözlüğünde tanımlanırsa makrodur. Makrosuz kanal `V` mesajını reddeder.

## Anlam makroları

```python
from oz import Atom, Codebook, Macro

book = Codebook([
    Macro("V", (Atom("r", 0), Atom("a", 0), Atom("t", 14))),
    Macro("P", (Atom("r", 13), Atom(">", 12))),
])
```

Tanımdaki `0` tek parametrenin yer tutucusudur; tel üzerinde geçerli referans değildir. Sözlük `Channel(..., codebook=book)` ile bağlanır.

| Mesaj | Tam açılım |
|---|---|
| `V7` | `r7a7t14` |
| `V` | Aktif referans 7 ise `r7a7t14` |
| `P` | `r13>12` |
| `VP` | Aktif 7 ise `r7a7t14r13>12` |
| `V+8.` | Makroyu aç; mevcut test raporu 8'in başarısını bildir; adım bitişini bildir |

Makro 2–16 temel iş atomundan oluşur: `a`, `r`, `t`, `>`. İç içe makro, literal, kanıt ve durum atomu tanıma alınmaz. Tek `V` başarı, onay veya bitiş iddiası saklamaz. Sabit referanslar mevcut ve doğru tipte olmalıdır. Aynı parametreyi hem yama hem prosedür isteyen bir tanım reddedilir.

Tam açılım dahil kare sınırı 64 atom; tel sınırı 8192 UTF-8 byte'tır. Bilinmeyen makro tahmin edilmez. `P7` gibi parametresiz makroya argüman vermek hatadır. İşlem sırası değişmez; tekrarlanan işler kendiliğinden silinmez. Sözlükte olmayan yeni bilgi `:tam metin` ile aynen aktarılır.

Sözlük, atom tip kuralları, amaç, tam referans içerikleri, aktif referans, oturum/görev/revizyon ve yönlendirme kanal parmak izine bağlanır. Tanımı değiştirince yeni kanal gerekir. Parmak izi kimlik doğrulama veya şifreleme sağlamaz; güvenilir host tarafından taşınır. Referansların yalnız hash'lerini vererek modelin içeriği bildiği varsayılmaz.

## Kodlayıcı ve alıcı girdisi

`Channel.encode` kesin anlam ağacını alır. Temel yazımlar, aktif referansın düşmesi ve tam eşleşen makrolar için sınırlı adaylar oluşturur. Varsayılan 256, üst sınır 4096 adaydır. Tam açık yazım ve byte bakımından en kısa aday daima değerlendirilir. Tokenizer her tam mesajı sayar; parça maliyetleri toplanarak yaklaşık karar verilmez.

Bütün olası yazımlar için en az token garantisi yoktur. Sayaç yoksa yalnız byte uzunluğu kullanılır. Birden çok sayaçta en yüksek sayı, sonra toplam en aza indirilir; bu dolar maliyeti optimizasyonu değildir.

`oz_batch.render`, 1–64 bağımsız ve aynı kanala ait mesajı birleştirir. Açık metin, anlamı koruyan kısa metin, işlem sözleşmeli kompakt JSON, sözlüklü ÖZ ve sözlüklü temel ÖZ ölçülür. Her biri referans nesneleri ve alanları tanımlanmış referans dizileriyle denenir.

Referansın metni, kaynağı, durumu, sayıları, birimleri ve belirsizliği aynen kalır. Literal mesajlar JSON ile kaçırılır ve veri olarak ayrılır; içlerindeki `V` veya satır sonları yeni komut değildir. Görev amacı, aktif referans, gereken kaynaklar ve sözlük her adayın ölçümüne dahildir. Önceki API bağlamının ücretsiz tutulduğu varsayılmaz; tek girdide ortak kaynak bir kez bulunur.

```python
from oz_batch import render

packet = render(channel, [("j1", "V"), ("j2", "P")],
                counters=[count_for_model], max_tokens=1200)
packet.text          # Alıcı model girdisi
packet.tokens        # Her sayaç için toplam
packet.alternatives  # Diğer tam girdi seçeneklerinin maliyeti
packet.wires         # Optimize edilmiş mesaj gövdeleri
```

`count_for_model` hedef tokenizer sayacıdır. `max_tokens` her sayaç için, `max_bytes` tüm girdi için uygulanır. Sığmayan paket hata verir; içerik kesilmez. Host daha küçük paket hazırlamalıdır. Gönderici talimatı, geçmiş, cevaplar, düşünme, araçlar ve sağlayıcı sarmalayıcıları ayrıca ölçülür.

## Kalıcı aktarım ve ajan bağımlılıkları

`oz_runtime.Inbox(path)` SQLite/WAL kullanır. Ayrı iş parçacığı/süreç kendi `Inbox` bağlantısını açmalıdır. Tek bağlantıyı iş parçacıkları arasında paylaşma.

```python
from oz_runtime import Inbox

with Inbox("agent-inbox.sqlite") as inbox:
    inbox.post(channel, "job1", "V", binding=channel.binding)
    inbox.post(channel, "job2", "P", binding=channel.binding, after=["job1"])
    delivery = inbox.claim(channel, owner="worker", lease_seconds=120)
    if delivery:
        packet = delivery.prepare(channel, counters=[count_for_model], max_tokens=1200)
        # replies = your_provider(packet.text)
        # Yanıtı doğrulayıp işledikten sonra, ID -> sonuç metni ile:
        # inbox.complete(delivery, {"job1": replies["job1"]})
```

Bu bir adaptör örneğidir; `channel`, tokenizer ve sağlayıcı çağrısı uygulamandan gelir. Tam yerel demo [oz2_demo.py](examples/oz2_demo.py). Kaynakların ve sözlüğün gönderici modelin gerçek bağlamında bulunması da adaptörün görevidir.

| API | Davranış |
|---|---|
| `post(..., after=[...])` | Çözümler, tip/durum kontrolü yapar, kalıcı kaydeder |
| `claim(..., kind="work")` | Bağımlılıkları bitmiş işleri atomik teslim eder |
| `claim(..., kind="host")` | Yalnız durum/kaynak isteği olaylarını teslim eder |
| `complete(delivery, {id: result})` | Tüm sonuçları ve ACK'leri aynı işlemde kaydeder |
| `retry(delivery, reason)` | Geçici hatada yeniden sıraya alır; limit dolduysa başarısız yapar |
| `retry(..., permanent=True)` | Kalıcı başarısızlık kaydeder |
| `renew(delivery, lease_seconds=...)` | Hâlâ geçerli teslimin süresini uzatır |
| `inspect(id)` | Durum, deneme, sonuç, hata ve beklenen öncülleri döndürür |
| `channel(binding)` | Kayıtlı kanalı geri yükler ve parmak izini doğrular |

Mesaj ID'si bütün `Inbox` içinde benzersizdir. Aynı ID ve anlam yeniden gönderilirse `False` döner, yeni kayıt açılmaz. `V` ve `r7a7t14` eşdeğerse aynı yeniden gönderimdir. ID aynı fakat anlam, kanal, öncüller veya deneme limiti farklıysa reddedilir. Farklı ID'lerde aynı metin ayrı işler olarak korunur.

Bağımlılıklar daha önce eklenmiş, aynı oturum/görev/revizyondaki mesajlara işaret eder. Gönderici/alıcı farklı olabilir: inceleyen ajan çalışan ajanı bekleyebilir. İleri referans ve kendine bağımlılık reddedilir; bu ekleme sırası döngü oluşturamaz. Bir öncülün `done` olması adaptörün sonuç kaydı ve ACK'sidir; doğruluk onayı değildir. Başarısız öncül bağımlı işi bekletir; `inspect(...)["waiting_for"]` nedeni gösterir. Onarım kararını host verir.

Teslim rastgele lease kimliği, sahibi ve son geçerlilik süresi taşır. İki bağlantı aynı bekleyen işi birlikte sahiplenemez. Süre dolunca sonraki `claim` işi yeniden açar; eski cevabın ACK'si reddedilir. Varsayılan üç deneme vardır; süre aşımı da deneme tüketir. Uzun model çağrısında zamanında `renew` gerekir. Bütçe hatası model çağrısından önce düzeltilmelidir.

İş ve durum aynı karedeyse (`V+8.`) durum önden uygulanmaz; tüm kare sırayla iş tesliminde kalır. Yalnız durum kareleri host kuyruğundadır; kayıt için model çağrısı istemez. `/` host kararı olmadan görevi durdurmaz; `+` kaynak doğruluğunu ispatlamaz.

**Teslim en az bir kezdir.** Süreç dış aracı çalıştırdıktan sonra ACK yazmadan kapanabilir. Yeniden teslim dış etkiyi tekrarlayabilir; araç adaptörü mesaj ID'sini idempotency anahtarı olarak kullanmalıdır. Kuyruk yetkilendirme, kaynak doğruluğu, ağ güvenliği veya görev kalitesi denetimi değildir. SQLite dosyası görev içeriğini düz biçimde tutar; dış paylaşımı host yönetir.

## Taşınabilir manifest ve CLI

`channel.snapshot()` JSON verisi döndürür; `Channel.from_snapshot(...)` bunu yeniden doğrular. [Örnek kanal](examples/oz2-channel.json).

```powershell
oz prompt --channel examples/oz2-channel.json
oz decode --channel examples/oz2-channel.json V
oz pack --channel examples/oz2-channel.json --messages examples/oz2-messages.json --encoding o200k_base --max-tokens 1200
```

`decode` ve `prompt` bağımlılıksızdır. `pack` için isteğe bağlı tokenizer: `python -m pip install ".[benchmark]"`. Hiçbiri modeli/araçları çalıştırmaz. Hatalı kare, manifest veya bütçe çıkış kodu 2 üretir.

## Doğrulama

```powershell
python -m unittest discover -s tests -v
python -X utf8 -m examples.oz2_demo
python -X utf8 oz2_benchmark.py
python -X utf8 oz_live_eval.py --suite oz2 --live
```

Son komut mevcut Codex ve Claude CLI hesaplarında gerçek model kullanımı tüketir; yalnız sentetik örnekler gönderir. `--live` olmadan istemi basar. Anahtar oluşturmaz, genel ayarları değiştirmez. [Sonuçlar](reports/OZ2-RESULTS.md).

0.3.0 tip kurallarını da parmak izine eklediği için 0.2.0 kanal kimlikleriyle yeniden senkronizasyon gerekir. ÖZ/1 ve AKOR/1 sözdizimi desteklenir; önceki raporlar tarihli 0.2.0 kanıtlarıdır.
