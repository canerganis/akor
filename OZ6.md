# ÖZ/6 — iki yönlü kısa iletişim

ÖZ/5 ortak iş akışını ve parametreleri sıkıştırır. ÖZ/6 buna **kısa cevap biçimini** ekler: ajan, her sonuçta görev kimliğini ve aynı durum kodunu tekrar yazmadan cevap verebilir. Tam sonuç metni, hata ayrıntıları ve belirsizlik korunur. Paket sürümü 0.8.0.

## Cevabın yapısı

Güvenilir adaptörün o teslim için bildiği görev sırası `["incele", "test", "oner"]` olsun:

```json
{"q":"0123456789abcdef","s":0,"v":["İnceleme sonucu","Test sonucu","Öneri metni"]}
```

`q`, o çağrıya ait 16 küçük hexadecimal karakterlik cevap kimliğidir; model, istemde verilen değeri aynen döndürür. `v` dizisindeki konumlar teslim sırasına bağlanır. `s:0`, **bütün sonuçlar için açıkça 0 durumunun bildirildiği** anlamına gelir. Alanın eksik olması başarı değildir.

Durumlar farklıysa:

```json
{"q":"0123456789abcdef","s":[0,1,2],"v":["İnceleme sonucu","Geçici hata nedeni","Kalıcı hata nedeni"]}
```

Durum kodları değişmez: `0` tamamlandı bildirimi, `1` yeniden denenebilir hata, `2` kalıcı hata. Her görev için bir boş olmayan sonuç gerekir. `s` listesi kullanılırsa uzunluğu da görev sayısıyla tam eşleşir. Boolean, bilinmeyen durum, eksik/fazla sonuç veya yanlış `q` bütün cevabı geçersiz yapar. Geçersiz cevap bağımlı görevleri açmaz.

Bu bir sonucun doğruluğunu ispatlamaz. Ajanın “tamamlandı” bildirimi ile gerçek test/kanıt doğrulaması ayrı kalır. Bir model iki sonuç metninin yerini değiştirip doğru sayıda değer döndürürse yalnız biçim denetimi bunu anlayamaz; anlam denetimi ayrıca gerekir. `q` çağrılar arası yanlış cevap eşleşmesini yakalar; kimlik doğrulama imzası değildir.

## Aktarım

```powershell
oz plan --workspace .oz-runtime/ekip --reply-mode lanes --show-prompt
oz run --workspace .oz-runtime/ekip --adapter adapter.json --reply-mode lanes
```

`lanes` açıkça seçilir. Mevcut `rows` davranışı varsayılandır; eski adaptörler sessizce yeni sözleşmeye geçirilmez. `lanes` isteği `oz.adapter/2`, `receipt`, sıralı `ids`, `prompt` ve ölçülen girdi tokenlerini taşır. Adaptör modele `prompt` metnini iletmeli, modelin kısa JSON cevabını ayrıştırıp döndürmelidir. İsteğe bağlı sağlayıcı `usage` bilgisi önceki sözleşmeyle aynı biçimde eklenebilir.

Her çağrı/yeniden deneme yeni `q` üretir. Gerçek `q` ve cevap dilbilgisi **işleri kuyruktan almadan önce girdi bütçesine dahil edilir**. Sonradan ücretsiz metin eklenmez. `plan` önizlemesi ve `run` farklı cevap kimlikleri kullanır; gerçek çalıştırma yeniden ölçülür. Yalnız geçici hata alan görevler tekrar denenir, tamamlanan kardeş görevler tekrar gönderilmez.

Python:

```python
worker = Worker(inbox, channel, adapter, counters=counters, reply_mode="lanes")
result = worker.run_once()
```

`oz_reply.validate_lanes(reply, delivered_ids, receipt)` doğrulanmış cevabı eski `results` satırlarına dönüştürür. `encode_lanes` ters dönüşümü yapar. Adaptör eski uzun cevabı modelden aldıktan sonra kısaltırsa **modelin çıktı tokenlerinden tasarruf edilmez**; bunun için model kısa biçimi doğrudan üretmelidir.

`oz compile --worker` hâlâ varsayılan satırlı cevap sözleşmesini ölçer. `lanes` kullanımının gerçek girdi bütçesi `plan/run --reply-mode lanes` veya `reply_contract(receipt)` ile ayrıca ölçülmelidir. Tek işte yeni sözleşme ve cevap kimliği toplam maliyeti artırabilir; yalnız gövde kısalığına bakılmamalıdır.

## Ölçüm kapsamı

Toplam verim **başarılı iş başına bütün çağrıların maliyetiyle** değerlendirilir: girdi, çıktı, araçlar ve yeniden denemeler birlikte izlenir. Sağlayıcı düşünme tokenlerini çıktı içinde, önbellek tokenlerini girdi içinde bildiriyorsa bunlar ikinci kez toplanmaz. Yerel sözlük ölçümleri tek başına canlı maliyet/hızlanma değildir. CLI sistem ve araç bağlamı, protokol metninden çok daha büyük olabilir.

Bu sürümün yerel ve canlı doğrulamalarını Luna alt ajanları yürütür. Sonuçlar ayrı raporlanır: [cevap biçimi](reports/OZ-REPLY-RESULTS.md), [ÖZ/5 anlama](reports/OZ5-LIVE-LANGUAGE.md), [kod düzeltme pilotu](reports/OZ5-LIVE-CODING.md). Başarısız/eksik denemeler ve sıkı çıktı sözleşmesine uyum, anlam eşdeğerliğinden ayrı tutulur.
