# ÖZ/5 Luna canlı dil anlama deneyi

Model seçimi: `gpt-6-luna`. Çağrı sayısı: 12; her şekil için iki bağımsız tekrar ve aynı modelle eşleştirilmiş açık ilkel JSON kontrolü.

Her çağrı ayrı ephemeral CLI oturumunda, read-only sandbox ve izole geçici çalışma dizininde yürütüldü. Girdiler sentetiktir; skor beklentileri istemlere eklenmedi. Bu deneyde araç kullanımı sıfırdır. Araç kullanan bir çağrı olsaydı, iki vakası da ana paydada uygunsuz başarısızlık sayılacaktı.

## Sonuçlar

| Şekil | Mod | Strict doğru / toplam | Semantik doğru / toplam | Durum | Süre (s) | Araç |
|---|---|---:|---:|---|---:|---:|
| simple_form #1 | oz5 | 1/2 | 2/2 | scored | 10.953 | 0 |
| simple_form #1 | primitive_json | 2/2 | 2/2 | scored | 9.25 | 0 |
| regular_matrix #1 | oz5 | 1/2 | 2/2 | scored | 7.156 | 0 |
| regular_matrix #1 | primitive_json | 1/2 | 2/2 | scored | 7.891 | 0 |
| mixed_matrix #1 | oz5 | 1/2 | 1/2 | scored | 7.734 | 0 |
| mixed_matrix #1 | primitive_json | 1/2 | 2/2 | scored | 8.329 | 0 |
| simple_form #2 | oz5 | 1/2 | 2/2 | scored | 24.218 | 0 |
| simple_form #2 | primitive_json | 2/2 | 2/2 | scored | 13.36 | 0 |
| regular_matrix #2 | oz5 | 1/2 | 1/2 | scored | 7.672 | 0 |
| regular_matrix #2 | primitive_json | 1/2 | 2/2 | scored | 10.375 | 0 |
| mixed_matrix #2 | oz5 | 1/2 | 1/2 | scored | 8.015 | 0 |
| mixed_matrix #2 | primitive_json | 2/2 | 2/2 | scored | 8.219 | 0 |

| Mod | Çağrı | Vaka paydası | Strict doğru | Semantik doğru | Geçerli yanlış ret | Geçersiz kabul |
|---|---:|---:|---:|---:|---:|---:|
| oz5 | 6 | 12 | 6 | 9 | 3 | 0 |
| primitive_json | 6 | 12 | 9 | 12 | 0 | 0 |

## Usage ve ölçüm sınırları

| Alan | Provider usage |
|---|---:|
| input_tokens | 298917 |
| cached_input_tokens | 104704 |
| output_tokens | 2893 |
| reasoning_output_tokens | 1691 |

Strict yanıt sözleşmesi, `op` alanında açıklayıcı `read/inspect/request_test/propose` adlarını ve JSON alan yapısını birebir ister. Semantik eşdeğerlik ayrıca yalnız bilinen `r/a/t/>` sembollerini bu adlara normalize ederek primitive sırası, referansları ve ID'leri exact karşılaştırır. Prompt, op alanında sembol mü açıklayıcı ad mı gerektiğini açıkça sabitlemedi; bu belirsizlik ilk cohort için korunmuştur.

Her modun vaka paydasına tamamlanmayan, malformed, timeout ve araç kullanılan çağrıların iki vakası da eklendi. `case_categories` doğru ret, invalid kabulü, geçerli işi yanlış ret, alias-only yanıt ve ilkel çözümleme hatalarını ayırır; `call_categories` araç kullanımını ve süreç hatalarını ayrıca sayar.

Yerel `o200k_base` prompt-token tahmini toplamı: 4482. Bu, provider input/cache token alanlarından ayrı tutulur. Wall time her süreç için yerel uçtan uca CLI süresidir; provider model süresi olarak yorumlanmaz.

ÖZ/5 ve ilkel kontrol sonuçları bağımsız sentetik şekil anlama davranışını ölçer. Gerçek kodlama, güvenilir araç kullanımı, doğruluk genellemesi veya üretim başarısı ölçümü değildir. Ham cevaplar, fixture/prompt SHA-256 değerleri ve ham provider usage event'leri JSON raporundadır.

## Dil iyileştirme önerisi

Promptta `op` alanının yalnız açıklayıcı ad mı yoksa wire sembolü mü taşıyacağı açıkça sabitlenmeli. Matris dilbilgisine geçerli bir karışık örnek (`(31,31)*2,33,32`) ve aynı boyutta geçersiz sütun örneği eklenmeli; bir vakadaki hata diğer bağımsız vakaları geçersiz kılmamalı. Bu deneyde Luna bütün bozuk girdileri doğru reddetti; üç ÖZ/5 geçerli matris vakasını da yanlışlıkla reddetti.
