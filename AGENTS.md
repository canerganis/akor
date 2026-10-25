# AKOR

- Bu repo kökünde çalış; önce `git status --short`, `git log -1` ve ilgili güncel planı kontrol et. Başlangıç: `README.md`, komutlar: `USAGE.md`, ortam: `pyproject.toml` (Python >=3.10). Bütün geçmişi yükleme.
- Replication için `docs/design/ozmap-replication-2026-10-24/` içindeki güncel amendment/ruling/freeze belirleyicidir. Tarihsel build-notes güncel PASS değildir. Onaylı kapsam dışında `bench/ozmap/`, `oz_*.py`, `examples/` ve frozen ops'a dokunma; kör değerlendirmeye işlem ayrıntısı sızdırma.
- Parser kontrolü: `python -B -m unittest discover -s tests -p test_oz.py`. Replication değiştiyse mevcut pytest ortamında `python -B -m pytest bench/ozmap_rep -q`.
- Live model/adapter çağrısından önce yetki, kota ve toplam token bütçesini kontrol et; çalışan run'ı yeniden başlatma. Retry, reasoning ve cache'i gerçek usage ile raporla; batching/format ve tarihsel/güncel model hücrelerini ayır.
- Dar regression testi kullan; belge değişikliğinde kaynak/komut/diff kontrolü yeterli. Kullanıcı değişikliklerini koru; yalnız kendi farkını yerel commit et. Push ayrıca yetki ister. Sonuç ve kalan sınırı kısa bildir.
