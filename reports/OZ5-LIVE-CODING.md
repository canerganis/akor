# ÖZ/5 canlı kodlama pilotu

## Sonuç

Aynı `gpt-6-luna` modeliyle açık JSON ve OZ/5 kompakt aktarım biçimlerinde 5 sentetik Python bugfix görevi karşılaştırıldı. Her biçimde 5 fixture ve 2 tekrar olmak üzere payda **10 hücre/koşul, toplam 20 hücre**; 12 canlı model çağrısı yapıldı. Model yanıtları yalnızca kod önerisiydi; üretim dosyaları değişmedi. Model araç/test çalıştırmadı. Kabul edilen aday fonksiyonları yerel değerlendirici, sabit gizli testlerle kontrollü alt süreçte çalıştırdı.

Bu kısa pilot OZ/5'in kod doğruluğuna etkisi hakkında genel sonuç vermez. Gözlenen tam geçişler explicit JSON'da 1/10, kompakt aktarımda 3/10 hücreydi. Değerlendirilebilen adayların test sonuçları sırasıyla 13/14 ve 19/19 doğruydu. Bunlar farklı paydalarla ölçüldüğü için doğrudan tek başına başarı oranı gibi okunmamalı: kalan hücrelerde aday kaynak açık AST/call kısıtlarını karşılamadı ve gizli testlere gönderilmedi.

## Sabitlenen görevler ve hücre sonuçları

| Fixture | Explicit r1 | Explicit r2 | OZ/5 r1 | OZ/5 r2 |
|---|---|---|---|---|
| `range-clamp` | 7/7 | 6/7 | 7/7 | 7/7 |
| `merge-adjacent` | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti |
| `strict-retry-after` | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti |
| `chunk-boundaries` | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | 5/5 | kaynak kısıtını ihlal etti |
| `stable-unique` | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti | kaynak kısıtını ihlal etti |

Her canlı çağrıda çıktı JSON şemasına ve batch yanıtlarında ID sırasına uydu (6/6 çağrı/koşul). Ancak ortak talimatlardaki “tek `function_source` nesnesi döndür” ifadesi batch talimatındaki `results` dizisiyle çelişiyordu. Bu nedenle batch sonuçlarını temiz bir format tercihi ölçümü olarak yorumlamıyorum. Gizli test paydası, elenmiş hücreleri de içeren her koşul için 66 sabit assertion'dır; yalnız AST ve kaynak imzası kontrolünden geçen hücreler yürütüldü.

Fixture'lar aralık sınırlarını kırpma, bitişik kapalı aralıkları birleştirme, katı `Retry-After` girişi, chunk sınırları ve hashlenemeyen değerlerle kararlı tekilleştirmeyi kapsadı. Her fixture için promptta aynı bozuk fonksiyon, davranış gereksinimleri ve kamuya açık kontrol örnekleri vardı. Gizli testler modele gönderilmedi. Önceden dondurulmuş beş bilinen-doğru çözümün tümü gizli testleri geçti; beş buggy başlangıç fonksiyonunun tümü en az bir testi kaybetti.

## Kaynak ve scorer değerlendirmesi

Çıktılar `proposal only` sözleşmesiyle istendi; hiçbir kod uygulanmadı. Adaylar yalnız tek fonksiyon, değişmeyen tam public imza ve sınırlı Python AST allowlist'iyle skorlandı. Import, attribute erişimi (`.append`/`.sort` dahil), I/O ve izin verilmeyen çağrılar elendi. JSON duplicate key ve nonfinite değerleri reddedildi; batch ID dizisinin eksik, fazla veya sırası değişmiş olması reddedilecek şekilde kontrol edildi. Araç kullanan yanıtlar gizli testlere alınmayacaktı; 12 çağrının hiçbirinde araç olayı yoktu.

İlk scorer `ast.keyword`/lambda söz dizimini kapsamıyordu. İlk dört çağrının ham cevapları korunup V1 gözlem skoru ayrıca tutuldu; aynı cevaplar yeniden istenmedi. Son scorer izin verilen built-in anahtar sözcük/lambda biçimlerini ve güvenli `ValueError` raise kullanımını kapsıyor. İkinci düzeltme, `Raise` söz diziminin güvenli ve makul Python olduğunu doğrulayan precheck sonrasında yapıldı; `.append` gibi promptta açıkça yasaklanan attribute kullanımları yine reddedildi. Bu yüzden OZ/5 chunk r1 yanıtı final scorer'da 5/5 geçti; öncesindeki `rejected_ast:Raise` sonucu evaluator kapsam kusuruydu, model başarısızlığı sayılmamalı. Eski ve yeni skorlar her çağrı kaydında ayrı duruyor.

Adaylar AST kontrolü sonrasında izole çalışma klasöründe, `-I -S`, kısıtlı builtins ve 3 saniyelik alt süreç zaman aşımıyla değerlendirildi. Bu kontrollü test harness'idir; güvenlik sandbox'ı iddiası değildir. Hidden test yürütümü yerelde yapılmıştır; model hiçbir aracı çağırmamıştır.

## Maliyet ve süre

| Ölçüm | Explicit JSON | OZ/5 kompakt |
|---|---:|---:|
| Canlı çağrı / hücre | 6 / 10 | 6 / 10 |
| Sağlayıcı kullanım kayıtları | 6 | 6 |
| Sağlayıcı input token | 150,792 | 152,727 |
| Cached input token | 125,440 | 124,416 |
| Output / reasoning token | 3,418 / 1,883 | 3,692 / 2,137 |
| Prompt tokenizer tahmini (o200k / cl100k) | 3,559 / 3,526 | 5,478 / 5,456 |
| Bilinen CLI wall-time ortalaması | 15.0 sn (4/6 çağrı) | 14.2 sn (4/6 çağrı) |

Sağlayıcı kullanım toplamları her çağrının saklanan tüm usage kayıtlarını toplar; her coding çağrısında bir kayıt vardı. Readiness çağrısı ayrı tutuldu. Tokenizer tahminleri prompt metinlerinden hesaplandı ve sağlayıcı kullanımından/billing'den ayrı gösterildi. Bu pilotta OZ/5 promptları tokenizer tahmininde explicit JSON'dan yaklaşık %54 daha uzundu; context, dictionary ve grammar başlıkları ek yük getirdi. Sağlayıcı input değerleri yerel CLI'nin oturum maliyetlerini de kapsayabileceğinden prompt boyutuyla bire bir eşitlenemez.

İlk dört kurtarılan çağrıda güvenilir `wall_seconds` kaydı yoktu; kalan 8 çağrıda süre yerel CLI başlatma ve oturum ömrünü de içeriyor. Bunlar model-only latency değildir. Model erişimi aynı oturumda `gpt-6-luna` açıkça seçilerek ve ayrı readiness çağrısında doğrulandı; readiness 0 araç olayı kullandı. CLI mevcut kullanıcı ayarındaki tanınmayan bir alanı yok saydığı, unstable-feature bildirimi verdiği ve bir hook timeout değerini kırptığı uyarılarını yazdı; ayar veya kimlik doğrulama yapılandırması değiştirilmedi.

## Tekrar üretim ve sınırlar

Tam ham model cevapları, event/usage kayıtları, prompt metinleri, SHA-256 değerleri ve deterministik skorlar JSON raporunda ve `.oz-eval/luna-coding/` altında saklandı. `reports/oz5-live-coding.json` her 20 hücreyi ve her çağrıyı içerir. `oz5_live_coding.py --rescore-report` aynı kaydedilmiş cevapları yeniden puanlar ve model çağrısı yapmaz. Kontroller: precheck (known-good/buggy, codec roundtrip ve parser koşulları), `py_compile`, CLI `--help` ve scorer ile sabit gizli fixture testleri.

Beş küçük sentetik fixture ve iki kısa tekrar; genellenebilir model yeteneği, production güvenilirliği veya gerçek repository değişikliğinde kalite ölçümü değildir. Batch talimat çelişkisi, oturumdan gelen usage overhead'i ve az sayıda örnek çıkarımları sınırlar.
