# AKOR

**Bağımsız ajan iletişim dili ve aktarım çekirdeği. Paket 0.9.0, ÖZ/9 dili.** Python 3.10+, çekirdekte yalnız standart kütüphane.

## 0.9.0: aynı iş, daha az token, daha hızlı cevap

ÖZ/9 her çağrıyı iki kural satırı ve tek bir JSON gövdesi olarak gönderir. Dört kodlama (doğrudan metin, referans numaralı metin, kod çerçeveleri, şablon tablosu) tam paket olarak ölçülür, en ucuzu gider. Model `{"results":[...]}` döndürür: her iş için doğal bir JSON değeri, başarısız iş için `null` ve `"errors":{"<sıra>":"neden"}`. İş kimlikleri ve çağrı kimliği (receipt) modele gitmez, host tarafında kalır.

Canlı ölçüm: Sonnet (`claude -p`), gerçek çıktılı işler (malzeme aralık hesabı, kod onarımı), deterministik doğrulayıcı. Karşılaştırma, aynı işi yapan 0.8 paketiyle. Her çağrıda CLI'ın kendi 905 tokenlık sabit yükü dahildir.

| Çağrı başına iş | Doğru iş (ÖZ/9) | Toplam token | CLI yükü hariç | Medyan süre |
|---:|---:|---:|---:|---:|
| 16 | 0.8 ile aynı veya iyi | %29 az | %41 az | benzer |
| 32 | 96/96 | **%43 az** | %52 az | 7,0 sn (0.8: 7,9) |
| 64 | 192/192 | **%55 az** | %61 az | 9,2 sn (0.8: 14,0) |

1 ile 4 işlik çağrılarda fark yok: sabit çağrı yükü baskın. En büyük kaldıraç az sayıda büyük çağrıdır. Bunun için:

```powershell
oz run --workspace .oz-runtime/ekip --adapter adapter.json --min-batch 16 --max-wait 30
```

`--min-batch` kadar iş hazır olana ya da en eski iş `--max-wait` saniye bekleyene kadar çağrı yapılmaz; bekleme sırasında deneme ve receipt harcanmaz.

Dil spesifikasyonu ve tüm ölçümler: [OZ9.md](OZ9.md), [canlı ölçüm özetleri](reports/). Dili Astra (gpt-6-astra) tasarladı; kod, ölçüm ve eleştiri Claude tarafından yapıldı.

## Önceki sürümler

0.5.0 ile 0.8.0 arasındaki ÖZ/3, ÖZ/4, ÖZ/5 ve ÖZ/6 katmanları 0.9.0'da kaldırıldı: canlı ölçümde token kazandırmadılar. O sürümlerin belgeleri ve kodu `oz-0.8.0-full` etiketinde duruyor. ÖZ/2 kanalları ve kuyruk dosyaları değişmeden yüklenir; kaldırılan özellikleri kullanan bir kanal açık bir hata mesajıyla reddedilir.

## 0.4.0: günlük kullanım

Artık Python entegrasyonu yazmadan çalışma alanı oluşturabilir, mesaj gönderebilir, bütçeyi önceden görebilir ve kendi ajan adaptörünü çalıştırabilirsin. [Hızlı başlangıç ve adaptör sözleşmesi](USAGE.md).

```powershell
python -m pip install ".[benchmark]"
oz demo .oz-runtime/ilk-deneme
oz status --workspace .oz-runtime/ilk-deneme
```

Demo gerçek tokenizer ve yerel stdin/stdout aktarımını kullanır; model hesabı/API anahtarı veya model çağrısı gerektirmez. Boş bir klasör seç. Gerçek bir görev için:

```powershell
oz init .oz-runtime/ekip --goal "Kaynağı incele; sayı, birim ve belirsizlikleri koru." --source veri.txt
oz send r --id incele --workspace .oz-runtime/ekip
oz plan --workspace .oz-runtime/ekip
oz run --workspace .oz-runtime/ekip --adapter adapter.json
```

`adapter.json` çalıştıracağın ajan programının `argv` listesidir. Program JSON stdin alıp JSON stdout döndürür; otomatik seçilen bir model veya gizli ücretli çağrı yoktur. Yalnız `run` açıkça seçtiğin programı çalıştırır.

- **Otomatik paketleme:** Sığan bağımsız işler seçilir; büyük mesaj diğerlerini bekletmez, sığmayan iş deneme harcamaz.
- **Gerçek devir:** Önceki ajanın sonuçları bağımlı ajana eksiksiz, doğrulanmamış veri olarak gider. Ortak sonuç bir kez gönderilir; maliyeti bütçeye dahildir.
- **İş bazında sonuç:** Başarılı işler tamamlanır; yalnız geçici hata alanlar gecikmeyle yeniden denenir. Eksik/yanlış cevap hiçbir işi sessizce tamamlamaz.
- **Kaldığı yerden devam:** İşler, sonuçlar, geçmiş ve raporlar kalıcıdır. Başarısız iş `oz retry ID` ile yeniden açılır.
- **Görünür durum:** `status`, `inspect` ve `plan` ile kimin neyi beklediği ve ölçülen girdi maliyeti görülebilir.
- **Dosyadan başlangıç:** `--source`, `--kind patch` ve `--procedure` ile elle manifest yazmadan kanal oluşturulur. Kaynak metni ve satır sonları korunur, SHA-256 kaynak kimliği kaydedilir.

**143 test geçti.** Çevrimdışı uçtan uca denemede 20 iş, iş paketi başına **350 girdi tokeni** sınırında **3 pakette** işlendi. Yalnız geçici hata verilen iş tekrarlandı. İnceleyici, 20 öncül sonucunu ayrıca 2.048 token bütçesi altında aldı. Model çağrısı sıfır; bu, gerçek model görev başarısı veya hız ölçümü değildir. [0.4.0 doğrulama raporu](reports/WORKFLOW-RESULTS.md).

## Dil ve önceki ölçümler

**Yeni: [ÖZ/2](OZ2.md).** Tek bir `V` işareti, tanımlanmış sözlükte “kaynağı oku → yamayı incele → belirli test prosedürünü iste” dizisini taşıyabiliyor. Bir işaret ancak sözlüğü ve bağlamı biliniyorsa anlamlı; bu şifreleme veya bilgiyi yoktan üretme değildir.

- **Anlam makroları:** Parametreli/sabit makrolar kesin işlem dizilerine açılır. Kanıt veya başarı iddiaları makrolarda gizlenmez.
- **Ölçülen maliyete göre seçim:** ÖZ, makrosuz ÖZ, kısa metin, açık metin ve kompakt JSON karşılaştırılır; sözlük ve bağlam dahil en ucuz aday kullanılır.
- **Toplu aktarım:** Bağımsız mesajlar tek girdide paylaşılır; ortak kaynak bir kez yer alır. Bütçe aşılırsa metin kesilmez.
- **Kalıcı kuyruk:** SQLite; farklı ajan bağımlılıkları, tekrar ayıklama, teslim süresi, yeniden deneme ve eski cevabı reddetme.
- **Modelsiz olay yolu:** Durum mesajları ayrı host kuyruğunda kaydedilebilir. İş içeren mesajlar alıcı modele hazırlanır.
- **Daha az kodlama işi:** Varsayılan en fazla 256 aday; tekrarlanan metin için tokenizer sonucu yeniden kullanılır.

0.3.0 canlı dil denemesinde Codex kodlama **20/20**, aynı mesajların Claude tarafından çözülmesi **20/20** doğru. Aşağıdaki token karşılaştırması o sürümün tarihli ölçümüdür; yeni Worker'ın cevap sözleşmesi ve öncül sonuçları ayrıca sayılır.

Sentetik 64 mesajlık pakette, **sözlük ve gerekli bağlam dahil alıcı girdi tokenleri**:

| Tokenizer | Kısa metin | Kompakt JSON | ÖZ/2 |
|---|---:|---:|---:|
| o200k_base | 1.791 | 1.250 | **814** |
| cl100k_base | 1.790 | 1.248 | **760** |

Bu örnekte kısa metne göre **%54,6–57,5**, JSON'a göre **%34,9–39,1** azalma. Küçük paketlerde metin/JSON kazanabiliyor; seçici onu kullanıyor. Altı alandaki 48 işi ayrı girdilerden 6 toplu girdiye taşımak yaklaşık **%72** azalma sağladı; bu ayrı karşılaştırmada bağlam tekrarının kaldırılması belirleyici. Gerçek görev başarısı veya toplam API hızlanması ölçülmedi. [Yöntem ve sınırlar](reports/OZ2-RESULTS.md).

```powershell
python -X utf8 -m examples.oz2_demo
python -m unittest discover -s tests -v
python -X utf8 -m oz_cli decode --channel examples/oz2-channel.json V
```

Yerel demo bağımsız işleri toplu teslim eder, inceleme ajanını öncüllerinin ACK'sine kadar bekletir ve durum kaydını model çağrısı olmadan işler. Gerçek araç/test yürütmez.

Kurulum: `python -m pip install .`. Komutlar: `oz decode`, `oz prompt`, `oz pack`. Token ölçümü için isteğe bağlı kurulum: `python -m pip install ".[benchmark]"`.

```powershell
oz pack --channel examples/oz2-channel.json --messages examples/oz2-messages.json --encoding o200k_base --encoding cl100k_base --max-tokens 1200
```

Kendi ajanına bağlamak için [ÖZ/2 sözleşmesi ve örnekleri](OZ2.md), [çalışan demo](examples/oz2_demo.py), [taşınabilir kanal](examples/oz2-channel.json). Çekirdek sağlayıcı hesabı/anahtarı gerektirmez; model ve araç adaptörü host'a aittir. Mevcut Orchestra Board veya başka projeler otomatik değiştirilmez.

AKOR, farklı modellerin görev, bulgu, soru, öneri ve sonuçları kısa, denetlenebilir mesajlarla paylaşması için bağımsız bir prototiptir. Aşağıda desteklenmeye devam eden önceki **AKOR/1** metin biçimi anlatılır. Güncel ÖZ/2 kullanımı ayrı belgededir; canlı pilotlar ÖZ diline aittir.

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

AKOR/1 `Hub` aktarımı bellektedir; süreç kapanınca kaybolur. ÖZ/2 için ayrı `oz_runtime.Inbox` kalıcı kuyruk sağlar. Paket ağ sunucusu, hazır sağlayıcı adaptörü veya araç yetkilendirmesi uygulayan bir servis değildir. `do`, `review pass` veya `done` tek başına araç çalıştırmaz, kullanıcı izni vermez ya da görevi kapatmaz. Ajanlar ve kaynaklar güvenilmeyen içerik olarak ele alınır.

İlk canlı pilotta aynı görevleri kısa düz yazı, JSON ve AKOR ile çalıştırıp başarı oranı, yanlış anlama, düzeltme turu, gecikme ve sağlayıcının toplam kullanımını karşılaştırmak gerekir. Daha düşük mesaj tokeni tek başına daha düşük toplam maliyet veya daha iyi sonuç anlamına gelmez.
