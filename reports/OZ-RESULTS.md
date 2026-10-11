# ÖZ/1 doğrulama ve maliyet sonuçları

11 Ekim 2026. Windows, Python 3.12, tiktoken 0.14.0. Paket sürümü 0.2.0.

## Çalışan sonuç

ÖZ/1 ayrıştırıcısı, tipli referans kontrolü, kanal parmak izi, kısa gösterim seçimi, alıcı girdi seçimi ve host olaylarına ayırma yolu hazırdır. Önceki AKOR/1 çekirdeğiyle birlikte **54 otomatik test geçti**.

Canlı pilotta Codex CLI 12 sentetik talimatı ÖZ mesajlarına çevirdi. Bu mesajlar değiştirilmeden Claude CLI'a gönderildi. Kodlama **12/12**, bağımsız çözümleme **12/12** doğru çıktı. Kesin sayılar, referanslar, çıkarım/gözlem ayrımı, test başarısı/başarısızlığı, bitiş ve açık metin örneği sınandı. Sonuç bir dilbilgisi/anlam sınıflandırma denemesidir; gerçek yazılım görevinde verim artışı veya genel model güvenilirliği kanıtı değildir.

## Mesaj boyutu

| Mesaj | Anlamı | o200k_base | cl100k_base |
|---|---|---:|---:|
| `a` | Aktif yamada tanımlı inceleme işlemi | 1 | 1 |
| `?3` | Kaynak 3'ü iste | 2 | 2 |
| `+8.` | Test raporu 8 başarılı; adım tamam | 3 | 3 |
| `~10` | Hipotez 10 bir çıkarım | 2 | 2 |
| `!11` | Neden 11 ile engellendi | 2 | 2 |

11 örneklik ayrı token fikstüründe ÖZ mesaj gövdeleri toplam **34 token**, bütün anlam kurallarını açıkça yazan İngilizce karşılıkları **154 token** tuttu: yalnız bu mesaj gövdelerinde **%77,9 azalma**. Bu karşılaştırma en iyi insan kısaltmasına karşı yapılmadı. Sözlük, kaynak tanımları, sistem istemi ve araçlar bu yüzdeye dahil değildir. Gerçek CLI denemesinin 12 örneği ile bu 11 örneklik token fikstürü farklı ölçümlerdir.

Sözlük/gramer tek başına **261–262 token** tuttu. Sözlüğün gerektiği kısa alıcı girdilerinin tamamında açık metin daha ucuz çıktı ve otomatik seçici onu seçti. Yeni bir sayısal bilgi için kullanılan `:` çıkışı açık metne bir token ekleyebildi; seçici bu maliyeti de gizlemez.

Bir tek girdi içinde 16 inceleme isteği birleştirildiğinde, gereken dar sözlük ve gramer dahil sembolik metin **154–155 token**, açık karşılıklar **272 token** tuttu. Bu, aynı çağrıdaki toplu gösterim ölçümüdür; farklı API çağrılarında ortak bağlamın ücretsiz olduğu anlamına gelmez. Kaynak ve görev bağlamı bu özel amortisman tablosunda sabit, hariçtir.

## Token üretmeyen host yolu

`?`, `+`, `-`, `!`, `.`, `/` mesajları doğrulandıktan sonra doğrudan host olayına dönüşebilir. Yalnız durum kaydı, kaynak isteğini kuyruğa alma veya bitiş bildirimi için ikinci bir model çağrısı zorunlu değildir. Bu durumda alıcıya ait ek çıkarım çağrısı yapılmaz. Yeni karar veya iş gerektiğinde host modeli çağırmaya devam eder. Göndericinin harcadığı tokenlar ve kanıtın üretilme maliyeti sıfır sayılmaz.

Bu mekanizma bir öneri döndürür; bitişi, test doğruluğunu veya araç yetkisini otomatik onaylamaz. Gerçek bir orkestratördeki toplam çağrı azalması henüz ölçülmedi.

## Gerçek CLI kullanımının gösterdiği sınır

Codex çağrısının raporlanan girdisi **26.257 token** (bunun 7.296'sı cached input alanında), çıktısı **110 token** oldu. Reasoning output alanı ayrıca 56 gösterdi. Bunları belirsiz sağlayıcı alanlarını iki kez sayacak şekilde toplamadık. Araç çalıştırma olayı görülmedi.

Claude çağrısı girişte 2 normal token ve **9.489 cache-creation token**, çıktıda **392 token** raporladı; düşünme ayrıntı alanı 166 idi. Model kullanım kaydı `claude-opus-5-5` gösterdi. Codex model adı sonuç akışından doğrulanmadığı için raporda yalnız yapılandırılmış CLI varsayılanı olarak bırakıldı.

Duvar süreleri yaklaşık 12,5 ve 10,8 saniye idi; modeller, istemler ve sistem yükleri farklı olduğundan bunlar hızlanma karşılaştırması değildir. CLI sistem/araç/eklenti başlangıç bağlamı kısa mesajlardan çok daha büyük olabilir. Bu yüzden %77,9 mesaj küçülmesini toplam CLI maliyeti tasarrufu olarak sunmuyoruz.

## Yeniden üretim ve sonraki değerlendirme

Token sayımı: `python oz_benchmark.py`. Canlı pilot: `python oz_live_eval.py --live`. Testler: `python -m unittest discover -s tests -v`.

Ham çıktılar: [oz-token-counts.json](oz-token-counts.json), [oz-live.json](oz-live.json). Pilot cevapları otomatik olarak beklenen işlem/referans dizileriyle karşılaştırıldı; başarısız örneklere gizli onarım yapılmadı.

Bir sonraki ölçüm, gerçek orkestrasyon görevlerinde aynı modellerle ÖZ, kısa doğal dil ve JSON yollarını karşılaştırmalıdır. Eşit görev başarısı, kaynak doğruluğu ve kısıt korunumu altında toplam girdi/çıktı/düşünme tokenleri, düzeltme turları ve duvar süresi belirleyicidir. Bu ilk sürüm bir evrensel en küçük dil veya garantili hızlanma iddiası taşımaz.
