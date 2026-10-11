# ÖZ/2 — 0.3.0 doğrulama raporu

11 Ekim 2026. Windows, Python 3.12, tiktoken 0.14.0. [Ham token ölçümleri](oz2-token-counts.json), [canlı cevaplar ve kullanım](oz2-live.json).

## İşlevsel doğrulama

**99 otomatik test geçti.** Önceki 54 test korunuyor. Yeni denetimler: makro açılımı, 250 rastgele yasal dizinin kayıpsız gidiş-dönüşü, kanıt/başarı gizleyen makroları reddetme, parmak izi, bütçe sınırı, Unicode/literal kaçırma, tokenizer önbelleği, kalıcı yeniden açma, farklı ajan bağımlılığı, lease yenileme/sona erme, eski cevabı reddetme, eksik ACK'yi atomik reddetme ve iki eşzamanlı bağlantının aynı işi almaması.

Yerel demo iki işi birlikte teslim etti, inceleme ajanını bunların ACK'sine kadar bekletti ve durum mesajını host yolunda kaydetti. Demo araç çalıştırmadı; sonuçları sentetik alındı kayıtlarıdır.

0.3.0 paketi proje sanal ortamına kuruldu. Repo dışından yüklü modüllerin import edilmesi, `oz decode`, iki tokenizer ile `oz pack` ve yetersiz bütçede çıkış kodu 2 doğrulandı. Doküman bağlantıları ve Git boşluk kontrolü geçti.

## Canlı dil anlama denemesi

Codex CLI 20 sentetik talimatı ÖZ/2'ye çevirdi: **20/20** anlam ağacı doğru. Tam bu mesajlar Claude CLI'a iletildi; temel işlemlere açarak çözümleme **20/20** doğru. Başarı işlem sırası, referans kimliği ve literal metnin tam eşitliğiyle sayıldı. Gizli onarım yapılmadı.

Eski atomlar, parametreli/sabit makro, makro birleşimi, test sonucuyla bitiş, başarısızlık ile engel, `not_run` kaydını okuma ve işaret/satır sonu içeren literal sınandı. Bu bir sözdizimi/anlam smoke testidir; gerçek görev kalitesi, görülmemiş büyük sözlük veya uzun konuşma başarı oranı değildir.

Codex kaydı 26.533 input, bunun ayrıntısında 7.296 cached input, 218 output ve ayrıca 123 reasoning output bildirdi. Model adı akışta doğrulanmadığından yapılandırılmış varsayılan olarak kaydedildi. Araç olayı görülmedi.

Claude kaydı 2 normal input, 3.948 cache creation, 5.721 cache read ve 1.164 output bildirdi; düşünme ayrıntısı 605 idi. Model kimliği `claude-opus-5-5`. Birbirini kapsayabilecek output/düşünme alanları toplanmadı. Duvar süreleri yaklaşık 15,1 ve 15,3 saniye; farklı süreç/istemler olduğu için hız kıyaslaması değildir. CLI başlangıç bağlamı mesaj dilinden büyük kalıyor; aşağıdaki yüzdeler toplam CLI/API maliyetine uygulanamaz.

## Bağlam dahil toplu aktarım

Altı sentetik alan: kod, malzeme ölçümü, veri kalitesi, çeviri, destek ve planlama. Her alanda 8 bağımsız iş ve 4 host olayı var. Toplam 72 mesaj, 48 iş. Gerçek kuyruk üzerinden yeniden oynatılarak 6 iş paketi ve 24 host olayı hazırlandı; **bu çevrimdışı ölçümde model çağrısı sıfır**.

Her gösterim aynı görevi, kaynakları, işlem sırasını ve mesaj ID'lerini taşıdı. Sözlük, alan tanımları ve gerekli bağlam her alıcı girdisinde sayıldı. Adaylar: açık metin, kısa metin, işlem sözleşmeli kompakt JSON, makrolu ÖZ, temel ÖZ; kaynak nesne/dizi biçimleriyle ölçüldü.

| 48 iş mesajı | o200k_base | cl100k_base |
|---|---:|---:|
| Ayrı ayrı, her girdide en ucuz aday | 7.334 | 7.330 |
| 6 toplu girdi, her girdide en ucuz aday | **2.049** | **2.041** |
| Azalma | **%72,1** | **%72,2** |

Kazançta ortak bağlam tekrarını kaldırmak belirleyici. Sekiz mesajlık bu paketlerde kompakt JSON seçildi; alfabenin her koşulda daha ucuz olduğu sonucu çıkarılmadı.

## Aynı paket, farklı gösterimler

Malzeme senaryosundaki sekiz mesajlık karma desen farklı ID'lerle 64 mesaja genişletildi. Sentetik tekrar, sözlük maliyetinin paylaşıldığı durumu sınar; gerçek iş yükünü temsil ettiği varsayılmaz.

| 64 mesajın tüm alıcı girdisi | o200k_base | cl100k_base |
|---|---:|---:|
| Kısa metin | 1.791 | 1.790 |
| Kompakt JSON | 1.250 | 1.248 |
| ÖZ/2 | **814** | **760** |
| Kısa metne göre azalma | **%54,6** | **%57,5** |
| JSON'a göre azalma | **%34,9** | **%39,1** |

Tüm sayılarda sözlük ve görev bağlamı var. Küçük paketlerde bunların maliyeti baskın; 16 mesajda temel ÖZ, 32/64 mesajda makrolu ÖZ seçilebiliyor. Eşik fikstüre/tokenizer'a özgüdür.

48 işin yalnız tel gövdesi tam açık referanslı temel ÖZ'de 228 token, optimize edilmiş makrolarla 126 token: **%44,7** azalma. Bu son oran sözlük/bağlamı içermez; doğal dil veya toplam maliyet karşılaştırması değildir.

## Yerel kodlayıcı maliyeti

Yirmi tekrarlı okuma atomunda önceki 0.2.0 araması 4.096 yazımı sayıyordu; yeni varsayılan en fazla 256 adayı sayar ve byte bakımından en kısa yolu da kapsar. Isındırma sonrası üç koşunun medyanında eski arama yaklaşık 18–25 ms, yeni arama 1,3–1,4 ms ölçüldü. Ayrıntı ham raporda.

Bu küçük mikrobenchmark ağ, model düşünmesi, iş süresi veya tokenizer başlangıcını içermez. Sınırlı arama farklı mesajda daha iyi yazımı kaçırabilir; evrensel minimum veya genel ajan hızlanması sonucu değildir.

## Sınırlar ve yeniden üretim

Çekirdek sayıları, birimleri, belirsizliği ve kaynak alanlarını korur; iddianın doğruluğunu kanıtlamaz. Host olayını modelsiz kaydetmek yeni kararın da modelsiz yapılabileceği anlamına gelmez. Tekrarlanan dış etkiler için adaptör idempotency'si gerekir.

Girdi sayımları gönderici başlangıç talimatını, model çıktı/düşünmesini, araç sarmalayıcılarını ve sağlayıcı ücret politikasını içermez. İki tokenizer bütün modellerin güncel tokenizer'ı değildir. Gerçek görevlerde aynı modellerle eşit başarı, düzeltme turu, toplam kullanım ve gecikme karşılaştırması henüz yapılmadı.

```powershell
python -m unittest discover -s tests -v
python -X utf8 -m examples.oz2_demo
python -X utf8 oz2_benchmark.py
python -X utf8 oz_live_eval.py --suite oz2 --live
```

Token ölçümü için `tiktoken==0.14.0` gerekir. Son komut gerçek mevcut CLI hesaplarını kullanır. Önceki [ÖZ/1 raporu](OZ-RESULTS.md) 0.2.0 sürümünün tarihli ölçümüdür.
