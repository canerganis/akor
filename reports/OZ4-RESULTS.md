# ÖZ/4 doğrulaması — 11 Ekim 2026

Paket 0.6.0; tiktoken 0.14.0; `o200k_base` ve `cl100k_base` birlikte seçiciye verilmiştir. Çalıştırma: `python -X utf8 oz4_benchmark.py`. [Ham sayımlar ve süreler](oz4-token-counts.json).

**Gerçek model çağrısı: 0. Gerçek kod değişikliği/test yürütmesi: 0.** Bu rapor, sentetik kod inceleme isteklerinin kayıpsız taşınmasını ve girdi maliyetini ölçer. Kod ajanlarının görev başarısını ölçmez.

## Yeni dil birimi

`^`, kanala bağlanmış programın aynısını istemek anlamına gelir. Örnekteki 48 ilkel işlem isteğini her iki tokenizer'da **1 komut tokeni** taşır. Base'in, sözlüğün ve kaynakların tanımı bu tek tokene dahil değildir. Tam paket ölçümlerinde hepsi ayrıca sayılır.

## Güçlü karşılaştırma

Başlangıçta ÖZ/3 makroları vardır. Derleyici önce mutlak gösterimi mevcut makrolar, yeni makrolar, hedef listeleri, kısa metin, JSON ve uygun olduğunda ortak frame tablosuyla iyileştirir. Sonra ÖZ/4 ortak program + fark gösterimini dener. İki tokenizer'da da maliyet artışı kabul edilmez.

Ek kontrol, tam aynı frame'leri bir kez tanımlayan açık bir şablon tablosudur. Bu basit yöntem tekrarlı mesajlarda güçlüdür; ÖZ/4'ün yalnız tekrarların üzerinden büyük başarı iddia etmesini önler. Üretim seçicisine de eklenmiştir. Her mesajın kimliği ve ayrı sonuç yükümlülüğü korunur.

| İş yükü | En iyi mutlak/tablo, o200k → ÖZ/4 seçimi | En iyi mutlak/tablo, cl100k → ÖZ/4 seçimi |
|---|---:|---:|
| Tek küçük okuma | 189 → 189 | 188 → 188 |
| Tek 48 adımlı plan | 846 → 846 | 844 → 844 |
| 8 farklı 48 adımlı plan | 1.150 → 1.140 | 1.141 → 1.129 |
| 32 farklı 48 adımlı plan | 2.200 → 1.739 | 2.168 → 1.705 |
| 64 farklı 48 adımlı plan | **3.351 → 2.300** | **3.289 → 2.236** |
| Aynı planın 64 kopyası, kontrol | 1.239 → 1.239 | 1.238 → 1.238 |
| Yeni serbest metin | 194 → 194 | 193 → 193 |

64 farklı plan için ek tasarruf **%31,36 / %32,02**. Planlar aynı sırayı büyük ölçüde paylaşır; test prosedürü ve başka bir okuma adımı farklılaşır. Toplam 3.072 işlem isteği vardır; bunlar gerçekleştirilmiş 3.072 iş değildir. Bütün 64 planın ayrı olduğu veri üretiminde doğrulanır. Bu yapı, fark dilinin uygun olduğu bir iş yüküdür; rastgele ve tamamen bağımsız görevlerde aynı kazanç beklenmemelidir.

Aynı planın 64 kopyası kontrolünde ÖZ/4 seçilmedi; **daha ucuz ortak tablo** seçildi. Gösterilen son maliyet, biçimi zorlamayan seçicinin sonucudur. Küçük mesajlarda da Base tanımı maliyetini çıkarmadığı için eski biçim korunur.

## Maliyet kapsamı

Her pakette gereken tam Base, dilbilgisi, makro tanımları, kaynakların tam metni, görev kimlikleri ve Worker cevap sözleşmesi sayılır. Kaynak/şema önbelleğinin model tarafında ücretsiz olduğu varsayılmaz. Sağlayıcı taşıyıcı alanları, gönderici eğitimi/ilk sözlüğü, model üretim/akıl yürütme tokenleri, araç çıktıları ve yeniden denemeler dahil değildir. Dolayısıyla bu rakamlar toplam API faturası veya uçtan uca hız kazancı olarak kullanılamaz.

## Yerel süreler ve testler

64 plan için sözlük/makro araştırması bu çalıştırmada onlarca saniye sürdü; kesin süre ham JSON'dadır. Bu hazırlığı her mesajda yeniden yapmak hızlı bir iletişim yolu oluşturmaz. Aynı kaynak ve sözlük revizyonunda derlenmiş kanalın yeniden kullanılması amaçlanır.

Derlenmiş kanalla 64 frame'in tam yeniden paketlenmesi üç çalıştırmanın medyanında yaklaşık **774 ms**, yalnız kesin çözümleme yaklaşık **2,94 ms** sürdü. Paketleme, her adayın tokenini saymayı ve tam bağlamı oluşturmayı da içerir. Bunlar bu makineye ait küçük yerel zamanlamalardır; ağ/model gecikmesi veya önceki sürüme karşı kontrollü hızlanma ölçümü değildir.

**179 birim/entegrasyon testi geçti.** Yeni kapsam: 250 rastgele düzenleme dizisinin kayıpsız açılımı; özgün koordinatlar; eşzamanlı referans takası; literal/kanıt/başarı bildirimlerinin düzenlemelere sokulamaması; 64 işlem/16 düzenleme sınırı; bozuk/eski bağlam reddi; SQLite yeniden açılışı; eşdeğer mesajların aynı kimlikle ayıklanması; Worker üzerinden bağımlı işlere gerçek sonuç metninin aktarılması. Test adaptörü açıkça sentetik alındı bildirimi üretir.

ÖZ/4 için canlı modellerde anlama, gerçek kodlama başarısı, sonuç kalitesi veya uçtan uca toplam maliyet ölçülmedi. Dünya çapında benzersizlik, mükemmel orkestra veya küresel en az token garantisi yoktur.
