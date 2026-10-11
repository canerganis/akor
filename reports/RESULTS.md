# AKOR 0.1.0 — ölçüm ve doğrulama

Tarih: 11 Ekim 2026. Çalıştırılan ortam: Windows, Python 3.12, tiktoken 0.14.0. Bunlar sentetik metin token sayımlarıdır; canlı modellerin iletişim kalitesi veya üretim maliyeti ölçülmedi.

## Sonuç

İki örnekte ve iki tokenizer'da AKOR mesajları, eşdeğer kısa JSON nesnelerinden **%25,89–32,02**, JSON dizilerinden **%10,89–13,57** daha az metin tokeni kullandı. Dil talimatı ve gerekli bağlam her alıcı çağrısına eklendiğinde giriş metnindeki tasarruf JSON nesnelerine karşı **%4,70–5,57**, JSON dizilerine karşı **%3,19–3,76** oldu.

Bu fark, kısaltılmış mesajın toplam görevin maliyetine eşit olmadığını gösterir. Daha az tekrar ve hedefli aktarımın katkısı da iş yüküne bağlıdır. Bu küçük deneyden büyük veya sağlayıcılar arasında evrensel bir tasarruf yüzdesi çıkarılamaz.

## Aynı içeriği taşıyan altı mesajın tokenleri

| Tokenizer | Örnek | AKOR | JSON nesnesi | JSON dizisi |
|---|---|---:|---:|---:|
| o200k_base | İngilizce kod | 175 | 253 | 199 |
| o200k_base | Türkçe malzeme verisi | 211 | 289 | 237 |
| cl100k_base | İngilizce kod | 172 | 253 | 199 |
| cl100k_base | Türkçe malzeme verisi | 229 | 309 | 257 |

Bu tablo yalnız ajan mesaj metnini sayar. Gönderici, alıcı, görev, revizyon, içerik ve referans alanları tüm biçimlerde aynıdır. JSON nesnesinde alan adları, JSON dizisinde aynı alanların sabit sırası kullanılır. Doğal dil içeriği yalnız AKOR lehine kısaltılmadı.

## Dil talimatı ve bağlam dahil altı alıcı çağrısı

| Tokenizer | Örnek | AKOR | JSON nesnesi | JSON dizisi | AKOR / nesne tasarrufu |
|---|---|---:|---:|---:|---:|
| o200k_base | İngilizce kod | 3224 | 3414 | 3350 | %5,57 |
| o200k_base | Türkçe malzeme verisi | 3291 | 3464 | 3410 | %4,99 |
| cl100k_base | İngilizce kod | 3221 | 3407 | 3341 | %5,46 |
| cl100k_base | Türkçe malzeme verisi | 3427 | 3596 | 3540 | %4,70 |

Her teslimat ayrı, belleksiz bir model çağrısı gibi sayıldı. AKOR'un 416 tokenlik dil talimatı her seferinde yeniden dahil edildi. Görev referansları, gerekli kaynak tanımları ve incelemenin hedef mesajı mevcut. JSON karşılaştırmaları da aynı anlam kurallarını, referansları ve yalnız yeni mesajları gönderme davranışını kullanıyor.

Aynı alıcıya ait işlenmiş mesajları tekrar ekleyen ayrı karşılaştırmada yalnız yeni mesajları göndermek AKOR giriş metnini **%6,18–8,05** azaltıyor. Bu özellikle verimsiz bir karşılaştırma koşuludur; ana JSON karşılaştırmasının yerine geçmez.

API mesaj sarmalayıcıları, araç şemaları, düşünme tokenleri, cevap üretimi, başarısız çağrılar, yeniden denemeler, fiyatlar ve önbellek indirimleri bu tablolarda yok. İlk tablo ile ikinci tablo ayrı hesap görünümleridir; toplanıp toplam API tüketimi diye sunulamaz. Gerçek tokenizasyon, sağlayıcının model ve mesaj biçimine göre değişebilir. Ölçüm aracı: [tiktoken](https://github.com/openai/tiktoken).

## Doğrulama

- **31 otomatik test geçti.** Unicode, alıntı ve satır sonu korunması; bozuk girdiler; zorunlu kanıt referansları; adresleme; eksik/değişmiş referanslar; tekrar mesajlar; ACK sınırları; eski revizyonlar; bütçe aşımı; inceleme hedefi ve bağlam sıfırlanması kapsandı.
- Altı mesajlık sentetik demo tamamlandı.
- Paket proje içindeki sanal ortama kuruldu; proje klasörü dışından kurulu `akor` komutu ve import kontrol edildi.
- Canlı modeller, farklı sağlayıcılar ve farklı işletim sistemleriyle çalışma **test edilmedi**.
- Testler referansın varlığını ve protokol kurallarını doğrular; referansın bilimsel doğruluğunu, doğal dilin anlamını veya gerçek test yürütmesini doğrulamaz.

Ham sayımlar ve örnek/talimat özeti: [token-counts.json](token-counts.json). Yeniden üretim: `python benchmark.py --output reports/token-counts.json`; önce `requirements-benchmark.txt` içindeki isteğe bağlı bağımlılığı kur.

## Canlı pilot için devam notu

Bir sonraki aşama, seçilecek iki veya daha fazla gerçek model için adaptör ekleyip aynı saklı görev setini kısa düz yazı, JSON ve AKOR ile çalıştırmaktır. Başarı oranı ve kısıtların korunması düşmeden; toplam sağlayıcı tüketimi, düzeltme turları ve gecikme birlikte değerlendirilmelidir. Mevcut sürüm buna hazır bir protokol ve yerel aktarıcı sunar; canlı çoklu model uyumluluğu iddiası taşımaz.
