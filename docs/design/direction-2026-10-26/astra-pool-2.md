**Değiştirerek kabul.** Ölçülen kazanç pooling’den geliyor; runtime’ın ek değeri henüz karşılaştırmalı olarak kanıtlanmadı. **P tam PASS değil:** ikinci koşuda P=27/32, D=28/32; “doğruluk düşmeyecek” koşulu sağlanmıyor. A’nın doğruluk farkının reasoning’den kaynaklandığı da henüz hipotez.

- **Build:** Yeni `akor_pool.py`; frozen dosyalara dokunma. Varsayılan, mevcut P sistem metni/isteği/JSON yanıtı olsun. Yalnız aynı model, effort, talimat, doğrulayıcı ve veri erişim sınırındaki hazır işler birleşsin. FIFO, en fazla **32 iş**, en eski hazır işten itibaren **500 ms bekleme**; dolulukta veya süre sonunda gönder. Deadline beklemeye izin vermiyorsa hemen gönder; uçuş hâlindeki paket yeni işleri bekletmesin. Eksik/fazla/yinelenen ID ve yanlış tip reddedilsin; sessiz onarım olmasın. İş doğrulayıcısı varsa teslimden önce çalışsın; şema kabulü anlamsal doğruluk diye sunulmasın. OZ/1g açıkça seçilen **deneysel mod** kalsın; henüz “daha doğru mod” demeyelim.

- **Deney ve bütçe:** D, her üreticinin sekiz işini gelişinde doğrudan göndersin; P yukarıdaki kuyruğu kullansın. Dört üreticinin gelişleri burst için **0/100/300/450 ms**, seyrek trafik için **0/2/5/9 s** olsun. Her profil iki kez, kol sırası ters çevrilerek ve yeni, önceden sabitlenmiş sorularla: **26 çağrı**. Ardından aynı yeni 32 soruda **P-default / P-high / A-default**, ters sırayla iki koşu: **6 çağrı**. P-high, aynı pooling ve plain promptla doğrudan high-effort çağrıdır; format hipotezi için doğru kontrol budur. **Toplam 32 planlı + en fazla 4 retry = 36 çağrı; 250 bin toplam token sert tavanı.** Çağrı başına en fazla bir retry; hepsi hesaba dahil. Claude kotası **%95’e ulaşınca dur**; doğrulanamayan kota veya eksik usage ile devam etme.

- **Geçiş ölçütü:** Her eşlenmiş koşuda tüm işler teslim edilmiş, usage eksiksiz ve **P doğruluğu ≥ D** olmalı. Burst: token oranı **≤0,80**; seyrek: **≤1,05**. İkisinde de makespan ve en kötü üreticinin **kendi gelişinden doğrulanmış teslimine kadar** gecikme oranı **≤1,10**. Bekleme/doğrulama/retry sürelerini dahil et. Geçmezse deneysel kalır; sonuçtan sonra eşiği gevşetmeyiz. P-high, A’nın doğruluğunu iki koşuda da yakalayıp token ve gecikmede aşmıyorsa, OZ’ye özgü doğruluk gerekçesi desteklenmez.

**README için imzam:**

> In two runs on the same 32-question BoolQ sample, plain cross-producer pooling used 38% fewer total tokens than four concurrent producer calls, with 1–8% longer makespan and 27/32 correct versus 26–28/32. The savings were largely explained by avoided per-call input overhead; these results do not establish a compact-wire advantage or performance under staggered arrivals.



