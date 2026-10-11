# AKOR

**Bağımsız ajan iletişim dili ve aktarım çekirdeği — paket 0.8.0 / ÖZ/6 cevapları.** Python 3.10+, çekirdekte yalnız standart kütüphane.

## 0.8.0: cevapları da kısalt

ÖZ/6, sonuç metinlerini teslim sırasına bağlayıp tekrar eden görev kimliklerini cevaptan çıkarır. `{"q":"0123456789abcdef","s":0,"v":["sonuç A","sonuç B"]}` iki ayrı iş için açıkça aynı tamamlanma durumunu bildirir; karışık durumlar `s:[0,1]` gibi ayrı verilir. Her çağrının cevap kimliği değişir; eksik cevap başarı sayılmaz.

```powershell
oz plan --workspace .oz-runtime/ekip --reply-mode lanes --show-prompt
oz run --workspace .oz-runtime/ekip --adapter adapter.json --reply-mode lanes
```

Varsayılan eski `rows` biçimidir. `lanes`, destekleyen adaptör için açıkça seçilir; sözleşme ve gerçek cevap kimliği girdi bütçesine dahildir. **Luna'nın 6 canlı biçim çağrısında tüm cevaplar exact denetimi geçti.** 64 işlik örnekte sağlayıcının bildirdiği çıktı **1.574 → 1.262 token** oldu; tam girdi+çıktı **28.058 → 27.807**. Tek ve 16 işlik örneklerde toplam tüketim arttı; bu küçük pilot genel görev başarısı veya hızlanma kanıtı değildir.

**Luna doğrulaması: 212 test geçti.** Paket 0.8.0 kuruldu; depo dışından import, CLI ve lanes kuyruk/cevap akışı yerel olarak kontrol edildi. Eksik cevap, yanlış çağrı kimliği ve karışık başarı/hata durumlarında yeniden deneme davranışı sınandı.

[ÖZ/6 sözleşmesi ve kullanım](OZ6.md) · [Luna cevap ölçümleri](reports/OZ-REPLY-RESULTS.md).

ÖZ/5 [canlı anlama pilotunda](reports/OZ5-LIVE-LANGUAGE.md) 12/12 vaka doğru yorumlandı; bunlar 6 açılım ve 6 ret vakasıdır. [Kodlama pilotunda](reports/OZ5-LIVE-CODING.md) ise 5 küçük fonksiyon için kompakt girdinin yerel token hesabı açık JSON'a göre yaklaşık **%54 daha pahalıydı**. Sözlük/dilbilgisi yükü kazancı aştı. Kaynak kısıtı ihlalleri ve toplu çıktı talimatındaki çelişki, kod doğruluğu kıyasını sınırladı; genel üstünlük gösterilmedi. Aşağıdaki eski sürüm sayıları çevrimdışı ölçümlerdir.

## 0.7.0: ortak işlem biçimi, değişen parametreler

ÖZ/5 bir iş akışındaki birden fazla referansı bağımsız parametre yapar. `Form=r$0a$0t$1` altında `&7,31`, `r7a7t31` anlamına gelir. Toplu görevlerde parametre sütunları ayrıca sıkıştırılır: `(1:24)*2,1:16` tek sütunda 64 hedefi tam sırayla taşır. İş kimlikleri ve sonuçlar ayrı kalır.

Sözlük, bağlam ve cevap biçimi dahil **64 farklı düzenli sentetik görevde 2.743 → 1.524 / 2.680 → 1.521 token**: optimize edilmiş ÖZ/4'e göre **%43–44 ek azalma**. Karışık sırada %14–16, rastgele parametrelerde %9–11 kazanç. Önceki ÖZ/4'ün 64 farklı plan örneği de **2.300 → 1.930 / 2.236 → 1.927** oldu. Kazanç olmayan küçük mesajlarda mevcut biçim korunur.

```powershell
oz compile --channel examples/oz5-training-channel.json --messages examples/oz5-training-messages.json --forms --relative --worker --encoding o200k_base --encoding cl100k_base --out .oz-runtime/oz5-derlenmis
oz unpack --channel .oz-runtime/oz5-derlenmis/channel.json --matrix .oz-runtime/oz5-derlenmis/matrix.json
```

**0.7.0'da 202 test geçti.** O sürümde dil çözümleyici ve kuyruk doğrulandı; canlı model anlama ve gerçek kodlama hızı ölçülmemişti. Doğrudan `channel.fill_form(...)` hazır Form'u tokenizer araması olmadan doldurur. Derleme, her mesajda tekrarlanacak bir iletişim adımı değildir.

[ÖZ/5 dili ve kullanım](OZ5.md) · [Ölçüm ve kontrol örnekleri](reports/OZ5-RESULTS.md). Aşağıdaki eski sürüm ölçümleri tarihli sonuçlardır; yeni sürüm daha fazla paket biçimini karşılaştırır.

## 0.6.0: ortak planı paylaş, yalnız farkı gönder

ÖZ/4 mesajları bağlı bir programdaki değişikliği taşıyabiliyor. `^` ortak programın tamamını, `^2=t31` üçüncü adımın değişmesini, `^@7:9` hedef referansının değiştirilmesini ifade ediyor. Her mesaj özgün Base'den bağımsız çözülür; önceki mesajın hatırlanması varsayılmaz.

```powershell
oz decode --channel examples/oz4-channel.json "^2=t31"
oz compile --channel examples/oz4-training-channel.json --messages examples/oz4-training-messages.json --relative --worker --out .oz-runtime/oz4-derlenmis
```

Örnek 48 adımlı plan `^` ile **1 komut tokeninde** taşınabiliyor; sözlük/bağlam ayrıca sayılır. Sentetik **64 farklı** kod inceleme planında gerekli sözlük, Base, kaynaklar ve cevap biçimi dahil **3.351 → 2.300 / 3.289 → 2.236** girdi tokeni: optimize edilmiş mutlak biçime göre **%31–32 ek azalma**. Aynı frame'lerin tekrarlandığı kontrolde daha ucuz şablon tablosu seçilir; küçük mesajlarda yeni dil zorlanmaz.

**179 test geçti.** Bunlar kodlayıcı, çözümleyici ve kuyruk testleridir; canlı model anlama veya gerçek kodlama hızı ölçümü değildir. Sözlük araştırması tek seferlik hazırlık olarak kullanılmalı; dilbilgisinin kısa olması model hızını tek başına kanıtlamaz.

[ÖZ/4 dili ve örnekler](OZ4.md) · [Ölçüm raporu](reports/OZ4-RESULTS.md).

## 0.5.0: daha az tokenle daha çok işlem isteği

Bu bölümün sayıları 0.5.0 sürümünün tarihli ölçümleridir; 0.6.0 ortak şablon tablosunu da karşılaştırdığı için aynı girdide farklı bir biçim seçebilir.

`V[1:16]`, `VN=rNaNt30` sözlüğü altında **48 işlem isteğini 6 komut tokeninde** taşıyor. Bu sayı sözlük ve kaynak bağlamını içermez. ÖZ/3 hedef listelerini ve aralıkları kesin sırayla açar; tekrar eden iş dizilerinden maliyeti ölçülmüş kısa kodlar üretir.

```powershell
python -m pip install ".[benchmark]"
oz compile --channel examples/oz3-training-channel.json --messages examples/oz3-training-messages.json --encoding o200k_base --encoding cl100k_base --worker --out .oz-runtime/derlenmis
oz decode --channel examples/oz3-channel.json "V[1:16]"
```

`compile`, tam alıcı girdisini karşılaştırır; sözlük maliyeti dahil kazanç bulursa yeni kanal ve kısa mesajlar üretir. Seçilen tokenizer'ların hiçbirinde maliyet artışını kabul etmez. Kazanç yoksa mevcut kanalı korur. Klasörde `channel.json`, `messages.json`, ölçülen `prompt.txt` ve `report.json` oluşur; çalışan kuyruk değiştirilmez.

Sentetik, tekrarlı 192 işlem isteğinde eski uyarlamalı biçime göre toplam girdi **1.133 → 899 / 1.127 → 894 token**: yaklaşık **%20,7** azalma. Sözlük, kaynaklar ve Worker cevap sözleşmesi dahildir. Zaten elle tanımlanmış iyi bir makroya göre ek kazanç yaklaşık **%2,4**; küçük mesajlarda kazanç olmayabilir. Yeni sürümde **161 test geçti**; ÖZ/3 için canlı model anlama/başarı ve toplam hız ölçümü yapılmadı.

[ÖZ/3 dili ve kullanım](OZ3.md) · [Ölçüm ve sınırlar](reports/OZ3-RESULTS.md). Eski ÖZ/1–2 manifestleri ve bağlam hash'leri korunur.

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
