# ÖZ/5 Luna canlı dil anlama deneyi — düzeltilmiş kohort

Model: `gpt-6-luna`. Düzeltilmiş kohortta 12 çağrı var; ÖZ/5 ve ilkel JSON kontrolü aynı cohort düzeninde karşılaştırıldı, iki bağımsız tekrar kullanıldı. Geçersiz girdilerin zorlukları eşlenmedi.

Scorer revizyonu: 2. Raw model yanıtları değiştirilmeden strict JSON parser ile yeniden puanlandı; geçerli primitive frame'ler `Channel.validate` ile denetlendi ve JSON eşitliği tür duyarlı canonical biçimde yapıldı.

Önceki hatalı kohort ayrı arşivde `invalidated=true` olarak işaretlidir; eski 12+12 vaka paydası bu yeni paydaya eklenmedi. Önceki rapordaki üç ret model hatası değildi: iki karışık matrisin her biri 6 değer/4 ID açıyordu, ikinci düzenli matris ise 2 değer/3 ID veriyordu. Tüm iyi/kötü girdiler canlı çağrıdan önce gerçek `Channel.accept`, `decode_matrix` veya `Channel.validate` ile kontrol edildi; bütün 24 codec preflight denetimi beklenen sonucu verdi. Hiçbir promptta valid/invalid verdict alanı yoktu.

## Sonuçlar

| Şekil | Mod | Strict doğru / vaka paydası | Semantik doğru / vaka paydası | Doğru ret | Geçerli yanlış ret | Geçersiz kabul | Süre (s) | Araç |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| simple_form #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 8.516 | 0 |
| simple_form #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.0 | 0 |
| regular_matrix #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 11.469 | 0 |
| regular_matrix #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.687 | 0 |
| mixed_matrix #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 10.563 | 0 |
| mixed_matrix #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.875 | 0 |
| simple_form #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 7.734 | 0 |
| simple_form #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.344 | 0 |
| regular_matrix #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 7.859 | 0 |
| regular_matrix #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 10.328 | 0 |
| mixed_matrix #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 24.297 | 0 |
| mixed_matrix #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 13.25 | 0 |

oz5: strict 12/12, semantik 12/12; kategoriler {"correct_rejection": 6, "exact_success": 6}.

primitive_json: strict 12/12, semantik 12/12; kategoriler {"correct_rejection": 6, "exact_success": 6}.

Strict skor açıklayıcı enum değerlerini (`read`, `audit`, `test`, `propose`) ve exact ID/frame/atom sırasını ister. Semantik skor ayrıca bilinen wire sembollerini (`r`, `a`, `t`, `>`) aynı primitive adlarına normalize eder; referanslar ve sıralar yine exact olmalıdır.

Geçersiz örnekler eşlenmiş zorlukta değildir: OZ/5 tarafında eksik Form slotu, sütun uzunluğu hatası veya sıfır ref; primitive kontrolde her seferinde eksik/null zorunlu ref kullanıldı. Bu nedenle 12/12 sonuçlar yalnız bu sentetik vakalarda her biçimin codec sözleşmesine uyduğunu gösterir; eşdeğer güçlük, üstünlük veya parity göstermez.

## Token ve süre

| Usage alanı | Provider toplamı |
|---|---:|
| input_tokens | 302552 |
| cached_input_tokens | 194560 |
| output_tokens | 2770 |
| reasoning_output_tokens | 1198 |

Yerel `o200k_base` prompt tahmini: 7676 token; provider input/cached/output/reasoning alanlarından ayrıdır. Süreler her CLI sürecinin yerel wall time değeridir.

Kapsam sentetik protokol anlama ve codec eşdeğerliğidir. Gerçek kodlama, araç yürütmesi, fiziksel doğrulama veya üretim başarısı ölçülmedi. Ham cevaplar ve prompt/fixture hashleri JSON raporundadır.

## Dil iyileştirme

Üretim `FORM_GRAMMAR` ve `WEAVE_GRAMMAR` aynen gönderildi; cevap enumu çağrıdan önce sabitlendi. Matrisin bağımsız ID sırası ve her sütunun tam olarak ID sayısı kadar açılması kritik kural. Bir adet valid/invalid mixed örneği ekleyerek bu sınırları öğretmek sonraki prompt sürümünde denenebilir.
