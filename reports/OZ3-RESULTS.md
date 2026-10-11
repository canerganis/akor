# ÖZ/3 ölçümü — 11 Ekim 2026

Paket 0.5.0; tiktoken 0.14.0. Çalıştırma: `python -X utf8 oz3_benchmark.py`. [Ham sonuçlar](oz3-token-counts.json). Sentetik yerel ölçüm; **gerçek model çağrısı ve araç yürütmesi 0**.

## Komut maliyeti

`VN=rNaNt30` sözlüğü altında `V[1:16]`, 48 ilkel işlem isteğine açılır. İki tokenizer'da da **6 komut tokeni**. Aynı açık işlem dizisi 96 token: yalnız komut gövdesinde **%93,75** azalma. Bu karşılaştırma sözlük, bağlam, mesaj kimlikleri ve cevap biçimini dışarıda bırakır; toplam API tasarrufu değildir.

## Tam alıcı girdisi

Bütün gerekli kaynak metinleri, dilbilgisi, kullanılan makro tanımları, mesaj kimlikleri ve Worker JSON cevap sözleşmesi dahildir. Başlangıç, aynı bağlamdaki eski ÖZ/2 seçicisinin kısa metin, JSON ve ÖZ adayları arasındaki sonucudur; yalnız uzun bir doğal dil açıklamasıyla karşılaştırılmamıştır. Derleyici iki tokenizer'ı aynı anda kullanmıştır.

| Sentetik iş yükü | o200k önce → sonra | cl100k önce → sonra |
|---|---:|---:|
| Tek okuma | 182 → 182 | 181 → 181 |
| 16 hedefe okuma | 707 → 707 | 704 → 704 |
| Önceden tanımlı makro, 4 × 48 işlem | 921 → 899 | 916 → 894 |
| Sözlüksüz başlayan tekrar, 4 × 48 işlem | 1.133 → 899 | 1.127 → 894 |
| Düzensiz sırada 30 işlem | 610 → 608 | 607 → 606 |
| Yeni serbest metin | 192 → 192 | 192 → 192 |

Sözlüksüz başlayan tekrarlı işte tasarruf **%20,65 / %20,67**. Zaten iyi bir elle tanımlanmış makro varsa ek tasarruf **%2,39 / %2,40**. Bu ayrım, mevcut iyi bir sözlüğe karşı kazancı olduğundan büyük göstermemek için önemlidir.

Aynı 4 × 48 işlem örneğinde kısa metin 3.180 / 3.178, kompakt JSON 1.655 / 1.652 token. ÖZ/3 sonucu 899 / 894. Bu iki zayıf olmayan alternatif de aynı işlem kurallarını ve kaynakları taşır; modellerin görev başarı eşitliği ölçülmemiştir.

Derleme dışında tutulan iki mesajda, yeni sözlüğün kullanılmayan makroları girdiye eklenmedi: maliyet **304 → 304 / 302 → 302**. Bu küçük kontrol, tüm gelecek iş yükleri için genelleme kanıtı değildir.

## Doğrulama ve sınırlar

- 161 birim/entegrasyon testi geçti. ÖZ/3 için 18 test; 180 rastgele sıralı iş dizisinin her birinde en fazla 16 kodlama adayının ilkel açılımı doğrulandı.
- Sıra, tekrarlar, referans türleri, belirsizlik/sayı/birim içeren kaynaklar ve CRLF dahil yeni metinler korunuyor. Kanıt veya tamamlanma bildirimleri makrolara alınmıyor.
- Hatalı aralıklar, eksik hedefler, uyumsuz türler, eski bağlam kimliği ve 64 işlemi aşan açılımlar reddediliyor.
- ÖZ/2 örneğinin 0.4.0'dan alınan bağlam hash'i aynı kaldı; SQLite yeniden açılışı ve CLI'nin taşınabilir çıktı paketi test edildi.
- Derleyici sınırlı ve açgözlü arama yapar. Makro sıralaması tahminidir; kabul kararı tam girdi token sayımına dayanır. Küresel minimum garantisi yoktur.
- Yerel derleme süreleri ham raporda tek çalıştırma olarak bulunur; model gecikmesi veya karşılaştırmalı hızlanma sayılmaz.
- Göndericinin sözlük öğrenme maliyeti, üretim/akıl yürütme tokenleri, araç çıktıları, yeniden denemeler, taşıyıcı sağlayıcı alanları ve canlı görev başarısı ölçülmedi.
- ÖZ/3 için yeni canlı model anlama testi yapılmadı. Eski ÖZ/2 canlı pilotu vektörleri kapsamıyordu.
