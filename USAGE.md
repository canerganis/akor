# ÖZ 0.9.0 kullanım kılavuzu

ÖZ, mesaj dilini ve aktarımı yönetir; kullandığın model veya ajan sistemini sen bağlarsın. Python 3.10+ gerekir. Başlangıç, gönderim, durum ve inceleme standart kütüphaneyle çalışır. Token sayımı için isteğe bağlı `tiktoken` kullanılır.

Paketler [ÖZ/9](OZ9.md) dilinde gider (tel sürümü `stage-1d`, tasarım: [docs/design/stage-1d-astra.md](docs/design/stage-1d-astra.md)): cevap kipine göre sabit sistem metni (aşağıda `--reply-mode`) ve tek JSON gövdesi `{"goal","d","j"}`. `d` görev adlarını talimatlara bağlar; `c` tablosu ve `{"input":...}` sarmalayıcısı yoktur. `j` işleri sırayla `[id,görev,girdi]` biçiminde taşır, öncülü olan işte dördüncü öğe `prior` listesidir: `[id,görev,girdi,prior]`. Girdi, çözülmüş referans metninin kendisidir; referansı olmayan iş `null` kullanır. İş kimliği pakette benzersiz boş olmayan bir string'dir: tek model atomlu işte inbox kimliği, çok atomlu işte atom başına `<kimlik>.<atom indeksi>`. Literal metinler `d` içinde `literal_0`, `literal_1` gibi adlarla gider; numara kanal başına ilk gönderim sırasıyla verilir, kalıcıdır ve paket bölünse ya da iş yeniden denense de değişmez, özdeş metin aynı adı paylaşır. Model her iş için doğal bir JSON değeri döndürür. `read` ve `test` modele gitmez: `read` boş string, `test` prosedür metnini aynen döndürür; ikisini host yerelde doldurur. Pakette model işi kalmazsa adaptör hiç çağrılmaz. Az sayıda büyük çağrı en çok tasarrufu sağlar; `oz run --min-batch` ve `--max-wait` bunun içindir (aşağıda).

## İlk çalışan örnek

Repo içinde:

```powershell
python -m pip install ".[benchmark]"
oz demo .oz-runtime/deneme
oz status --workspace .oz-runtime/deneme
oz inspect review --workspace .oz-runtime/deneme
```

Demo boş bir klasör oluşturur. `read` işi host'ta, `propose` işi yerel programda tamamlanır; inceleyen ajan bunların sonuçlarını bekler, kendi işi (`read`) model çağrısı olmadan host'ta biter. Durum olayı model çağrısı olmadan kaydedilir. Demo programının çıktıları açıkça `DEMO receipt only` der; gerçek iş/test yapıldığı iddia edilmez. Aynı klasöre yeniden `demo` uygulamak yerine mevcut durumu incele veya yeni boş klasör seç.

Tokenizer ilk kullanımda sözlüğünü indirebilir; bu model çağrısı değildir. `TIKTOKEN_CACHE_DIR` önbellek konumunu seçer. Model anahtarı gerekmez.

## Kendi kaynak dosyanla başla

```powershell
oz init .oz-runtime/ekip --goal "Kaynağı incele; ölçüm belirsizliğini koru." --source veri.txt
cd .oz-runtime/ekip
oz send r --id okuma
oz plan --show-prompt
```

Yama ve test prosedürü için:

```powershell
oz init .oz-runtime/kod --goal "Yamayı incele; public API değişmesin." --source degisiklik.diff --kind patch --procedure kontroller.txt
oz send V --id inceleme --workspace .oz-runtime/kod
```

Prosedür dosyası yapılacak testlerin açıklamasıdır; ÖZ dosyadaki komutları kendisi çalıştırmaz. Yama profilinde `V`, okuma + inceleme + varsa test prosedürü isteğidir. Kaynak profilinde prosedür yoksa `r`, varsa `V` kullanılır.

Girdi dosyası UTF-8 olarak tam okunur; CRLF dahil satır sonları korunur. Kaynak yolu ve ham byte'ların SHA-256 özeti kayda girer. Dosyanın sonradan değişmesi mevcut kanalı değiştirmez. Yeni kaynak/revizyon için yeni kanal gerekir.

`oz init` yalnız boş klasöre yazar. Şu dosyalar oluşur:

| Dosya | İçerik |
|---|---|
| `oz.json` | Kanal manifestleri, tokenizer, girdi bütçesi ve paket büyüklüğü |
| `inbox.sqlite` | İşler, sonuçlar, bağımlılıklar, denemeler ve geçmiş |
| `BASLANGIC.md` | Kanalına uygun ilk komutlar |
| `.gitignore` | Yerel SQLite çalışma dosyalarının yanlışlıkla commit edilmesini önleyen desen |

Bir mevcut manifesti `oz init KLASOR --channel kanal.json` ile kullanabilirsin. Yeni bir kanalı mevcutları değiştirmeden eklemek için `oz channel-add yeni kanal.json` kullan. `worker` ve `reviewer` kanal takma adlarıdır; kendi isimlerinle yeni kanallar eklenebilir. Değişmez eski kanalı korumak bekleyen işlerin bağlamını korur.

## Mesaj ve bağımlılık

```powershell
oz send P --id plan1
oz send r1 --to reviewer --id kontrol1 --after plan1
oz send --file yeni-bilgi.txt --id bilgi1
oz status
oz inspect plan1
```

İlk satır varsayılan demo kanalındaki `P` içindir; gerçek kaynak profilinde kanalın desteklediği `r` veya `V` kullanılır. `--after` birden fazla kez verilebilir. Bağımlılıklar aynı oturum/görev/revizyonda olmalıdır; farklı alıcılar desteklenir.

Gönderici cevap gelmediği için yeniden gönderiyorsa **aynı `--id`** kullanmalıdır. Aynı ID ve anlam tekrar iş yaratmaz. `--id` verilmezse yeni kısa rastgele ID üretilip gösterilir; her çağrı yeni iş sayılır. `--file` yeni metni literal veri olarak taşır, çalıştırılacak talimat olarak yorumlamaz. Frame sınırı 8192 UTF-8 byte'tır; büyük kaynakları kanal referansı olarak ekle.

Öncül işlerin sonuçları, bağımlı işin kendi girdisine `{"input":...,"prior":[...]}` olarak katılır (`prior`, yalnız doğrudan öncüllerin başarılı sonuç kayıtlarıdır ve `--after` verilme sırasındadır; kayıtlar JSON değeridir, JSON metni içeren string değildir: tek atomda değerin kendisi, çok atomda `{"results":[...]}`; bu sürümden önce saklanmış sonuçlar string olarak gider. Başarısız öncül bağımlı işi bloklar, iş eksik `prior` ile gönderilmez). Çalışanın göreceği ayrı bir bağımlılık sözdizimi yoktur; özdeş girdiler aynı `c` numarasını paylaşır. Bunlar **doğrulanmamış ajan verisidir**, yeni yetki veya kanıt değildir. Sayılar ve belirsizlikler otomatik özetlenmez. Sonuçlar bütçeye sığmıyorsa iş bekler. Düşük seviyeli `Delivery.prepare` yalnız kendi frame'lerini gösterir; otomatik devir için `Inbox.plan`, `claim_prepared` veya `Worker` kullan.

## Kendi ajan programını bağla

`adapter.json`:

```json
{"argv":["python","benim_ajanim.py"],"protocols":["oz.adapter/3"],"languages":["OZ/9"]}
```

`protocols` ve `languages`, programın konuşabildiği sürümlerdir; desteklenmeyen sürümde hiçbir iş alınmadan durulur. Argümanlar liste olarak verilir; shell komut dizisi olarak yorumlanmaz. Çalışma dizini adaptör JSON dosyasının klasörüdür. `init`, `send`, `plan` ve `status` adaptör çalıştırmaz. Açıkça çalıştırmak için:

```powershell
oz run --adapter adapter.json --max-calls 4 --timeout 120
```

Program stdin'den tek UTF-8 JSON nesnesi alır:

```json
{
  "protocol":"oz.adapter/3",
  "language":"OZ/9",
  "binding":"...",
  "receipt":"2a",
  "ids":["plan1","plan2"],
  "attempts":[1,1],
  "system":"Sabit sistem metni...",
  "prompt":"İşleri taşıyan tek satırlık JSON gövdesi...",
  "prompt_tokens":[312]
}
```

Modeline yalnız `system` (sistem talimatı) ve `prompt` (kullanıcı mesajı) alanlarını ver. `prompt_tokens`, ikisinin birleşik ölçümüdür. `ids`, `attempts` ve `receipt` host üstverisidir; prompt'ta yer almazlar. `receipt` her denemede yenilenen kısa bir sayaçtır; cevabı o çağrıya bağlamak içindir, kimlik doğrulama değildir. stdout yalnız aşağıdaki JSON olmalıdır; tanılama için stderr kullanılabilir:

```json
{
  "reply":"[0,\"Sonuç metni\"]\n[1,[\"12.48 mm\",\"12.52 mm\"]]\n[2,null,\"kaynak eksik\"]",
  "usage":{"input_tokens":312,"output_tokens":44,"cached_input_tokens":0}
}
```

`reply`, modelin ham metin cevabıdır (JSON ayrıştırma adaptörün işi değil). `jsonl` kipinde her satır tam iki öğeli `[id,sonuç]` dizisidir; `id`, istekteki iş kimliğidir ve harfi harfine karşılaştırılır. Çok atomlu iş (`r7a7t14` gibi) birkaç sonuca açılır; host modelin ve kendi (`read`, `test`) sonuçlarını atom sırasıyla toplar ve `{"results":[...]}` olarak saklar. Kabul bütün cevap için atomiktir: satırlar LF üzerinden bölünür, uçlardan yalnız ASCII boşluk, tab ve CR atılır, boş satırlar yok sayılır. Bilinmeyen kimlik, bozuk satır, çift anahtarlı nesne, sonlu olmayan sayı, aynı kimlik için farklı baytlar, `2N`den fazla boş olmayan satır (`N` iş sayısı) veya kimlik kümesinin beklenenle tam eşit olmaması bütün cevabı reddeder; hiçbir sonuç yayımlanmaz ve bütün işler yeni receipt ile yeniden denenir. Bayt bayt aynı tekrar satırı tek sayılır ve ledger'a `duplicate_lines` olarak yazılır. Modelin bir işi yapamadığını bildireceği ayrı bir hata biçimi yoktur; eksik kimlik cevabı reddettirir. Satır en çok 65536 byte, cevabın tamamı `65536 × iş sayısı + 4096` byte olabilir. Adaptör hatası veya zaman aşımında da bütün işler yeniden denenir. Satır hataları `calls.jsonl` içinde `validation.violations` altında görünür.

**Cevap kipi.** `oz run --reply-mode jsonl|value` ve `oz plan --reply-mode jsonl|value` (Python'da `Worker(..., reply_mode=...)`) hangi sistem metninin gideceğini seçer; varsayılan `jsonl`; kip çağrıdan önce sabitlenir, çıktıya bakılarak değişmez. `value` kipi tam bir model işi içindir (her çağrı bir iş; birden fazla model atomlu iş çağrıdan önce host hatasıdır): gövde `"j":[görev,girdi]` veya `[görev,girdi,prior]`, cevap kimliksiz tek JSON değeri satırıdır (bayt bayt aynı en çok iki kopya kabul edilir, farklı ikinci satır reddedilir). `calls.jsonl` içinde `validation.binding` jsonl için `declared`, value için `host`, `semantic_verified` her zaman `false` yazılır: modelin yazdığı kimlik yanındaki cevabın o işe ait olduğunu kanıtlamaz, yalnız `value` kipi çağrı-iş bağını host'a verir, içerik doğruluğu için göreve özgü doğrulayıcı gerekir. `--context full` kalktı (`c` tablosu yok); yalnız `needed` vardır.

String sonuçlar olduğu gibi, diğer değerler kompakt JSON metni olarak saklanır. `usage` isteğe bağlı sağlayıcı raporudur; yoksa bilinmiyor kabul edilir. Cached input normal input'a tekrar eklenmez. Sistem metni, cevap sözleşmesi ve öncül çıktılar yerel girdi bütçesine dahildir. Çalışma alanında her model çağrısı `calls.jsonl` dosyasına (`akor.call/1`) `call_start` ve `call_end` satırları olarak eklenir; bilinmeyen değerler `null` kalır.

Hazır örnek: [examples/claude_cli_adapter.py](examples/claude_cli_adapter.py) isteği `claude -p` ile çalıştırır; `system` alanı `--system-prompt` olarak, `prompt` stdin olarak gider, model `OZ_MODEL` ortam değişkeniyle seçilir (varsayılan `claude-sonnet-5-5`; tam model kimliği kullan, `haiku` takma adı eski Haiku 4.5'e gidiyor). `adapter.json` içinde `argv` olarak Python yolu ve bu dosya verilir.

Python içinden subprocess olmadan mevcut framework'e bağlamak için:

```python
from oz_worker import Worker

def adapter(request):
    text = existing_agent(request["system"], request["prompt"])  # Kendi mevcut ajan çağrın.
    return {"reply": text}  # Ham model metni, satır başına bir JSON dizisi.

worker = Worker(inbox, channel, adapter, counters=[count_for_model], max_tokens=2048,
                capabilities={"protocols": ["oz.adapter/3"], "languages": ["OZ/9"]})
report = worker.run_once()
```

`existing_agent`, `inbox`, `channel` ve tokenizer kendi uygulamandan gelir. İstenen JSON sözleşmesi `system` metninde yer alır. Python callable zaman aşımını kendi sağlayıcı istemcisinde uygulamalıdır; keyfi Python fonksiyonu zorla durdurulmaz. Stdio adaptörü zaman aşımında başlattığı süreç ağacını sonlandırır. Stdio çıktı boyutu yakalama sonrasında denetlenir; bu bir bellek kotası veya araç sandbox'ı değildir.

## Bütçe, yeniden deneme ve görünürlük

`oz.json` içindeki `max_tokens` alıcı girdisinin üst sınırıdır. `encodings` hedef tokenizer adlarıdır; birden fazlası varsa her birinde sınır uygulanır. `batch_size` en fazla kaç hazır işin taranacağını belirler (1–64). Varsayılanlar 2048 token ve 64 iş. Hazır işler bekletilmeden tek çağrıda toplanır; canlı ölçümde büyük çağrılar toplam tokeni en çok azaltan ayardı.

`plan` yan etkisizdir: deneme veya lease tüketmez. Önce tam paket denenir; sığmazsa sınırlı, açgözlü seçim yapılır. Büyük bir iş daha küçük bağımsız işleri engellemez. Bu, bütün olası paketler için matematiksel optimum garantisi değildir. Bütçeye sığmayan işlerin metni kesilmez ve deneme hakkı harcanmaz.

Her model çağrısı sabit bir yük taşır (sistem talimatı, araç tanımları). Bu yükü daha çok işe bölmek için:

```powershell
oz run --adapter adapter.json --min-batch 16 --max-wait 30
```

Hazır iş sayısı `--min-batch` altındaysa ve en eski hazır iş `--max-wait` saniyeden genç ise `run` çağrı yapmadan `waiting` döner; deneme ve receipt harcanmaz. Varsayılan `--min-batch 1`, yani beklemeden çağırmaktır. Canlı ölçümde 32 işlik çağrılar 0.8'e göre toplam tokeni %43, 64 işlik çağrılar %55 azalttı ([OZ9.md](OZ9.md)).

`run` varsayılan tek adaptör çağrısı yapar; `--max-calls` ile üst sınır artırılır. Boş kuyruk, adaptör hatası veya geçici hata sonucu döndüğünde durur; arka planda sonsuz döngü başlatmaz. Yeni işlerin varsayılan deneme hakkı 2'dir (ilk deneme dahil; `oz send --max-attempts` ile değişir). Geçici hata için varsayılan iki saniyelik bekleme kalıcı kaydedilir. Model gerektirmeyen (yalnız `read`/`test`) paketler adaptörsüz, `host_completed` durumuyla biter; bunlar `--max-calls` hakkından düşmez. Zamanı gelince tekrar `run` çağır.

```powershell
oz status
oz status --json
oz inspect plan1
oz retry plan1 --extra-attempts 1
oz events
```

`retry` yalnız başarısız işi yeniden açar; tamamlanan işi tekrar çalıştırmak için yeni ID gerekir. `events` host olaylarını yalnız kaydeder; stop isteğini uygulamaz, araç çalıştırmaz veya başarıyı doğrulamaz. `status` varsayılan olarak sonuç metinlerini göstermez; `inspect` içerik ve olay geçmişini açar.

`ready`: hazır; `waiting`: öncül bekliyor; `backoff`: yeniden deneme zamanı bekleniyor; `leased`: teslim edilmiş; `expired`: teslim süresi dolmuş; `failed`: deneme sınırı veya kalıcı hata; `done`: host sonucu kabul edip ACK etmiş. `done`, dış dünyadaki iddianın doğruluğuna dair bağımsız onay değildir.

CLI çıkış kodları: **0 başarılı/boş**, **2 yapılandırma, girdi veya bütçe hatası**, **3 adaptör ya da iş sonucu hatası**. Sağlayıcı istisnasının keyfi metni kayda alınmaz; `adapter_timeout`, `adapter_invalid_json`, `adapter_invalid_reply`, `adapter_exit_N` gibi kodlar gösterilir. Tokenizer'ın gerçek hedef modelle eşleşmesini adaptör doğrulamalıdır.

SQLite v1 kuyruğu ilk açılışta v2'ye işlem içinde yükseltilir; işler/sonuçlar korunur. Aynı anda birden fazla çalışan ayrı SQLite bağlantılarıyla farklı işleri alabilir. Teslim en az bir kezdir: dış etki gerçekleşip ACK öncesi süreç kapanırsa iş tekrar gelebilir. Araç tarafında mesaj ID'siyle idempotency hâlâ gereklidir.
