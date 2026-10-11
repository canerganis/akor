# ÖZ/3 — minimum tokenle daha çok işlem isteği

ÖZ/3, ÖZ/2'nin kesin anlamlı kısa komutlarına **hedef listeleri, aralıklar ve maliyete göre sözlük derleme** ekler. Paket sürümü 0.5.0. Python çekirdeği modelden ve sağlayıcıdan bağımsızdır.

```text
VN = rNaNt30
V[1:16]
```

Sözlükte `V`: hedefi oku, yamayı incele, 30 numaralı test prosedürünün yürütülmesini iste. `V[1:16]`, bu üç isteği 1'den 16'ya kadar her hedef için sırayla taşır: **48 ilkel işlem isteği, 6 komut tokeni** (`o200k_base` ve `cl100k_base`). Sözlük ve kaynak bağlamı bu 6 tokene dahil değildir. Komutun çözülmesi, görevlerin yapıldığı veya modelin doğru anladığı anlamına gelmez.

## Sözdizimi

| Yazım | Kesin açılım |
|---|---|
| `r[1:4]` | `r1r2r3r4` |
| `r[7,2:4,2]` | `r7r2r3r4r2`; tekrar korunur |
| `V[1:3]` | `r1a1t30r2a2t30r3a3t30` |
| `V` | Yalnız bağlı aktif hedef için makro |
| `:tam metin` | Yeni bilgi; içerik ve satır sonları korunur |

Liste/aralık yalnız `a`, `r`, `t`, `>` ve parametreli makrolara uygulanır. `+`, `-`, `=`, `~`, `!`, `?`, `.`, `/` gibi durum/kanıt bildirimleri listelere veya makrolara gizlenmez. Sabit makrolar liste alamaz. Komut boşluk içermez; serbest metin `:` ile ayrı frame olur.

Aralık uçları dahildir; yalnız artan aralık geçerlidir. `1:4`, mevcut nesneler arasındaki ilk dördü değil, tam olarak 1, 2, 3, 4 kimliklerini belirtir. Eksik veya yanlış türde bir hedef tüm frame'i reddettirir. Hedefler kendiliğinden oluşturulmaz. Başında sıfır olan kimlikler ve 1..9999 dışı değerler geçersizdir.

Her hedefte makronun **tamamı** açılır, ardından sonraki hedefe geçilir. İşlem sırası korunur; paralellik, tekrar ayıklama veya araç yürütme yetkisi eklenmez. Açılmış bir frame en fazla 64 işlem içerir. Bu sınır, küçük bir girdinin denetimsiz büyümesini önler; daha büyük işler ayrı mesajlara bölünür.

## Sözlüğü iş yüküne göre derle

```powershell
python -m pip install ".[benchmark]"
oz compile --channel examples/oz3-training-channel.json --messages examples/oz3-training-messages.json --encoding o200k_base --encoding cl100k_base --worker --out .oz-runtime/derlenmis
```

Çıktı klasörü daha önce var olmamalıdır. Derleme yereldir; model veya araç çalıştırmaz.

- `channel.json`: karşı tarafın da kullanacağı değişmez sözlük ve bağlam.
- `messages.json`: anlamı aynı kalan kısa komutlar ve mesaj kimlikleri.
- `prompt.txt`: tokeni ölçülen **tam alıcı girdisi**, UTF-8 byte olarak.
- `report.json`: önce/sonra sayımları, tokenizer isimleri, arama sınırları ve bağlam kimlikleri.

Derleyici 2..8 adımlı tekrarlanan iş dizilerini bulur. Bir hedef değişkene dönüşebilir; diğer referanslar aynen korunur. Mevcut sözlüğü değiştirmeden yeni makrolar önerir. Her turda en fazla 8 şablon ve şablon başına 2 kod tam paket üzerinden denenir; varsayılan en fazla 4 makro eklenir. Kod ön seçimi mevcut boş A–Z işaretlerinin sözlük maliyetini ölçer. Frame başına 32 yazım adayı denenir. Bunlar sonlu arama sınırlarıdır; evrensel en kısa dili bulma garantisi yoktur.

Bir değişiklik yalnız **her seçilen tokenizer'da toplam alıcı girdisi artmıyorsa ve en az birinde azalıyorsa** kabul edilir. Sözlük, yeni dilbilgisi, kaynakların tam metni, mesaj kimlikleri ve `--worker` seçildiyse cevap sözleşmesi sayılır. Kısa metin, kompakt JSON, ilkel ÖZ, makrolu ÖZ ve vektörlü ÖZ karşılaştırılır. Sözlük kazandırmıyorsa eski kanal korunur.

Optimizasyon, verdiğin en fazla 64 mesajlık paketin ölçümüdür. Gelecek iş yükü için garanti değildir. `--worker` olmadan yalnız genel alıcı sözleşmesi ölçülür; gerçek Worker hesabı için bu seçeneği kullan. Önceki işlerin sonuçları varsa Python API'sindeki `additional_context` ile ayrıca dahil edilmelidir. Modelin üretim, akıl yürütme, araç ve yeniden deneme tokenleri bu çevrimdışı ölçümde bulunmaz.

## Kendi sisteminde kullan

```python
from oz import Atom, Codebook, Macro
from oz_compiler import compile_messages

book = Codebook([Macro('V', (Atom('r', 0), Atom('a', 0), Atom('t', 30)))], vectors=True)
# Channel(..., codebook=book): bütün hedefler ve 30 numaralı prosedür tanımlanmalı.

# Her counter tam bir metin alıp hedef tokenizer'ın token sayısını döndürür.
result = compile_messages(channel, messages, counters=[target_token_counter])
new_channel = result.channel
receiver_input = result.packet.text
# result.messages içindeki frame'leri new_channel.binding ile aktar.
```

Kaynak kodu yalnız standart kütüphane ister; CLI ölçümü için isteğe bağlı tiktoken kullanılır. Diğer modeller için kendi gerçek token sayacını verebilirsin. İnsanların işaretleri ezberlemesi gerekmez: `oz decode` kesin açılımı verir.

```powershell
oz decode --channel examples/oz3-channel.json "V[1:16]"
oz pack --channel .oz-runtime/derlenmis/channel.json --messages .oz-runtime/derlenmis/messages.json --worker
oz init .oz-runtime/oz3-ekip --channel .oz-runtime/derlenmis/channel.json
```

`oz init` kuyruğu oluşturur; derlenen mesajları kendiliğinden kuyruğa eklemez. `oz send FRAME --id ID --workspace .oz-runtime/oz3-ekip` ile gönderilir. Frame yalnız ÖZ/3 sözleşmesini bilen alıcıya verilir; model için gereken dilbilgisi `prompt.txt`/`render()` girdisine dahildir.

## Uyumluluk ve ölçüm

ÖZ/1–2 kanallarının mevcut bağlam hash'leri değişmez. ÖZ/3 desteği manifestte `vectors: true` ile açılır ve bağlam hash'ine dahil edilir. Derleyici kazanç bulursa revizyonu bir artıran yeni kanal üretir. Gönderici ve alıcı aynı yeni manifesti kullanmalıdır. Eski kuyruk ve bekleyen işler otomatik taşınmaz; eski kanalla tamamlanır. Farklı revizyonlar arasındaki iş bağımlılıkları otomatik kurulmaz.

[Ölçüm raporu](reports/OZ3-RESULTS.md): tekrarlı dört mesajlık örnekte, sözlük ve Worker cevap biçimi dahil **1.133 → 899** ve **1.127 → 894** girdi tokeni. Yaklaşık **%20,7** azalma. Aynı örnekte zaten elle tanımlanmış bir ÖZ/2 makrosu varsa ilave kazanç yaklaşık **%2,4**. Tek küçük istekte ve yeni serbest metinde kazanç yok; biçim korunuyor.

Bu sürüm için gerçek modellerle anlamayı ve görevi tamamlama kalitesini ölçen yeni bir pilot yapılmadı. Önceki ÖZ/2 pilotu yeni vektör sözdizimini doğrulamaz. Otomatik testler kodlayıcı/çözücü eşitliğini, sıra ve veri korumasını, maliyet seçimini ve taşınabilirliği doğrular.
