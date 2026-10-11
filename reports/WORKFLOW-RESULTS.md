# ÖZ 0.4.0 — kullanım ve aktarım doğrulaması

11 Ekim 2026. Windows, Python 3.12, tiktoken 0.14.0. [Tekrar üretilebilir senaryo](../oz_workflow_eval.py), [ham sonuç](oz-workflow.json).

## Otomatik denetimler

**143 test geçti.** Önceki 99 test korunuyor. Yeni kapsam:

- Bütçeye göre otomatik bölme; büyük işin küçük işleri engellememesi; planlamanın deneme hakkı tüketmemesi.
- Cevap sözleşmesi ve öncül sonuçlarının bütçeye dahil edilmesi; paylaşılan öncülün bir kez aktarılması.
- Başarılı/geçici/kalıcı sonuçların ayrı işlenmesi; kısmi veya hatalı cevabın yanlış ACK üretmemesi.
- Gecikmeli tekrar, açıkça yeniden açma, eski cevabı reddetme ve farklı çalışanların aynı işi almaması.
- SQLite v1'den v2'ye mevcut sonuç korunarak geçiş; yeniden açılış; geçmiş ve durum sayfalaması.
- Gerçek stdin/stdout süreçleri, zaman aşımı, hatalı JSON, shell karakterlerinin veri olarak kalması ve Windows'ta UTF-8.
- CLI çalışma alanı, kaynak dosyasından kanal, CRLF/Unicode korunumu, mevcut dosyanın üzerine yazmama ve güvenli hata kodları.

## Uçtan uca çevrimdışı deneme

20 bağımsız iş, bunlara bağlı bir inceleme işi, bir host olayı ve bilerek büyük tutulmuş bağımsız bir mesaj eklendi. Gerçek `o200k_base` tokenizer kullanıldı. Standart JSON stdin/stdout adaptörü gerçek yerel Python süreçleriyle çalıştı; sonuçları sentetik alındı kayıtlarıdır.

| Kontrol | Sonuç |
|---|---|
| Çalışan ajanın girdi bütçesi | Paket başına 350 token |
| 20 iş için gönderilen paket | 3 |
| Geçici hata verilen `m3` | 2 teslim denemesi |
| Diğer 19 iş | Her biri 1 teslim denemesi |
| Büyük bağımsız mesaj | Tam metni korundu; 0 deneme; bekliyor |
| İnceleme ajanı | 20 işin tamamını bekledi, sonuçlarını aldı |
| İnceleme girdi bütçesi | Önceki 20 sonuç dahil 2.048 token |
| Host olayı | Yalnız kaydedildi; model çağrısı yok |
| Kuyruk yeniden açıldığında | Sonuçlar ve deneme sayıları korundu |
| Gerçek model çağrısı | **0** |
| Yerel adaptör süreci çağrısı | 4 |

Son durumda 22 kayıt tamamlandı, bilerek bütçeden büyük olan 1 kayıt bekliyor. Bunlar demo alındı kayıtlarıdır; alan görevlerinin gerçekten yapıldığı veya doğrulandığı iddia edilmez.

0.4.0 yerel sanal ortama paket olarak kuruldu. Repo dışından `site-packages` modülleriyle `oz demo`, `oz status` ve `oz inspect` çalıştırıldı. Bırakılan örnek çalışma alanı `.oz-runtime/demo-0.4` içinde; dört demo kaydı tamamlandı. Bu küçük demoda çalışan girdi 231, inceleyen girdi 267 token ölçüldü; model çağrısı yapılmadı.

## Kapsam sınırı

Bu sürümün doğrulaması kullanım akışı, bütçe ve aktarım tutarlılığı üzerinedir. Yeni bir model kalitesi, uçtan uca API maliyeti veya model hızlanması denemesi değildir. 0.3.0'ın 20/20 Codex–Claude dil denemesi ve token tabloları [ayrı raporda](OZ2-RESULTS.md) tarihli kanıt olarak durur.

Worker'ın çıktı biçimi talimatı ve önceki ajan sonuçları alıcı girdi sayımına eklenir. Adaptörün kendi sistem istemi, araç şemaları, düşünme/çıktı tokenleri ve sağlayıcı ücret hesabı bunun dışındadır. Stdio sonucu sentetik olduğundan rapora uydurma sağlayıcı kullanım sayısı yazılmadı.

Yeniden üretim:

```powershell
python -m unittest discover -s tests -v
python -X utf8 oz_workflow_eval.py
oz demo .oz-runtime/yeni-demo
```

İlk iki komut test/ölçüm yapar. Son komut yeni, boş bir demo klasörü oluşturur. Tokenizer kurulu olmalı; model anahtarı gerekmez.
