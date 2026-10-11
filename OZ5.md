# ÖZ/5 — işlem biçimi ve parametre akışları

ÖZ/5 aynı yapıya sahip farklı görevlerin işlem dizisini bir kez tanımlar; mesajlarda değişen referansları taşır. Toplu aktarımda bu referansları sütunlara ayırıp aralıkları, tekrarları ve döngüleri kısaltır. Paket sürümü **0.7.0**. İstekler kesin olarak açılır; kodlama ve çözümleme model çağırmaz.

## Tek mesaj

```text
Form=r$0a$0t$1
&7,31
```

Bu kanalın bağlı Form'u altında `&7,31`, tam olarak `r7a7t31` demektir: 7'yi oku, aynı yamayı incele, 31'deki test prosedürünü iste. `$0` iki adımda kullanılsa da değeri bir kez gönderilir. `$1` bağımsız bir referanstır. Eski makroların tek parametre sınırı burada yoktur.

Form, sabit referansları da korur. Örneğin `r$0a$0t$1>41` son adımda her zaman 41 numaralı öneriyi kullanır. Bir frame her parametreyi sıra ile tam olarak verir; önceki mesajın değerleri hatırlanmış sayılmaz. Yanlış tür, eksik parametre veya olmayan referans reddedilir.

## Çok sayıda farklı görev

Aynı Form altında:

```json
{"ids":["a","b","c"],"cols":["7:9","30*3"]}
```

Kesin açılım:

```text
a → r7a7t30
b → r8a8t30
c → r9a9t30
```

Birinci sütun `$0`, ikinci sütun `$1` değerlerini taşır. `ids[j]` görevi her sütunun j numaralı değerini alır. Sütunlar yalnız referans numaralarıdır; kaynak metinleri ayrıca tam olarak gönderilir.

| Sütun yazımı | Açılım |
|---|---|
| `7,2,7` | 7, 2, 7 — sıra ve tekrar korunur |
| `7:9` | 7, 8, 9 — artan, iki uç dahil |
| `30*3` | 30, 30, 30 |
| `(30,31)*3` | 30, 31, 30, 31, 30, 31 |
| `(1:24)*2,1:16` | 64 referans: iki tam aralık, ardından 1–16 |

İşler sıralanmaz, kimlikleri kısaltılmaz ve aynı referansı kullandıkları için birleştirilmez. Her iş kendi sonucunu alır. Sütun yapısı paralel çalıştırma izni veya bağımlılıkların kalkması anlamına gelmez. Kalıcı kuyruğun bağımlılık ve yeniden deneme kuralları sürer.

## Otomatik seçim

Derleyici aynı işlem sırasını paylaşan örnekleri gruplar. Bütün örneklerde aynı kalan referansları sabit, birlikte değişen referans konumlarını ortak parametre yapar. Birbirinden bağımsız değişen konumlara farklı parametre verir. Yeni mesaj bu ilişkiyi sağlamıyorsa normal ÖZ veya fark dili ile eksiksiz aktarılır.

Tam alıcı girdisinde makrolar, hedef listeleri, ÖZ/4, parametreli frame'ler, sütunlar, aynı-frame tablosu, metin ve JSON karşılaştırılır. Gerekli sözlük, Form/Base, kaynaklar, görev kimlikleri, önceki sonuçlar ve cevap sözleşmesi sayılır. Derleyici seçilen tokenizer'ların herhangi birinde artışı kabul etmez; en az birinde azalma gerekir. Küçük mesajlarda yeni sözlük eklemeyebilir.

Arama sınırlıdır: varsayılan en fazla 8 Form adayı, frame başına 32 yazım adayı; sütun kodlayıcı sınırlı sayıda aday üzerinde ölçüm yapar. Küresel en kısa dil veya bütün tokenizer'larda optimum iddiası yoktur. Byte uzunluğu ile token sayısı ayrı değerlendirilir.

## Kullanım

```powershell
python -m pip install ".[benchmark]"
oz compile --channel examples/oz5-training-channel.json --messages examples/oz5-training-messages.json --forms --relative --worker --encoding o200k_base --encoding cl100k_base --out .oz-runtime/oz5-derlenmis
```

Klasör yeni olmalıdır. `channel.json`, `messages.json`, `report.json`, tam ölçülen `prompt.txt` oluşur. Matris seçilirse ayrıca kanal kimliğini içeren `matrix.json` yazılır. Mevcut makrolar yeterliyse `--max-macros 0` makro aramasını atlar; aynı kazancı her veri kümesinde garanti etmez. Bu örnekte matrisin son token sayısı değişmez.

```powershell
oz unpack --channel .oz-runtime/oz5-derlenmis/channel.json --matrix .oz-runtime/oz5-derlenmis/matrix.json
oz pack --channel .oz-runtime/oz5-derlenmis/channel.json --messages .oz-runtime/oz5-derlenmis/messages.json --worker
oz init .oz-runtime/oz5-ekip --channel .oz-runtime/oz5-derlenmis/channel.json
```

`unpack`, 64 bağımsız frame'i model çağrısı yapmadan geri açar; işi çalıştırmaz. `pack` en ucuz tam alıcı girdisini yeniden seçer. `init`, eğitim mesajlarını kuyruğa eklemez. Göndermek için mevcut `send`/`run` akışı kullanılır. `run`, açıkça seçilmiş ajan adaptörünü gerektirir.

Hazır kanalda tek bir Form doldurmak için sözlük araştırması veya tokenizer gerekmez:

```python
# Form sırası r$0a$0t$1 olan bağlı kanal:
wire = channel.fill_form(7, 31)  # '&7,31'
atoms = channel.accept(wire, binding=channel.binding)
```

Bu hızlı yol yalnız geçerli mesaj üretir; en ucuz tam paket iddiası taşımaz. Tam maliyet için `oz_batch.render` kullanılır. Örnek demo kanalının dokuz parametresi farklı bir sıradadır; `channel.prompt()` her kanalın gerçek Form'unu gösterir.

Python'da `Channel(..., form=[Atom('r', -1), Atom('a', -1), Atom('t', -2)])` ile Form bağlanır. Snapshot'ta `-1` `$0`, `-2` `$1` anlamındadır; pozitif sayılar sabit referans, sıfır geçersizdir. `compile_messages(..., forms=True)` otomatik seçim yapar. `oz_weave.encode_matrix` / `decode_matrix` taşınabilir matris için kesin kodlayıcı/çözümleyicidir. Çözümleme, beklenen kanal `binding` değerini zorunlu alır.

## Sınırlar ve doğrulama

- Form en fazla 64 ilkel iş adımı ve kesintisiz `$0` ile başlayan 1–32 parametre içerir. Yalnız `r`, `a`, `t`, `>` iş isteklerine izin verilir. Bir parametrenin kullanıldığı bütün adımların referans türleri uyumlu olmalıdır.
- Frame argümanları 1–9999 tam sayı referanslarıdır. Eksik/fazla değer, sıfır, baştaki sıfır, örtük varsayılan, durum veya kanıt bildirimi içeremez.
- Matris 1–64 bağımsız görev içerir. Bütün sütunlar tam olarak görev sayısı kadar değer açmalıdır. Sütun başına en fazla 4096 karakter; açılım en fazla 64 değer. Tek düzeyli gruplar vardır; iç içe grup ve kod yürütme yoktur.
- Form ve matris dilbilgisi kanalın bağlam kimliğine dahildir. Kaynak/kanal değiştiğinde eski paket sessizce yeniden yorumlanmaz. ÖZ/1–4 manifestlerinin hash'leri değişmez.
- Literal bilgi, kanıt, hata ve belirsizlikler kısaltılıp tahmin edilmez. “Test iste” ile “test geçti” farklı anlamlardır.

**202 test geçti.** Parametre ve sütun açılımı, rastgele örnekler, taşınabilirlik, eski hash uyumu, başarısız girdiler, kuyruk kimliği ve bağımlı sonuç aktarımı sınandı. [Ölçüm raporu](reports/OZ5-RESULTS.md).

64 farklı ve düzenli sentetik görevde optimize edilmiş ÖZ/4'e göre **%43–44** daha az alıcı girdisi ölçüldü. Karışık sırada **%14–16**, rastgele parametrelerde **%9–11** kazanç görüldü. Önceki ÖZ/4'ün 64 farklı plan örneği de **2.300 → 1.930 / 2.236 → 1.927** token oldu. Bunlar sözlük/bağlam dahil ölçümlerdir; canlı model anlama doğruluğu, gerçek kodlama başarısı ve uçtan uca hızlanma henüz ölçülmedi.
