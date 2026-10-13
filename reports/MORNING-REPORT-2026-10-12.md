# Sabah raporu, 12 Ekim 2026

Branch `oz-0.9`, son commit `3f07723`. Push yok, main'e merge yok. 198 test yeşil.

## Kısa sonuç

32 ve 64 işlik çağrılarda hedef tuttu. Sonnet ile canlı ölçümde ÖZ/9, aynı işi yapan 0.8'e göre toplam tokeni **%43 (32 iş)** ve **%55 (64 iş)** azalttı. Bütün işler doğrulayıcıdan geçti (96/96 ve 192/192), cevaplar daha hızlı geldi (64 işte medyan 9,2 sn, 0.8'de 14,0 sn).

1 ile 4 işlik çağrılarda kazanç yok. Claude CLI her çağrıya kendi 905 tokenlık sabit yükünü ekliyor; bu yük küçük çağrıda baskın. 16 işte toplam %29, CLI yükü hariç %41 azalma var.

## Gece ne oldu

1. **Çevrimdışı hedef tuttu ama canlıda tutmadı.** İstek paketi o200k ile 1 işte %38, 64 işte %55 küçülmüştü. İlk canlı Sonnet testinde ise toplam token 0.8'den %9 fazla çıktı, çağrılar da yavaştı. İki sebep vardı. Birincisi, sıkıştırılmış cevap sözleşmesini Sonnet yanlış anladı: 8 cevabın 5'i geçersizdi. İkincisi, model "read" işlerinde referans metnini kelimesi kelimesine tekrar yazıyordu.
2. **Karşılaştırma adil değildi.** 0.8 paketi 16 işte hiç iş yapmadı, sadece kodları geri kopyaladı. Bu yüzden 16 işteki eski karşılaştırma geçersizdi.
3. **Astra gerçek bir test seti tasarladı.** İçinde malzeme aralık hesabı ve kod onarımı var, beklenen sonuçlar deterministik olarak kontrol ediliyor. İşi gerçekten yapan bir 0.8 kolu da ekledi. Bunu harness olarak kurdum.
4. **Cevap formatı değişti.** Sonuçlar artık doğal JSON değerleri ve hatalar ayrı bir haritada. Bu formatla geçerli cevap oranı 13/18'den 36/36'ya çıktı. Receipt artık pakette yok, host tarafında kalıyor.
5. **Batch'leme eklendi.** Astra'nın birinci önceliği batch'lemeydi: `oz run --min-batch N --max-wait S`. Varsayılan kapalı.
6. **Spec ve belgeler güncellendi.** Astra OZ9.md'yi kodla birebir uyumlu olacak şekilde yeniden yazdı. README ve USAGE 0.9'a göre güncellendi.

## Canlı ölçümler (Sonnet, `claude -p`, araçsız)

Aynı işi yapan 0.8 kolu ile karşılaştırma. "Toplam", CLI'ın 905 tokenlık sabit yükünü de içerir.

| Ölçüm | Doğru iş | Toplam token | CLI yükü hariç | Medyan süre |
|---|---:|---:|---:|---:|
| Karışık 1/4/16 iş, 18 çağrı | 124/126 (0.8: 123) | %17 az | %30 az | 3,1 sn (0.8: 3,1) |
| 16 farklı iş | 0.8 ile benzer | %29 az | %41 az | benzer |
| 32 farklı iş | 96/96 | **%43 az** | %52 az | 7,0 sn (0.8: 7,9) |
| 64 farklı iş | 192/192 | **%55 az** | %61 az | 9,2 sn (0.8: 14,0) |

Ölçülüp reddedilen öneriler:
- **Astra'nın çıktı kuralı:** isteğe 18 token ekliyordu, canlıda çıktıyı azaltmadı.
- **Kısaltılmış cevap sözleşmeleri:** ya daha uzun çıktılar (36'ya karşı 35 token) ya da canlıda daha çok geçersiz cevap üretti.
- **Astra'nın "e" işi netleştirmesi:** yeni metin bütün kollarda, 0.8 dahil, boş cevaba yol açtı.

Ayrıntılar: [OZ9.md](../OZ9.md) bölüm 10 ve `reports/OZ9-LIVE-*.txt`.

## Kendi kararlarım

- **Güvenlik ifadesi:** Astra'nın birleştirdiği başlıkta "no tool permissions" yoktu. Kendi kuralına dayanarak geri ekledim, Astra da onayladı.
- **Receipt:** 16 karakterlik rastgele receipt yerine kısa bir sayaç kullandım. Rastgele receipt hem istekte hem cevapta yaklaşık 7'şer token tutuyordu. Sonra receipt tamamen pakette yer almaz hale geldi.
- **Test yazımı:** Luna'nın yazdığı OZ/9 testlerinden 22'si hatalıydı, düzelttim. Senin talimatınla sonraki testleri Sonnet alt ajanlarına yazdırdım, hepsini inceleyip kendim çalıştırdım.
- **Ölçüm hatam:** Ölçümlerde sabit ve ucuz bir receipt kullanmıştım, bu yüzden ilk tablolar maliyeti olduğundan biraz düşük gösterdi. Hatayı buldum ve düzelttim.

## Senin kararın gereken konular

1. **Varsayılan batch.** Ölçümler büyük çağrıları açıkça destekliyor. `--min-batch` şu an varsayılan olarak kapalı (1) ve batch üst sınırı 16. Varsayılanı 32 yapmak ve quorum'u açık getirmek istiyor musun? Bunun bedeli bekleme süresi.
2. **cl100k ve diğer modeller.** Spec'teki release gate, cl100k ile canlı ölçüm ve başka modellerde doğrulama istiyor. cl100k OpenAI tokenizer'ı; bunu ölçmek için bir GPT modeli gerekiyor. Luna'ya iş vermememi söylemiştin. Hangi model kullanılsın, yoksa bu adım atlansın mı?
3. **Merge.** `oz-0.9` main'e alınmaya hazır mı? Ben merge etmedim, push da yapmadım.

## Kota

Claude haftalık %90, Codex haftalık %33. Handoff gerekmedi.
