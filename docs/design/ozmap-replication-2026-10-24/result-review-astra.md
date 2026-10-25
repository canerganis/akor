OK — “Verdict”: **“Invalid. Every gate and both magnitude checks are invalid”** scorer raporuyla aynıdır. A4.14.1, araç yürütülüp yürütülmediğinin belirsiz olduğu hücreyi `interrupted` değil `invalid` sayar; bütün kapıların invalid olması scorer’ın raporladığı kapsamdır, A4.14.1 tek başına her yerel bulgunun bütün kapıları geçersiz kılacağını söylemez.

OK — “Verdict”: **“no backend claim, no rule learning claim, no pooling claim and no cross backend headline is permitted”** scorer’ın bütün claim bayraklarıyla ve A4.10’un koşullarıyla uyumludur. Betimleyici ölçüm ve A4.8 kapsamındaki yakınsama gözlemi yine raporlanabilir.

OK — “Verdict”: **“Safety passed: no accepted rule answer was wrong (safety kill false)”** raporlanan safety-kill sonucuyla uyumludur; yalnız kabul edilmiş kural yanıtlarının güvenlik ölçütünü ifade eder.

CHANGE — “Verdict”: **“The single validity failure is leakage”** yerine “Tek invalidating bulgu türü leakage; aynı hücrede dört bulgu var” yazın. BoolQ A’nın eksik sonuçları ve doğrulanmamış kullanımının da ayrıca bulunduğunu koruyun.

CHANGE — “Verdict”: **“The cause … is network transport, not tool use”**, reconnect sayıları, fallback kaydı ve **“SIGNED_TRANSPORT_NOTICES = []”** verilen bağımsız kanıtlarda yoktur. Scorer dört leakage bulgusunu ve hücrenin invalid olduğunu doğruluyor; taşıma olaylarının tek neden olduğunu veya araç kullanılmadığını doğrulamıyor. Bu ayrıntıları doğrulanmamış yazar aktarımı olarak belirtin; `uncertain` sonucunu kesin araç-kullanılmadı hükmüne çevirmeyin.

OK — “Verdict”, materials kapı tablosu: Codex **0.8371 / 0.4758 / 1.2470 / 3.6391**, Sonnet **1.1989 / 0.9951 / 0.9172 / 2.3825** scorer’dan doğru aktarılmıştır. Doğruluk eşitliği, **0.75 / 0.5 / 0.9** eşikleri ve cold makespan’in kapı olmaması A4.10’la uyumludur.

CHANGE — “Verdict”: **“no materials gate would pass either”** tek tek ölçütler için yanlıştır: iki backend doğruluğu koruyor, Codex warm token ölçütünü karşılıyor. “Hiçbir backend birleşik materials başarı koşullarını karşılamıyor” şeklinde daraltın.

BLOCKER — “Verdict”, BoolQ: **“no added gold errors”** desteklenmiyor. A’da sıfır çözülmüş iş varken C’de **15 yanlış** vardır; A’nın yanıt vermemesi hata eklenmediğini göstermez. “Ek hata koşulu bu eksik referansla doğrulanamaz” yazın.

OK — “Verdict”, BoolQ ve pooling: **1.0193 / 0.4065** ve **0.6910 / 1.0882** scorer’la aynıdır. Pooling’in sayısal makespan koşulunu karşılamadığı doğrudur.

CHANGE — “Verdict”, BoolQ: **“235 s of reconnects”** ve **“they carry no information”** aşırıdır. Scorer **235.0 saniye toplam makespan** verir; tamamının reconnect süresi olduğunu göstermez. Oranlar geçerli bir performans karşılaştırması kurmaz, fakat başarısız girişimin maliyetini betimler.

OK — “Magnitude”: **“status invalid … computes no ratio”** raporla uyumludur. Ayrı hesaplanan betimleyici oranların resmî magnitude sonucu olmadığının belirtilmesi doğrudur.

CHANGE — “Magnitude”, R tablosu: **269.42, 62.43, 167.20, 166.39, 4.3154, 1.0049, 0.8019, 1.0903** verilen scorer raporunda bulunmuyor; `R_cells` de pakette yok. Yuvarlanmış girdiler oranlarla yaklaşık tutarlıdır, fakat R maliyet atfı ve makespan sınırları doğrulanamıyor. Kaynak veriyi ekleyin veya doğrulanmamış hesaplar olarak işaretleyin.

OK — “Magnitude”: **“even a valid run would not have replicated direction; both ratios are below … 4.4 and 1.6”**, verilen R oranları doğru kabul edilirse eşik aritmetiği olarak doğrudur: token oranı yön eşiğini karşılar, zaman oranı karşılamaz. Bunu gerçekleşmiş, geçerli bir replication sonucu olarak sunmayın.

OK — “What was measured”, ana hücre tablosu: **13 satırın tamamındaki** state, correct, unresolved, rule answers, calls, tokens, tokens-per-correct ve makespan değerleri scorer raporuyla eşleşiyor. BoolQ B’nin **17**, C’nin **15** yanlış yanıtı da `256 − correct − unresolved` hesabıyla doğrudur.

CHANGE — “What was measured”, sensitivity: **0.6783, 0.4758, 1.2414, 1.6392, 1.1333** additive sonuçları paketteki scorer çıktısında yoktur. Ayrıca **“No sensitivity gate passes”** yerine “Sensitivity altında da hiçbir birleşik başarı sonucu kurulamaz” yazın; belirtilen sayılarda Codex’in cold ve warm token ölçütleri karşılanıyor.

CHANGE — “Per operation” tablosu: Operasyon başına bütün token değerleri ve **“every operation 64 of 64 correct”** iddiası verilen scorer raporundan bağımsız olarak doğrulanamıyor. Toplam hücre doğruluğu doğrulanıyor; operasyon dağılımı ve maliyet atfı için ayrıntılı veri eksik.

OK — “Reading” 1 ve 5: Codex’in tam **R** için kural önermesi ve bunların kabul edilmesi, Sonnet’in hiçbir kural önermemesi, BoolQ’da öneri olmaması ve bootstrap’taki **3 hata** scorer’da mevcut. Bu BoolQ hatalarının efficiency-invalidating olmaması A4.6’ya uygundur.

CHANGE — “Reading” 1: **“64 of 64 coverage, 0 covered errors”** admission ayrıntıları scorer özetinde yoktur. “Admitted” sonucu doğrulanıyor; admission sayıları ayrıca kanıt gerektiriyor.

BLOCKER — “Reading” 2–3: **“Warm, rules cut Codex tokens”** ve **“Pooling helped tokens”** yasaklanmış kural/pooling katkı iddiasına dönüşüyor. “Warm C’de ölçülen token maliyeti A’dan düşüktü” ve “Cold C/B token oranı 0.6910 idi” şeklinde yalnız kol ölçümlerini anlatın; nedensel katkı sonucu çıkarmayın.

CHANGE — “Reading” 2: **2.1x**, **16%** ve **3.6x** ilgili tam-workload sayılarıyla uyumludur; fakat **“that call alone (22.1 s) was slower than any of A’s four parallel calls”** hücre düzeyindeki scorer tablosundan doğrulanamaz. Tekil çağrı kayıtları ve pilotun çağrı düzeni pakette yoktur.

CHANGE — “Reading” 3: **“the bootstrap costs more than the rules save”** net token ölçümüyle uyuşmuyor: bootstrap dahil C, A’dan yaklaşık **%16.3 daha düşük** token maliyetine sahip. “Bootstrap dahil net azalma %25 eşiğine ulaşmadı” yazın.

CHANGE — “Reading” 4: **“warm C equals warm A within noise”** için tekrar ölçümü veya belirsizlik analizi yoktur. Ölçülen token oranını **0.9951**, makespan oranını **0.9172** olarak verin. **“again”** ve pilot bütçe hatasının tekrarlanmadığı iddiasının tarihsel kısmı bu paketten doğrulanamıyor.

OK — “Convergence”: A4.8, scoring sonrasında reviewer–learner AST yakınsamasının **gözlem olarak** raporlanmasına izin verir. Invalid verdict bu gözlemi tek başına yasaklamaz; gözlem gate veya magnitude sonucunu değiştiremez.

CHANGE — “Convergence”: Hash’ler, **437/428/1,278/1,008 byte**, **273/214 node**, prompt’un **33,765 byte** olması, ilk **40 byte** taraması, **2 CLI notice** ve scorer’ın `convergence()` kontrolü paketteki bağımsız kanıtlarla doğrulanamıyor. AST’ler, prompt, stream ve scorer kodu verilmediğinden bunları doğrulanmış audit sonucu olarak sunmayın.

CHANGE — “Convergence”: **“The likeliest reading … essentially one minimal canonical AST”** desteklenmiş sonuç değildir. Operasyon sözleşmeleri hesapların basitliğini gösterir; frozen AST dili veya alternatif minimal çözümler incelenmeden kanoniklik ve en olası açıklama belirlenemez. “Sınanacak bir hipotez” olarak yazın; A4.8’deki aşırı genelleme sınırını koruyun.

OK — “Validity items”: Isolation’ın passed olması, **4 leakage**, **0 accounting failure**, üç bootstrap’ın efficiency-valid olması, classification/simulation/artifact/freeze problem sayılarının sıfır olması ve safety kill’in false olması scorer özetinde destekleniyor. Bootstrap’ın yerel validity sonucu, genel invalid verdict’i kaldırmaz.

CHANGE — “Validity items”: **86 isolation event, 51 launch record, 6 replay fixture, 46,080/38,154 cached token, 23 reconcile record, 14 wave gate**, decoder hash’i, auth hash kontrolleri ve r1’in beklenen auth failure olması bağımsız kanıtlarda yoktur. **51 fiziksel çağrı** bütçeden doğrulanabilir; diğer ayrıntılar için kaynak gereklidir.

OK — “Interrupted and stopped cells”: BoolQ A’nın **invalid**, `features` hücresinin bulgusuz **interrupted** olması scorer’la ve A4.14.1’le uyumludur.

CHANGE — “Interrupted and stopped cells”: Exit **75**, zaman damgaları, containment, hiçbir resume/rerun yapılmaması, bağımlı hücre bulunmaması ve diğer **16** hücrede `DONE.json` olması scorer özetinden doğrulanamaz. Bunları destekleyen yürütme kayıtları pakette bulunmuyor.

OK — “Preparation and review calls”: Agent toplamları **26/53/2/4/2**, toplam **87** ve Astra cap **30** scorer ile uyumludur. İmzalı A4.13 revision 2, global cap’i **246** yapar; eski Astra **20** sınırı nihai sınır değildir.

CHANGE — “Preparation and review calls”: **72 rows**, kategori dağılımı **41/44/2** ve ledger hash’i paketten doğrulanamıyor. Ayrıca **246 hazırlık/review bütçesi değildir**; evaluation dahil global sınırdır. Bilinen **87 + 51 = 138** çağrıyı, eksik dispatch sayıları nedeniyle alt toplam olarak ayrı gösterin.

BLOCKER — “Preparation and review calls”: **“No cap was exceeded”**, hemen ardından kabul edilen eksik runner/scoring kayıtlarıyla doğrulanamaz. A4.13.2 gerçek agent/kategori toplamlarını gerektirir. Eksik çağrıları, bu sonuç incelemelerini ve revizyonların yürürlüğe giriş sırasını uzlaştırın; hem agent hem global cap uyumunu bundan sonra değerlendirin. Sonradan yükseltilen cap önceki aşımı geriye dönük meşrulaştırmaz.

OK — “Run costs”: **29/2/20/51** fiziksel çağrı, scorer bütçesiyle uyumludur. Bildirilen bootstrap maliyetleri doğru kabul edilirse çift analitik yüklemeyi bir kez çıkarınca **539,464 / 215,587**, telemetry eklenince **766,570** token elde edilir; toplama tutarlıdır. **31/62, 29/38, 0/20, 2/4, 20/40**, warm increments ve bootstrap’ın B/C’ye tam yüklenmesi ilgili rapor/protokolle uyumludur.

CHANGE — “Run costs”: Bootstrap tokenları **25,760/24,079/19,523** scorer özetinde ayrı verilmemiştir; **19,580 reasoning token**, driver quota **%77/%78**, Codex **%3** ve owner probe’larının yaklaşık **29 token** olması da doğrulanamıyor.

CHANGE — Giriş: Run/experiment kimlikleri, freeze ve dosya hash’leri, commit’ler, CLI sürümleri, çağrı zaman aralığı ve **“exit 0”** verilen bağımsız kaynaklarda doğrulanmıyor. Bunları audit edilmiş provenance olarak değil, rapor sahibinin aktardığı metadata olarak ayırın.

CHANGE — “What follows” 1: **“every Sonnet gate”** ifadesini “Sonnet’in birleşik materials koşulları” olarak düzeltin; doğruluk koşulu karşılanıyor. **“preregistered transport rule”** yerine “preregistered tool-event uncertainty/leakage disposition” yazın; P1 taşıma sınıflandırması bu pakette yoktur.

BLOCKER — “What follows” 2: **“The rule mechanism itself behaved as designed”**, **“Token savings on R … close to the pilot”** ve **“the time gain did not reproduce once one operation stays model answered”** açılıştaki claim yasağını aşan başarı/nedensellik anlatısı oluşturuyor. Önerilen ve kabul edilen kuralları, **142 + 142 + 192 = 476 kural yanıtı olayını** ve safety-kill sonucunu betimleyici olarak koruyun; geçerli mekanizma başarısı veya pilot magnitude sonucu çıkarmayın.

CHANGE — “What follows” 3: **“so network retries are not leakage”** sonraki P1 kararının sonucunu peşinen belirliyor. “Doğrulanmış taşıma bildirimlerinin hangi dar koşullarda istisna sayılacağını freeze öncesinde fixtures ve anchored grammars ile karara bağlamak” yazın; belirsiz yürütme yine invalid kalmalıdır.

CHANGE — “What follows” 4: **“convergence … repeats across model families”** yalnız doğrulanmış AST eşleşmelerinin betimlemesi olarak kalmalıdır. **“would separate language narrowness from any other channel”** fazla kesindir; çoklu minimal AST içeren bir test hipotezleri sınamaya yardımcı olur, bütün diğer kanalları tek başına ayıramaz.

VERDICT: do_not_sign