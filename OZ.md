# ÖZ/1 — ajanlar için anlam dili

Bu belge 0.2.0'daki temel atom dilini açıklar. Güncel makrolar, 256 adaylı varsayılan arama, toplu girdi seçimi ve kalıcı kuyruk için [ÖZ/2](OZ2.md) belgesine bak. Aşağıdaki eski arama limiti ve raporlar tarihsel sürüme aittir.

ÖZ, kelime ve JSON alanlarını tekrar üretmek yerine tanımlı kavramları birleştiren sembolik bir dildir. Örneğin `a7`, bir yama üzerinde önceden tanımlanmış inceleme işlemini ister. Aktif hedef zaten 7 ise `a` yeterlidir. `+8.` ise 8 numaralı test raporunun başarılı olduğunu bildirir ve atanan adımı tamamlar.

Bu dilin alfabesi görsel yoğunluğa göre seçilmedi. Mısır, Çin ve çivi yazısı gibi yazı sistemlerinden alınan esin, bir işaretin tanımlı bir kavram taşıması ve işaretlerin düzenli birleşmesidir. ÖZ'de bu fikir ortak sözlük, bileşim kuralları ve açık bağlamla uygulanır; tarihsel alfabeler kopyalanmaz. Kod kitabı yaklaşımı kriptografiye benzer görünebilir ama ÖZ şifreleme değildir.

## Çalışan yapı

`oz.py` üç işi yapar:

1. **Anlamı çözer:** Sembolleri kesin işlem ve referanslara dönüştürür. Bunun için ayrıca bir model çağrısı yapılmaz.
2. **Gösterimi seçer:** Alıcının sembol sözlüğü ve gerekli bağlam dahil giriş metnini sayar. Desteklenen gösterimler arasında daha ucuz olanı seçer.
3. **Gereksiz çağrıyı ayırır:** Bilgi isteği, test durumu, engel, adım bitişi ve durma isteğini host olayları olarak ayırır. Yalnız bu olayları kaydetmek için başka bir ajanı uyandırmak gerekmez.

Gönderici modelin talimatı, düşünme süresi, araç kullanımı ve sağlayıcı mesaj sarmalayıcıları ayrıca maliyetlidir. Bu modül bunları yok sayarak toplam tasarruf iddiasında bulunmaz. İnsanların okuyabilmesi seçim ölçütü değildir; anlamın doğru korunması ve ölçülen token maliyeti seçim ölçütüdür.

## Sözlük ve dilbilgisi

| Biçim | Kesin anlam |
|---|---|
| `aN` | N yamasını incele; public API'yi koru; ilgili testleri çalıştır; hataları bildir |
| `rN` | N kaynağını oku; sayı, birim, kısıt ve belirsizlikleri koru |
| `tN` | N'deki test prosedürünün yürütülmesini iste; sonuç iddia etme |
| `>N` | N planını öner; uygulanmış sayma |
| `=N` | N'deki kaynaklı gözlemi bildir |
| `~N` | N'deki hipotezi çıkarım olarak bildir |
| `?N` | N tanımını iste; bilinmeyen içeriği tahmin etme |
| `+N` | N test raporunun başarılı sonucunu bildir |
| `-N` | N test raporunun başarısız sonucunu bildir |
| `!N` | N nedeniyle ilerlenemediğini bildir |
| `.` | Atanan adım bitti; test başarısı veya genel onay anlamına gelmez |
| `/` | Durma isteği |
| `:metin` | Sözlükte olmayan yeni bilgiyi aynen aktar |

`N`, 1–9999 arasında, başında sıfır olmayan bir referans kimliğidir. Örnek: `a7?3` iki atomdur. Boşluk ve ayırıcı gerekli değildir. `a`, `r`, `t`, `>` yalnız hedef aktif referansa eşitse N'yi düşürebilir. Kanıt ve durum atomlarının referansı asla düşmez: çıplak `+`, `=`, `~`, `!`, `?` geçersizdir. `.` ve `/` yalnız son atom olabilir.

Bir kare en fazla 64 atom ve 8192 UTF-8 byte taşır. Daha büyük içerik bölünür. `:` ile başlayan kare bütünüyle açık metindir; ardından gelen işaretler komut olarak yorumlanmaz. Böylece yeni ölçümler, özel adlar, negatif koşullar ve alışılmadık ayrıntılar kaybolmaz. Dili tüm yeni bilgileri tek işarete dönüştüren bir sistem olarak düşünmemek gerekir: kısa işaretin anlamı sözlükte veya gönderilmiş bağlamda mevcut olmalıdır.

## Bağlamı kim taşır?

Yönlendirme bilgileri modelin ürettiği metin dışında host tarafından tutulur: oturum, görev, revizyon, gönderici, alıcı, sözlük sürümü ve referans içerikleri. Bunlar kanala bağlanan SHA-256 parmak izine dahildir. Bir kare başka kanalın parmak iziyle kabul edilmez.

Bu, modelin bağlamını ücretsiz yapmaz. Görevi anlaması için gereken amaç ve kaynaklar gerçek model girdisinde bulunmalıdır. Referanslar kaynak konumu ve tam içerikle sağlanır. Yeni bağlam için yeni `Channel` oluşturulur. Parmak izi doğrulama veya şifreleme değildir; taşımayı doğrulamak, mesaj kimliğini sabitlemek, yeniden denemeleri ayıklamak ve yetki kontrolü adaptörün sorumluluğudur.

`+8` ancak 8 bir test raporuysa ve kayıtlı durumu `passed` ise kabul edilir. `not_run` durumundan başarı üretilemez. Bu kontrol kaydın tutarlılığını denetler; kaynak metnin doğru olduğunu veya bir testin gerçekten çalıştırıldığını ispatlamaz. Kaynağı host doğrular.

## Kullanım

```powershell
cd C:\Users\can02\Projects\akor
python -X utf8 -m examples.oz_demo
python -m unittest discover -s tests -v
```

```python
from oz import Atom, Channel, Reference, prompt

channel = Channel(
    session="s1", task="T1", revision=1,
    sender="lead", recipient="worker",
    goal="Yamayı incele; API değişmesin.", active=7,
    references=[Reference(7, "patch", "Rev abc: timeout ekleyen yama.")],
)

agent_system_instructions = prompt()  # Göndericinin bu dili üretmesi için.
wire = channel.encode([Atom("a", 7)])  # a
atoms = channel.accept(wire, binding=channel.binding)
request_for_receiver = channel.describe(atoms)
```

Gerçek tokenizer ile sınırlı adaylar arasında en ucuz yazımı seç:

```python
import tiktoken

enc = tiktoken.get_encoding("o200k_base")
count = lambda text: len(enc.encode(text, disallowed_special=()))
wire = channel.encode(atoms, counters=[count])
packet = channel.prepare(atoms, counters=[count])
model_input = packet["text"]
```

`encode`, aynı anlamın aktif referanslı ve referansı düşürülmüş yazımlarını dener. En fazla 4096 aday değerlendirir. Birden fazla tokenizer verilirse en yüksek token sayısını, sonra toplamı en aza indirir. Sınırın ötesindeki değişkenler açık yazılır. Bu, tüm olası diller üzerinde matematiksel bir minimum iddiası değildir.

`prepare`, sözlüğü ücretsiz kabul etmez: gereken atom tanımları ve gramer dahil sembolik girdi ile programın ürettiği açık anlamı karşılaştırır. Kısa ve yeni bağlamda çoğunlukla açık anlam kazanır. Sembolik `wire` her iki durumda da elde edilir. Uzun bir ortak bağlamın saklandığı API oturumlarında önceki tokenlar yeniden sayılabilir; adaptör sağlayıcının kullanımını ayrıca izlemelidir.

Durum mesajı için alıcı modeli çağırmadan host'a aktar:

```python
decision = channel.dispatch(wire, binding=channel.binding)
host_events = decision["host_events"]
if decision["needs_model"]:
    # Yalnız karar/iş gerektiren atomları ilgili modele ver.
    pass
```

`dispatch` hiçbir aracı çalıştırmaz, izin vermez ve kullanıcı adına karar almaz. Örneğin durma isteğini uygulamak veya eksik kaynağı getirmek host işidir. Sonraki iş adımı yeni muhakeme gerektiriyorsa host yeniden model çağırabilir.

## Doğrulama ve devam

[Ölçüm raporu](reports/OZ-RESULTS.md), [ham token sayımları](reports/oz-token-counts.json), [canlı pilot](reports/oz-live.json).

```powershell
.\.venv\Scripts\python.exe -X utf8 oz_benchmark.py
python -X utf8 oz_live_eval.py --live
```

Son komut gerçek model kullanımını tüketir. Yalnız sentetik örnekler mevcut Codex ve Claude CLI oturumlarına gönderilir; anahtar dosyası oluşturulmaz, global ayar değiştirilmez. Kodlama ve çözümleme ayrı sağlayıcı süreçlerinde sınanır. Test izleri `.oz-eval/` içinde kalır; raporda yalnız gerekli cevap ve kullanım bilgileri tutulur. Opt-in `--live` olmadan yalnız test istemi basılır.

Mevcut Orchestra Board veya diğer uygulamalar otomatik değiştirilmedi. Paket içine entegre edilecek yol: gönderici talimatı → kısa ÖZ çıktısı → host doğrulama/olay aktarımı → gerektiğinde alıcı girdisi. Üretimde başarı, düzeltme turu, toplam kullanım ve gecikme aynı görevler üzerinde karşılaştırılmalıdır. Çekirdek bağımsızdır; canlı pilotun kapsamı 12 sentetik örnektir.
