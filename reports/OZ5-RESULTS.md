# ÖZ/5 ölçüm raporu

Tarih: **11 Ekim 2026**. Paket 0.7.0; `tiktoken 0.14.0`, `o200k_base` ve `cl100k_base`. Kaynak: [oz5-token-counts.json](oz5-token-counts.json). Tekrarlama: `python -X utf8 oz5_benchmark.py`.

Ölçüm çevrimdışıdır: **0 model çağrısı, 0 gerçek kod/test yürütmesi**. Tam alıcı girdisi sayılır: işlem sözlüğü, kullanılan Form/Base ve dilbilgisi, gerekli kaynak metinleri, görev kimlikleri ve Worker cevap sözleşmesi. Provider mesaj zarfı, göndericinin ilk eğitimi/bağlamı, model çıktısı/düşünmesi, araç sonuçları ve yeniden denemeler bu sayılara dahil değildir.

## Karşılaştırma

Karşılaştırma aynı veride optimize edilmiş ÖZ/4'tür: dört yeni makroya kadar sınırlı arama, hedef listeleri, ortak Base araması, aynı-frame tablosu ve metin/JSON seçenekleri. Yalnız uzun doğal dil veya makrosuz bir zayıf karşılaştırma kullanılmadı. Yeni Form ve matris ancak seçilen tokenizer'ların hiçbirinde toplam maliyeti artırmıyorsa kabul edilir.

| İş yükü | o200k: ÖZ/4 → ÖZ/5 | cl100k: ÖZ/4 → ÖZ/5 | Ek azalma |
|---|---:|---:|---:|
| Tek okuma | 188 → 188 | 187 → 187 | %0 |
| 8 farklı düzenli görev | 1.252 → 1.252 | 1.243 → 1.243 | %0 |
| 32 farklı düzenli görev | 1.901 → 1.412 | 1.870 → 1.409 | %24,7–25,7 |
| 64 farklı düzenli görev | 2.743 → **1.524** | 2.680 → **1.521** | **%43,3–44,4** |
| Aynı 64 görev, karışık sıra | 2.743 → 2.314 | 2.680 → 2.311 | %13,8–15,6 |
| 64 rastgele parametreli görev | 2.745 → 2.456 | 2.692 → 2.453 | %8,9–10,5 |
| Makrolara uygun 64 görev | 1.875 → 1.524 | 1.810 → 1.521 | %16,0–18,7 |
| Aynı planın 64 kopyası | 857 → 857 | 855 → 855 | %0; eski tablo |
| Önceki ÖZ/4: 64 farklı fark planı | 2.300 → **1.930** | 2.236 → **1.927** | **%13,8–16,1** |
| Yeni literal bilgi | 192 → 192 | 191 → 191 | %0 |

Düzenli örnekler dört modülün okuma, inceleme ve test isteklerini taşır; her görev 16 ilkel istek içerir. Parametre örüntüleri bilerek tekrarlanabilir üretilmiştir; bu nedenle kazanç düzensiz görevler için genellenemez. Aynı kimlik ve anlamlar korunarak sıra karıştırılan kontrol ile bağımsız rastgele referans/prosedür seçilen kontrol ayrıca raporlandı. Kodlayıcı işlerin sırasını değiştirmez.

Önceki ÖZ/4 veri kümesi değiştirilmeden karşılaştırıldı: her biri 48 istek içeren 64 farklı plan. Bu veride Form ve Base aynı kanalda bulunabilir; pakette yalnız kullanılan dilbilgisi ücretlendirilir. Matris seçildiğinde Base kullanılmıyorsa metne eklenmez.

## Yerel süre ve doğruluk

64 düzenli görev için ölçüm sırasında beş tekrarın ortancası yaklaşık **0,36 saniye tam paketleme**, **1 milisaniye doğrudan Form doldurma** ve **1 milisaniye matrisi 64 bağımsız frame'e açma** oldu. Bunlar yerel Python süreleridir. Doğrudan doldurma tokenizer/aday araması ve ağ/model süresini içermez. Güncel ham süreler JSON raporundadır; donanım/yükle değişebilir.

Tam derleme sözlük araştırmasını da içerir ve bu veri kümesinde yaklaşık 8 saniye, eski ÖZ/4 örneğinde yaklaşık 22 saniye sürdü. Hazır kanalı iletişim sırasında yeniden kullanmak gerekir. Her mesajda yeniden derleme yapmak hız avantajını silebilir. `--max-macros 0` yeni makro aramasını atlar; bu örnekte aynı nihai matris maliyetini verir.

Bütün derlenen örnekler özgün ilkel işlem dizisine tam açıldı. Ayrı 17 mesajlık görülmemiş girdi kontrolü yeni parametre değerleri ve Form'a uymayan bir işlem dizisi içerir; hepsi kayıpsız açıldı, uygun eski biçim seçildi. Bu, kodlayıcı doğruluğudur; bir modelin sıkıştırılmış girdiyi doğru anladığına dair sonuç değildir.

**202 test geçti.** 250 rastgele Form bağlaması, 113 farklı sütun örneği, hatalı/taşan açılımlar, eski manifest uyumu, CLI dışa/içe aktarımı, görev kimliği ve bağımlı sonuç aktarımı kapsamda. Bazı birim testleri maliyet seçim davranışı için karakter sayacı kullanır; yukarıdaki token sayıları yalnız gerçek tokenizer ölçümleridir.

Sütun kodlama, sözlük ve şablon paylaşımı bilinen tekniklerdir. Bu uygulama için dünya çapında benzersizlik, küresel token minimumu, canlı model hızlanması veya gerçek kodlama verimi iddiası yoktur. Daha güçlü sonuç için aynı gerçek kodlama görevlerinde başarı, yanlış çözümleme, toplam token ve uçtan uca süre birlikte ölçülmelidir.
