# AKOR çalışma rehberi

- Kullanıcıyla Türkçe konuş. Kendi repo kökünde çalış; önce `git status --short`, `git log -1` ve göreve ait güncel karar/planı kontrol et. Kullanıcı ve diğer ajan değişikliklerini koru.
- Başlangıç: `README.md` ürün ve benchmark kapsamı; `USAGE.md` komut sözleşmeleri; `pyproject.toml` giriş noktaları ve bağımlılıklar. Yalnız ilgili `docs/design/` planını oku.
- OZ-map replication işi için `docs/design/ozmap-replication-2026-10-24/` altındaki güncel amendment/ruling ve freeze kayıtları belirleyicidir. `build-notes.md` tarihsel test kaydıdır, güncel yeşil suite kanıtı değildir.
- Freeze kapsamındaki çekirdeği/benchmark girdilerini göreve özel açık yetki olmadan değiştirme. Replication işi sırasında `bench/ozmap/`, `oz_*.py`, `examples/` ve `bench/ozmap_rep/ops/` sınırlarını aktif plandan doğrula. Kör değerlendirme girdilerine işlem ayrıntılarını sızdırma.
- Deterministik testler model çağrısı değildir. Gerçek `claude`, `codex`, adapter veya live benchmark çağrıları için yetkili kapsamı, kota ve toplam token bütçesini kontrol et; süren başka run'ı yeniden başlatma.
- Başarısız çağrı/retry, reasoning ve cache alanlarını sağlayıcının gerçek kullanım kayıtlarıyla raporla. Batching avantajını format avantajından; tarihsel Sonnet/Opus hücrelerini güncel Codex sonuçlarından ayır.

## Çalıştırma ve doğrulama

Python çekirdeği >=3.10, bağımlılıksızdır; tokenizer benchmark'ı ayrı `benchmark` extra'sını kullanır. Mevcut `.venv` ve test aracını kontrol et; kurulum yapmadan önce eksik bağımlılığı bildir.

- Küçük parser smoke: repo kökünden `python -B -m unittest discover -s tests -p test_oz.py`.
- Host-only manual akış: `python -B -m unittest discover -s tests -p test_oz_manual.py` (Windows acceptance, tiktoken gibi ek ortam koşullarını kaynakta kontrol et).
- Replication değişikliğinde ilgili dar test: `python -B -m pytest bench/ozmap_rep -q`; ortamda pytest bulunduğunu doğrula. `run live` bu testin parçası değildir.
- Kod değişikliğinde ilgili davranış/regression testini çalıştır; mümkünse hata düzeltmesinden önce başarısızlığı göster. Belge değişikliğinde kaynak, komut yolu ve diff kontrolü yeterlidir.
- Tamamlanma: istenen davranış doğrulandı, test exit/result kaydedildi, bilinen FAIL/SKIP açıklandı ve yalnız kendi değişikliklerin yerel commit edildi. Sayıları tahmin etme; push ayrıca yetki ister.
