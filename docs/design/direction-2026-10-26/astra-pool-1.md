**Değiştirerek kabul.** Tek iş akışında resume/retry üstünlüğünü kovalamayı bırakalım. Ajanlar arası havuzlama doğru sonraki deney; fakat “tek ajan bunu yapamaz” fazla güçlü: sıradan bir ortak kuyruğun da yapabildiği şey. AKOR’un katkısını ayırmalıyız.

**Üç kol gerekli:**

- **D:** Her üretici kendi işlerini tek direct çağrıda gönderir; çağrılar eşzamanlı.
- **P:** Basit ortak kuyruk, aynı işleri tek direct çağrıda toplar.
- **A:** Aynı kuyruk politikasıyla mevcut OZ/1g.

D→P havuzlama kazancını, P→A AKOR’un ek etkisini gösterir. A yalnız D’yi geçerse sonuç yine değerlidir; iddia **“havuzlamayı otomatikleştirmenin ölçülmüş faydası”** olur.

**İş yükü:** [Mevcut BoolQ üreticisi](../../../bench/ozmap/data.py:314). Oracle, veri kümesindeki gold etiketler; değerlendirme yolu [score.py](../../../bench/ozmap/score.py:91). Dosyanın SHA256’sını doğruladım. Etiketler modele gitmez. Eski aritmetik/dönüşüm işleri bu deneyin ana kanıtı olmasın: yetkin direct runner bunları zaten kodla çözebilir.

**Kalan sekiz çağrı için:** K=8 bütçeye sığmaz; yalnız D+A bile dokuz çağrı. **4 üretici × 8 farklı soru = 32 iş** seçelim: D=4, P=1, A=1; iki çağrı hata/retry rezervi. Bu tek tur bir ön elemedir, genel üstünlük kanıtı değildir.

**Önerdiğim geçiş koşulları:**

- İş dağılımı, geliş zamanları, azami bekleme, model/effort ve retry politikası önceden dondurulsun. P ve A aynı bilgiyi alsın; sorular birbirinden bağımsız olsun.
- Eksik/yanlış yönlendirilmiş sonuç sıfır; A’nın gold doğruluğu D ve P’den düşük olmasın.
- A, D’ye karşı **toplam tokenı en az %20 düşürsün**; maliyet artmasın. Başarısız çağrılar, cache ve reasoning dahil; reasoning output içinde ikinci kez sayılmasın.
- Süre, işin gelişinden doğrulanmış teslimine kadar ölçülsün: bekleme ve doğrulama dahil. Makespan ve en kötü üretici gecikmesi D’nin **1,10 katını aşmasın**. Geçerse verimlilik adayı; hız üstünlüğü ancak gerçekten daha hızlıysa.
- P aynı kazancı sağlıyorsa AKOR’a özgü verimlilik iddiası yok.

Ayrıca **~3,7k sabit framing** şimdilik yaklaşık çıkarım: farklı tokenizer sayımıyla provider usage farkı, tek başına sabit overhead ölçümü değildir.


