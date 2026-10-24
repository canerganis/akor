# Council 3, Astra (gpt-6-astra, high), raw reply (Turkish, to be translated)

Note: the evidence pack used the working-tree oz_host.py, which held another session's uncommitted multi-operation edits on top of 43bb009. Finding B1 likely belongs to that work in progress.

**Council 3 kararı: HOLD. `43bb009` pilot freeze için hazır değil.**

İnceleme sağlanan kaynak üzerinde statiktir; runtime veya test çalıştırmadım. Test durumu **bilinmiyor**. Aşağıdaki engeller test sonucundan bağımsız: bootstrap yolunda eksik metot, belirsiz bootstrap sonrası replacement execution, kurtarmada kimlik ve muhasebe kaybı, eksik route doğrulaması bulunuyor.

**1. Council 2 blocker kapanışları**

| Astra blocker | Durum | Dosya/fonksiyon ve gerekçe |
|---|---|---|
| **1. Yetkili settlement, generation ve resume** | **Kısmen kapalı** | `oz_rulephase.py`: `open_job`, `_authority`, `settle_model` ve immutable emissions doğru yönde. Fakat `adopt_rule` mevcut sonuç bulunca authority kontrolünden **önce** dönüyor; `Learner.attempt` aynı erken dönüşü yapıyor. `mark_awaiting` generation doğrulamıyor. `oz_host.py::_settle_model` generation’ı hesaplamadan önce değil, cevap geldikten sonra alıyor. |
| **2. Awaiting verification ve eksiksiz check evidence** | **Kısmen kapalı** | `evidence_problem`, `adopt_rule`, `settle_model` eksik/inconclusive evidence ile acceptance’ı engelliyor. Ancak `ArmHost.report` kalan `awaiting_verification` işlerini incomplete nedeni saymıyor; bootstrap başarısı da bu nihai kontrol sınırından önce belirleniyor. |
| **3. Ortak bootstrap ve wave audit seçimi** | **Kısmen kapalı** | `ExperimentStore.assignment`, `claim_bootstrap`, `audit_wave` ortak kalıcı kayıt sağlıyor. B/C yolları ayrılmış. Ancak bootstrap çalıştırma yolu bozuk; import sırasında binding/payload eşitliği doğrulanmıyor; tüm wave için dataset-ID tekilliği yok. |
| **4. OS lock ve dispatch fencing** | **Kısmen kapalı** | `oz_spool.py::HostLock`, `Host.check`, scheduler transaction’ları eski takeover yarışını gideriyor. Ancak `Scheduler.close` çalışan daemon worker’ları bitirmeden kilidi bırakıyor. Eski worker sonradan host ledger/budget işlemi veya launch yapabilir. |
| **5. Atomik submit, binding ve teslim kimliği** | **Kısmen kapalı** | `Spool.submit`, `_bindings`, request mapping ve foreign-ID kontrolü önemli kısmı kapatıyor. `_deliver`, conflicting duplicate’ı kaydedip batch’i yine `delivered` yapıyor; host raporu bu rejection’ı geçersizlik olarak taşımıyor. Host intake katmanı ayrıca spool’un kimlik kontrollerinin tamamını uygulamıyor. |
| **6. Dört slot, bağımsız scheduler ve spool entegrasyonu** | **Kısmen kapalı** | Pilot A/B/C dispatch’leri spool’dan geçiyor; thread slotları ve child environment ayrımı var. Fakat eşzamanlı dört producer senaryosu `dry_run` içinde yok; global quota zorunlu değil; restart planı kalıcı değil. Learning kapalı `oz_map.run` hâlâ eski yolda. |
| **7. Ham kanıt ve bootstrap başarısı** | **Kısmen kapalı** | Shim bootstrap stdout/stderr/exit/timeout kanıtını parse öncesi saklıyor. Ancak host başarısı nihai settlement’a bağlı değil; recovery ilk denemenin kanıt/süre alanlarını değiştiriyor; başarısız fiziksel çağrıların raw capture ile ledger uzlaştırması tamamlanmamış. |
| **8. Etkin spec, exact AST ve route closure** | **Kısmen kapalı** | `bootstrap_shim.parse_envelope` ve `decode_ast` exact AST dilimini, 2.048 byte sınırını ve Unicode kontrolünü sağlıyor. Spec dosyasının içeriği burada verilmediğinden etkin semantik kapsamı doğrulanamıyor. Route closure ve dispatch öncesi yeniden doğrulama eksik. |

**Council 2 rulings**

Aşağıdaki numaralar Council 2’deki iki ayrı ruling listesine karşılık geliyor.

| Ruling | Durum | Gerekçe |
|---|---|---|
| Unmet **1 — ayrı DB, D1’i zayıflatamaz** | **Kısmen kapalı** | Settlement DB eklendi; yukarıdaki authority/resume açıkları sürüyor. |
| Unmet **2 — awaiting verification** | **Kısmen kapalı** | Acceptance sınırı düzeldi; rapor ve bootstrap sınırı tamamlanmadı. |
| Unmet **3 — ortak bootstrap ve ayrı B modu** | **Kısmen kapalı** | `ArmHost._pool` B’yi producer bazında ayırıyor; ortak bootstrap uçtan uca güvenilir değil. |
| Unmet **4 / A2.1 — replacement yok, unknown uzlaştırılmalı** | **Kısmen kapalı** | `max_attempts=1` ve spool unknown durumu doğru. Fakat `_rule_arm`, bootstrap unresolved olduğunda seçilmiş bootstrap işlerini normal fallback’e sokabiliyor. |
| Reading **1 / A2.2 — tam etkin spec, gizli örnekler hariç** | **Kısmen kapalı** | `spec_excerpt` hash kontrolü var. İçerik kapsamı doğrulanmadı; `check_hidden` tam leakage/disjointness kontrolü değil. |
| Reading **2 — özgün AST dilimi** | **Kapalı, statik olarak** | `parse_envelope` → `decode_ast` → registry admission/storage/reevaluation exact byte akışını koruyor. |
| Reading **3 — failed/memo audit inconclusive; memo efficiency ihlali** | **Kısmen kapalı** | `_decide_audits` inconclusive üretiyor. Audit memo ihlali kalıcı efficiency-invalid nedeni olmuyor; başarılı retry bunu rapordan silebilir. |
| Reading **4 — pending audit kimliği korunur, evidence tamamlanamaz** | **Kısmen kapalı** | Audit satırları kalıcı. Ancak resume yalnız `pending` olanları dispatch ediyor; `inconclusive` retry devamı ve fiziksel request kimliği güvence altında değil. |
| Reading **5 — interpreter hash ancak tüm semantiği kapsıyorsa yeterli** | **Kısmen kapalı** | `INTERPRETER` yalnız `oz_rule.py` hash’i. Bu dosyanın semantik closure’ı sağlanan kaynakta doğrulanamıyor. |
| Reading **6 — tam route dispatch öncesi yeniden hesaplanmalı** | **Açık** | `ArmHost._launch` supplied `identity` kullanıyor; yeniden `build/reconcile` yapmıyor. |

Opus’un beş blocker’ı da **kısmen kapalı**:

1. **Wave audit scope:** `audit_wave` ile düzeltilmiş; dataset tekilliği, mismatch ve resume açıkları var.
2. **Bootstrap claim yarışı:** `claim_bootstrap` işlemsel; fakat unresolved claim sonrası host davranışı A2.1’e uymuyor.
3. **Bootstrap environment sızıntısı:** gerçek child yolunda environment ayrılmış; frozen bootstrap packet membership doğrulaması eksik.
4. **Bootstrap retry muhasebesi:** normal worker retry kaldırılmış; unknown bootstrap’ın yeni fallback isteklerine dönüşmesi hâlâ mümkün.
5. **Eksik audit sonrası warm reuse:** `RuleStore.reusable` engelliyor; retry devamı ve ihlal geçmişi tamamlanmamış.

**DRIVER 8’i onaylıyorum:** quarantine sonrası henüz üreticiye teslim edilmemiş rule sonuçları model fallback’e gidebilir. Daha önce teslim edilmiş sonuç, hata ve maliyetler değiştirilemez. Gerçek teslim sınırı kalıcı olarak kaydedilmelidir.

**2. Step 6 için zorunlu düzeltmeler**

**B1 — Bootstrap yapılandırma metodu yok.**  
`oz_host.py::ArmHost._launch`, `self._bootstrap_config()` çağırıyor; verilen sınıfta bu metot tanımlı değil. Bootstrap daha child başlamadan exception üretir.

**Karar:** Metodu ekle; tüm workload operasyonları için `Learner.bootstrap_config` verisini birleştir, şemayı launch öncesi doğrula. Fake test, yalnız rapor oluşmasını değil **bir bootstrap çağrısının gerçekten gerçekleşmesini** doğrulamalı.

**B2 — Unknown bootstrap, replacement cevaplara dönüşebiliyor.**  
`_bootstrap` unknown sonuçta veya başka owner beklemesi dolunca `None` döndürüyor. `_rule_arm` bunun ardından boş `boot_ids` ile bütün işleri fallback’e gönderiyor. Böylece halen çalışan veya sonucu bilinmeyen bootstrap’ın 64 işi yeni request’lerle cevaplanabilir.

**Karar:** Frozen assignment, bootstrap kaydı oluşmadan da bağlayıcıdır. Bu 64 iş `bootstrap_pending` olarak tutulmalı; normal fallback’e girmemeli. Yalnız mevcut invocation reconciliation veya kanıtlanmış unlaunched recovery izinli. Malformed/failed bootstrap cevapları terminal failure olarak korunmalı.

**B3 — Bootstrap başarı kaydı yanlış sınırda ve çoklu çağrıyı eksik aktarabiliyor.**  
`_bootstrap`, yalnız `execute` sonuçlarının `accepted` olmasına bakıyor. Registry consumer kontrolleri daha sonra `_bootstrap_row → _settle_model` içinde çalışıyor. Bunlardan biri fail/inconclusive olsa bile kayıt `status=ok`, `efficiency_valid=true` kalabilir.

Ayrıca bootstrap birden fazla attempt’e bölünürse yalnız geçici `notes` invalid oluyor; ortak record ilk attempt’i saklıyor. Import eden arm diğer çağrıları ve maliyetlerini kaçırabilir.

**Karar:**

- Bootstrap’ın tam **64 kayıt ve tek planlanmış packet** olduğunu, shim ek metni dahil input sınırıyla launch öncesi doğrula.
- Başarıyı 64 ordinary cevabın **nihai host settlement’ı** tamamlandıktan sonra kaydet.
- Bütün başarısızlık nedenleri ve fiziksel attempts ortak immutable record’a girsin.
- Import eden arm aynı failure/invalidity durumunu devralsın.

**B4 — Host crash recovery, kalıcı dispatch planına dayanmıyor.**  
`_groups`, `_items` ve `_rows` yalnız bellekte. `_dispatch`, spool submission adını o anda kalan işlerin key kümesinden türetiyor. Crash sonrası bazı işler settled ise kalan küme değişebilir; önceden çalışmış işler yeni submission/request altında tekrar gönderilebilir. Eski reserved/unknown batch’lerin metadata’sı da yeniden kurulan kümelerde bulunmayabilir.

**Karar:** Wave planını dispatch öncesi kalıcılaştır: original job, spool delivery, round, pool, request, attempt ve allocation bağlantıları. Restart önce bu planı yükleyip mevcut attempts’i uzlaştırsın. Yeni request yalnız açıkça izin verilen yeni retry için oluşturulsun. Producer delivery zamanı ve payload’ı da kalıcı olmalı.

**B5 — Settlement boundary’de resume ve fencing bypass’ları var.**  
`adopt_rule` ve `Learner.attempt`, mevcut sonucu identity/generation kontrolünden önce döndürüyor. `mark_awaiting` eski generation’dan state değiştirebiliyor. Model generation’ının cevap geldikten sonra alınması, hesaplamanın hangi yetkiyle başladığını bağlamıyor.

**Karar:** Her işin execution authority’si dispatch/evaluation öncesinde tahsis edilsin. Resume dahil bütün yollar immutable job identity’yi doğrulasın. `mark_awaiting` aynı authority kontrolünü kullansın. İdempotent mevcut sonuç dönüşü ancak aynı payload/binding için mümkün olsun; daha önce yayımlanan sonuç quarantine nedeniyle silinmesin.

**B6 — Fiziksel çağrı muhasebesi crash ve reconciliation’da eksiliyor.**  
`Ledger.finished`, `execution=None` olduğunda fiziksel call listesi çıkaramıyor. `reconcile_unknown`, aynı attempt’in stdout/stderr hash’lerini reconciliation child’ının hash’leriyle, elapsed değerini de `None` ile değiştiriyor. `reconcile` yalnız eldeki `calls` satırlarını sayıyor; her launch’ın açıklanmasını zorunlu tutmuyor.

`calls` ve `allocations` idempotent insertion yolları da mevcut satırla tam payload eşitliğini kontrol etmiyor.

**Karar:** Launch, capture ve reconciliation ayrı append-only olaylar olsun. İlk kanıt ve elapsed hiçbir zaman değişmesin. Her reservation/launch şu sonuçlardan birine bağlansın: kanıtlı unlaunched, kesin physical call, unresolved physical outcome. Sonuncusu varken accounting complete olamaz. Raw core ledger ve adapter captures uzlaştırılsın; bilinmeyen kullanım sıfırlaştırılmasın. Tekrarlanan insert farklı payload taşıyorsa hard conflict verilsin.

**B7 — Allocation gerçek çağrı üyeliğine göre yapılmıyor.**  
`_ledger_calls` gerçek `call_start.job_map` üyeliğini okuyor; host allocation bunu kullanmıyor. `_dispatch`, spool batch’indeki bütün satırları attempt boyutuna bölüyor; `_capture` batch’in ilk call ID’sini ortak taşıyor.

Planner input sınırı nedeniyle yalnız batch’in bir bölümünü göndermişse, hiç çağrıya girmemiş işler de fiziksel maliyetten pay alabilir. Mevcut reconciliation aynı planlanan üyeliğe baktığından bu hatayı yakalamaz.

**Karar:** Fiziksel call membership doğrudan kalıcı `call_start.job_map` üzerinden kurulmalı. Producer/kind paylarının paydası gerçek dispatched kayıt sayısı olmalı. Planned, dispatched ve accepted sayıları ayrı tutulmalı.

**B8 — Cold timing’den zorunlu işler düşülüyor.**  
`report` şu hesabı yapıyor:

`makespan - bootstrap_seconds + bootstrap_attempt.elapsed`

Oysa `bootstrap_seconds`, `_bootstrap` içindeki kuyruk, bekleme, kayıt ve admission süresini de kapsıyor. Yerine yalnız attempt elapsed eklenince zorunlu cold maliyetlerin bir bölümü kayboluyor. Resume ayrıca `_row` üzerinden yeni teslim zamanları üretiyor.

**Karar:** Monotonic süre ölçümü ve kalıcı phase timeline kullan. Ortak bootstrap’ın tam tanımlanmış elapsed maliyeti B/C’ye tam yüklensin; arm’a özgü admission, check, queue ve audit süreleri korunmalı. Measured makespan ile replay projection ayrı alanlar olmalı.

**B9 — Bütçe ve concurrency pilot için zorunlu değil.**  
`Budget` frozen caps verilmezse unlimited; `launch_gate` opsiyonel; doğrudan `oz_quota` entegrasyonu yok. Dört slot host başına, deney genelinde değil. `Scheduler.close` kilidi worker’lar bitmeden bırakıyor.

**Karar:** Gerçek pilot giriş noktası, eksiksiz frozen configuration olmadan launch reddetsin. Global **50**, backend **37/13**, revize bucket tahsisleri ve deney genelinde dört fiziksel slot zorunlu olsun. Telemetry/preparation/retry de aynı reservation sisteminden geçsin. Shutdown yeni launch’ı kapatsın; worker ve child yaşam döngüsü sonuçlanmadan sahipliği bırakmasın.

**B10 — Rapor tamamlanmış/geçerli kanıtı fazla kolay ilan ediyor.**  
`report`:

- `awaiting_verification` işlerini incomplete nedeni saymıyor.
- Memo-served audit’i kalıcı efficiency invalidity olarak tutmuyor.
- Bootstrap answer kaydı memo bilgisini taşımıyor.
- Spool rejection’larını ve açıklanmamış launch durumlarını bütünüyle hesaba katmıyor.

`_tokens`, input/output alanlarının varlığından inclusive cached/reasoning accounting’in doğrulandığını çıkaramaz.

**Karar:** Kalıcı violation/event kaydı ekle. Retry önceki ihlali silemesin. Evidence completeness; settlement, audit, launch reconciliation ve accounting durumlarından birlikte türetilsin. Gold gates ayrıca hesaplanmalı; runtime `efficiency_valid` yalnız teknik önkoşul olsun.

**B11 — Etkin worker route dispatch’te doğrulanmıyor.**  
`ArmHost` supplied identity’ye güveniyor. `oz_route.build(env=...)` ise `probe` fonksiyonuna bu environment’ı iletmiyor. `source_manifest` yalnız argv dosyaları, sibling imports ve declared data’yı tarıyor; executable, parent/package imports veya diğer çalıştırılan bağımlılıkları genel olarak kapsamıyor.

**Karar:** Gerçek launch ortamı ile route’u yeniden hesapla ve frozen worker hash’ine eşitliğini doğrula. Dependency manifest açık ve tam olsun; çözümlenmemiş dependency launch’ı engellesin. Model/effort/backend, executable/CLI sürümü, invocation flags ve ilgili nonsecret environment aynı doğrulamaya girsin.

**B12 — Dataset/wave kimliği ve deney harness’i yeterince bağlanmamış.**  
`_validate_jobs` dataset ID tekilliğini wave genelinde zorlamıyor; `by_dataset` sözlükleri tekrarları sessizce ezebilir. Bootstrap import’unda `record.binding_key` ve dataset-ID→payload eşitliği doğrulanmıyor. `run_wave` tam 4×64 intake beklemiyor; `dry_run` producer submission’larını sırayla yapıyor.

**Karar:** Call öncesi sealed wave manifest zorunlu olsun: her dataset ID tek bir operation/input hash/producer/wave kaydına bağlansın. B/C aynı immutable veri ve binding manifest’ini tüketmeli. Dört scripted producer ortak barrier’dan başlasın. Admission/evaluation/warm ayrıklığı ve leakage kontrolü launch öncesi doğrulansın.

**3. Bütçe ve %55 hükmü**

**Kayıt amendment gerektiriyor.** Alıntılanan imzalı kayıtta %55 launch sınırı §4’te; architecture notu bunun kaldırıldığını söylüyor. Owner’ın token-limit istisnasının **%55 weekly launch guard’ını da kaldırdığı** ana kayıtta açıkça yazılmalı; kapsam ve bitiş koşulu belirtilmeli. Bu karar owner’a ait. Eski hüküm uygulanırsa bildirilen **%56’da yeni Sonnet launch yapılamaz**. Global 50 ve backend 37/13 sınırları değişmez.

Sonnet B eklenmesinin tahsisi de henüz çözülmüş değil. B’nin işleri dört producer’da çağrı gerektiriyorsa:

| Sonnet materials | En az çağrı |
|---|---:|
| A cold + warm | 8 |
| Ortak bootstrap | 1 |
| B producer-local residual/audit | 4 |
| C cold + warm residual/audit | 2 |
| **Toplam** | **15** |

Bu, bütün olası coverage dağılımları için matematiksel alt sınır değildir; **B’nin dört producer’ının da çağrı gerektirdiği durumda** alt sınırdır. Frozen audit seçimi bu durumu üretiyorsa 13 çağrıyla tam evidence elde edilemez. Audit seçimini bütçeye uydurmak, B’yi atlamak veya cap’i sessizce büyütmek yasak. Revize tahsis ve exhaustion halinde hangi evidence’ın incomplete kalacağı önceden yazılmalı.

**4. Pilot freeze kaydında zorunlu içerik**

| Alan | Freeze edilecekler |
|---|---|
| **Normatif kararlar** | Joint record, amendments, Council 3 düzeltmeleri, DRIVER 8, %55 owner kararı, geçerli belge önceliği ve byte hash’leri. |
| **Kod ve ortam** | Nihai commit/tree; frozen core hash manifest’i; host/spool/rulephase/map/route/shim; adapter ve executable dependency closure; interpreter; Python/OS/SQLite/CLI sürümleri; workspace configuration. |
| **Worker ve prompt** | Backend/model/effort, tam route/worker hash, flags, nonsecret environment; ordinary system/operation/goal metinleri; bootstrap instruction, effective spec ve envelope template byte hash’leri. |
| **Veri** | Codex materials/BoolQ cold ve iki backend materials warm manifest’leri; tam bytes/hash; dataset ID, operation, producer, sıra, newline policy. BoolQ snapshot/revision ve seçili örnek kimlikleri. |
| **Admission ve gold** | Operasyon başına bağımsız 48 representative + 16 predetermined challenge; label kaynağı, dataset/check/permission hash’leri; gold erişim ayrımı ve disjointness raporu. |
| **Deney matrisi** | Gerekli bütün A/B/C hücreleri; warm A/C; seed `20261024`; 4×64 producer barrier; bootstrap’ın producer başına 16 kimliği; arm order; concurrency 4, batch ≤64, flush 1 s. |
| **Semantik ve recovery** | Settlement authority, input policy, typed audit comparison, quarantine/delivery sınırı, pending/inconclusive retry politikası, bootstrap replacement yasağı, memo kapalı, unknown reconciliation kuralları. |
| **Muhasebe** | 50/37/13 cap ve revize bucket tahsisi; telemetry/preparation/retry giderleri; inclusive token tanımları; shared-bootstrap fiziksel tek/analitik çift yükleme; producer membership payları; timing başlangıç/bitişleri. |
| **Scoring** | Scorer kaynak hash’i; unique-job denominator; failed/awaiting/unresolved davranışı; bootstrap gold ve A karşılaştırması; ordered kills ve tüm cold/warm/pooling gate formülleri. |
| **Doğrulama** | Nihai commit’e ait okunabilir tam test sonucu; bağımsız fake oracle ve replay capture hash’leri; tüm matrix, crash boundaries, overflow, exhaustion ve race senaryolarının raporu; sıfır external-call kanıtı. |

Öğrenilen AST’ler çağrıdan **önce** freeze edilemez. Önceden artifact şeması ve no-revision kuralı dondurulur; bootstrap sonrası exact AST bytes/hash, raw cevap, admission sonucu, covered population ve audit selection append-only kaydedilir. B/C bunları aynı kimlikle kullanır.

**5. Kalan işi hızlandıracak kararlar**

- Önce **B1–B3**: çalışan ve A2.1’e uygun tek bootstrap yolu. Sonra durable recovery/accounting; ardından gerçek pilot harness.
- Yeni framework kurmayın. Mevcut SQLite yapısına kalıcı wave planı ve append-only attempt/violation olayları eklemek yeterli.
- B/C admission hesabını aynı immutable artifact/binding altında bir kez yapıp doğrulanabilir sonucu paylaşabilirsiniz. Analitik admission maliyeti iki arm için de önceden tanımlanmalı.
- Mevcut compatible fallback/audit packing’i koruyun. Prompt prefix reuse yapılabilir; cached input rapordan düşülmez.
- `none`/BoolQ için boş audit veya artifact-retry çağrıları üretmeyin.
- İlk bağımsız fake oracle, şu beş hatayı özellikle yakalasın: **bootstrap metodu yok**, **unknown bootstrap’a replacement**, **crash sonrası yeni request**, **memo audit sonrası yanlış valid**, **reconciliation sonrası eksik maliyet**.

Devam noktası: Claude bu engelleri giderip nihai commit, okunabilir test özeti ve tüm matrix’in sıfır dış çağrılı dry-run kanıtını getirmeli. Dosya değiştirmedim; commit veya push yapmadım.


