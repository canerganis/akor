# ÖZ/4 — ortak plana göre fark dili

ÖZ/4'te mesajın anlamı, **bağlı bir işlem programından sapma** olarak yazılabilir. Gönderici ve alıcı aynı değişmez programı bilir; gönderici gereken değişikliği belirtir. Her mesaj tam bir işlem dizisine kesin biçimde açılır. Paket sürümü 0.6.0.

Örneğin ortak program:

```text
Base = r7a7t30
```

Bu, 7 numaralı yamayı oku → incele → 30 numaralı test prosedürünü iste demektir.

| Mesaj | Kesin anlam |
|---|---|
| `^` | Ortak programı aynen iste: `r7a7t30` |
| `^2=t31` | Üçüncü adımı değiştir: `r7a7t31` |
| `^@7:9` | Bütün 7 referanslarını 9 yap: `r9a9t30` |
| `^1=` | İkinci adımı çıkar: `r7t30` |
| `^1:1=r8` | İkinci adımın önüne ekle: `r7r8a7t30` |
| `^0:2=r9a9` | İlk iki adımı değiştir: `r9a9t30` |
| `^0=r8;2=t31` | Birinci ve üçüncü adımları değiştir: `r8a7t31` |

İndeksler **sıfırdan** başlar. Dil bir iş akışındaki sıra, hedef ve değişiklikleri kodlar. `^` bir yürütme isteğidir; işin tamamlandığını, testin geçtiğini veya araç izni verildiğini söylemez.

## Neden orkestraya uygun?

- Uzun, benzer planlar her seferinde yeniden yazılmadan taşınır. `^`, bağlı 48 adımlı örnek planı iki ölçülen tokenizer'da **1 komut tokeniyle** temsil eder. Planın ilk ve sonraki alıcı girdilerindeki sözlük/bağlam maliyeti ayrıca sayılır.
- Her mesaj aynı değişmez Base'e göre çözülür. Önceki mesajın doğru teslim edilmiş veya alıcı tarafından hatırlanmış olması çözümleme için varsayılmaz. Gerekli Base paketin içindedir.
- İş akışına özgü farklar açık kalır: başka hedef, farklı test prosedürü, ek inceleme veya çıkarılmış adım. Sayılar, kaynak metinleri ve yeni bulgular silinmez.
- Görev kimlikleri, bağımlılıklar, yeniden denemeler ve sonuçlar mevcut kalıcı kuyrukta ayrı kalır. Dilin kısalığı, bağımsız olmayan işleri paralelleştirme yetkisi sağlamaz.

Bu yöntem yalnız aynı planı tekrar eden örnekte değerlendirilmedi. Ölçümde **64 farklı** kod inceleme planı kullanıldı; her biri 48 işlem isteği içeriyor. Ortak kaynaklar ve sözlük dahil, optimize edilmiş mutlak biçime karşı yaklaşık **%31–32 ek girdi tasarrufu** görüldü. [Yöntem ve sınırlar](reports/OZ4-RESULTS.md).

## Kesin sözleşme

`^i=WORK` özgün Base'in i numaralı ilkel adımını değiştirir. `^i:j=WORK`, Python dilimleme gösterimi gibi `[i,j)` aralığını değiştirir. Boş sağ taraf silme; eşit uçlar araya ekleme demektir. Makrolar ve hedef listeleri açıldıktan sonraki ilkel adımlar indekslenir.

Birden çok düzenleme `;` ile ayrılır. Hepsi **özgün Base koordinatlarını** kullanır; önceki düzenlemeyle kayan dizine göre yorumlanmaz. Başlangıçlar kesin artan sırada olmalı, aralıklar örtüşmemelidir. Aynı başlangıca iki düzenleme yazılamaz. Yeni plan en az 1, en fazla 64 işlem içerir; en fazla 16 düzenleme kabul edilir.

`^@A:B,C:D` ayrı bir biçimdir: Base'deki referansları **eşzamanlı** değiştirir. `^@1:2,2:1` bir takastır; dönüşümler zincirleme uygulanmaz. En fazla 16 eşleme vardır. Kaynak Base'de bulunmalı, tekrar edilmemeli ve hedefinden farklı olmalıdır. Bütün sonuç referansları kanalda mevcut ve işlemle tür açısından uyumlu olmalıdır. Eşleme ile indeks düzenlemeleri aynı frame içinde karıştırılmaz.

Base yalnız `r`, `a`, `t`, `>` türündeki açık ve geçerli ilkel iş isteklerinden oluşabilir. Başarı, engel, kanıt, tamamlanma ve durma bildirimleri Base veya düzenlemeler içinde gizlenemez. Yeni serbest bilgi `:tam metin` olarak eksiksiz aktarılır. Öz yineleme yoktur. Boş mesaj veya sessizlik başarı sayılmaz.

Base ve dilbilgisi, kanalın SHA-256 bağlam kimliğine dahildir. Farklı Base, kaynak, hedef ajan veya revizyon kullanan alıcı mesajı reddeder. ÖZ/1–3 manifestleri değişmez; Base yokken `^` geçersizdir.

## Kullanım

```powershell
python -m pip install ".[benchmark]"
oz decode --channel examples/oz4-channel.json "^2=t31"
oz compile --channel examples/oz4-training-channel.json --messages examples/oz4-training-messages.json --relative --worker --encoding o200k_base --encoding cl100k_base --out .oz-runtime/oz4-derlenmis
```

Çıktı klasörü yeni olmalıdır. `channel.json`, `messages.json`, tam ölçülen `prompt.txt` ve `report.json` oluşturulur. Mevcut kuyruk veya kanal değiştirilmez. Derleyici önce makrolu/listeli mutlak biçimi iyileştirir; sonra en fazla 8 gerçek mesajı ortak program adayı olarak dener. Her tokenizer'da toplam girdi maliyeti artmıyorsa ve en az birinde azalıyorsa yeni biçim kabul edilir. Kazanç yoksa eski biçim korunur.

Rapordaki `absolute_optimized_tokens`, fark diline geçmeden hemen önceki güçlü karşılaştırmadır. `relative_selected`, çıkan kanalın bir Base içerip içermediğini belirtir; paket hâlâ daha ucuz metin/JSON biçimini seçebilir. Komut gövdeleriyle tam alıcı girdisinin tokenleri ayrı değerlendirilmelidir.

Mevcut makrolar yeterliyse `--max-macros 0`, yeni makro aramasını atlayıp yalnız ortak programı seçer. Bu örnekte aynı 2.300 / 2.236 token sonucuna ulaştı; farklı iş yüklerinde aynı sonuç garanti edilmez. Tam makro aramasıyla elde edilen karşılaştırma raporda ayrıca korunur.

Birbirinin aynı frame'ler varsa ayrıca ortak şablon tablosu denenir. Frame bir kez tanımlanır; her görev kimliği ona referans verir. Bu, işleri veya sonuçları birleştirmez. Aynı iş örneğinde tablo fark dilinden ucuzsa tablo seçilir.

Derleme sözlük araştırmasıdır ve çevrimiçi aktarımın her adımında yapılmamalıdır. Aynı bağlam revizyonunda derlenmiş kanalı tekrar kullan:

```powershell
oz pack --channel .oz-runtime/oz4-derlenmis/channel.json --messages .oz-runtime/oz4-derlenmis/messages.json --worker
oz init .oz-runtime/oz4-ekip --channel .oz-runtime/oz4-derlenmis/channel.json
oz send "^" --id inceleme --workspace .oz-runtime/oz4-ekip
oz plan --workspace .oz-runtime/oz4-ekip
```

Kaynak değiştiğinde yeni manifest/revizyon gerekir; eski Base başka kaynak üstünde sessizce yeniden kullanılmaz. `oz init`, eğitim mesajlarını otomatik kuyruğa koymaz. `run`, açıkça seçilmiş model/ajan adaptörünü gerektirir; örnekler gerçek kod değiştirmez veya test çalıştırmaz.

Python'da `Channel(..., basis=[Atom('r', 7), Atom('a', 7), Atom('t', 30)])` ile açık program bağlanabilir. Otomatik seçim için `compile_messages(..., relative=True)` kullanılır. Yeni biçimin tam sözlüğünü `channel.prompt()`, kesin anlamını `channel.accept(frame, binding=channel.binding)` verir. `parse()` tek başına kanal Base'ini bilmez; göreli mesajlar `Channel.accept()` üzerinden çözülür.

## Hız ve kanıt sınırı

Mevcut örnek için `^` bir tokendir; alıcının bu tokeni anlamasını sağlayan sözlük ücretsiz değildir. Tam paket ölçümü Base'i, dilbilgisini, kaynakları ve cevap sözleşmesini içerir.

Yerel dil çözümleme süresi ile modelin görev tamamlama süresi ayrıdır. Sözlük araştırması bu bilgisayarda büyük örnekte onlarca saniye sürebilir; derlenmiş kanalla iletişim araştırmayı tekrar etmez. Göreli kanallarda paketleme varsayılan 32 yazım adayı, eski kanallarda 256 aday kullanır. Python çağrısında `candidate_limit` değiştirilebilir.

ÖZ/4 için canlı model anlama doğruluğu, gerçek kodlama başarısı, toplam API maliyeti ve uçtan uca hızlanma henüz ölçülmedi. Fark kodlama ve ortak sözlük bilinen genel tekniklerdir; bu uygulama için dünya çapında benzersizlik veya küresel minimum iddiası yoktur.
