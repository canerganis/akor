# ÖZ/encoding ölçümü

Bu çevrimdışı benchmark, mevcut ÖZ/2 sentetik senaryolarında tam alıcı girdisini gerçek tokenizer’larla sayar. Model ve araç çağrısı yapılmaz.

| Senaryo | İlk auto sözlük paketi |
|---|---:|
| code | 32 |
| materials | 32 |
| data | 32 |
| translation | 32 |
| support | 32 |
| planning | 32 |

`Auto` tek bir eşik kullanmaz. Her tam JSON/sözlük girdisini tüm seçili tokenizer’larda karşılaştırır; hiçbir tokenizer’da gerileme olmamasını, en az bir kesin tasarrufu ve `min_savings` değerini ister. Tablodaki crossover yalnız bu sentetik fikstürler için gözlenen ilk pakettir.

## Materials scaling senaryosu

| İş sayısı | o200k JSON | o200k dictionary | o200k auto | cl100k JSON | cl100k dictionary | cl100k auto | Seçilen auto modu |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 563 | 677 | 563 | 563 | 675 | 563 | json/tuples |
| 4 | 602 | 703 | 602 | 602 | 698 | 602 | json/tuples |
| 8 | 684 | 753 | 684 | 684 | 744 | 684 | json/tuples |
| 16 | 821 | 839 | 821 | 821 | 823 | 821 | json/tuples |
| 32 | 1095 | 953 | 953 | 1095 | 951 | 951 | oz_base/tuples+table |
| 64 | 1643 | 1177 | 1177 | 1643 | 1175 | 1175 | oz_base/tuples+table |

## Yöntem ve sınırlar

- Altı eski OZ/2 senaryosu ve 1, 4, 8, 16, 32, 64 görevli paketler kullanıldı. Her satırın ID, wire metni, bağlamı ve gerekiyorsa sözlüğü tam alıcı girdisinde sayıldı.
- `off` yalnız kompakt JSON adaylarını; `on` yalnız OZ/1/2 sözlük adaylarını ölçer. `auto`, tam girdileri karşılaştırıp gate koşullarına uyan sonucu seçer.
- En büyük ölçülen paket 64 iştir; runtime girdi bütçeleri ayrıca geçerlidir. Token sayıları yalnız `tiktoken` tokenizer’larına aittir.
- Bu ölçüm canlı model tasarrufu, görev doğruluğu, gecikme veya genel performans iddiası değildir.

Ham tüm senaryo sayımları ve varsayımlar `OZ-ENCODING-RESULTS.json` içindedir.
