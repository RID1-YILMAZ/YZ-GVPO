# Veri Paketi Oluşturucu (img2dataset tabanlı)

Bir AI platformu için **internetteki görselleri indirip tek bir veri paketi (dataset) klasöründe toplayan** araç.
Çekirdekte sektör standardı [rom1504/img2dataset](https://github.com/rom1504/img2dataset) kullanılır;
onun üstüne URL toplama, tekilleştirme, ayıklama ve `manifest.csv` üretme katmanı eklenmiştir.

## Klasör yapısı

```
veripaketiolusturma/
├── scriptler/
│   ├── url_toplayici.py        # Anahtar gerektirmeyen açık kaynaklardan URL toplar
│   ├── veri_paketi_olustur.py  # img2dataset sarmalayıcı + paketleme
│   └── img2dataset_yama.py     # /dev/shm olmayan ortamlar için iş parçacığı yaması
├── urls/                       # Toplanan URL listeleri (CSV)
│   └── ornek_kopek.csv
├── veri/                       # Üretilen veri paketleri
│   └── ornek_kopek/
│       ├── goruntuler/         # Tüm görseller tek klasörde (hash ile tekil adlandırılmış)
│       ├── manifest.csv        # dosya, url, caption, kaynak, lisans, boyut, sha256
│       ├── ozet.json           # Sayım ve atlanan kayıtlar
│       └── ham/                # img2dataset'in ham çıktısı (yeniden çalıştırmada kaldığı yerden devam)
└── requirements.txt
```

## Kurulum

```bash
pip install -r requirements.txt
```

## Hızlı başlangıç

**1. Adım — URL listesi topla** (Openverse + Wikimedia Commons; API anahtarı gerekmez):

```bash
python3 scriptler/url_toplayici.py --arama "golden retriever" --adet 200
```

Birden fazla sınıf/etiket için komutu her terim için tekrarlayın ya da birden fazla terim verin:

```bash
python3 scriptler/url_toplayici.py --arama "kedi" --adet 300 --cikti urls/kedi.csv
python3 scriptler/url_toplayici.py --arama "köpek" --adet 300 --cikti urls/kopek.csv
```

Kendi URL listeniz de olabilir: `url,caption` sütunlu herhangi bir CSV yeterlidir
(ek sütunlar: `kaynak,lisans,sayfa,arama` — isteğe bağlı, manifeste taşınır).

**2. Adım — Veri paketini oluştur:**

```bash
python3 scriptler/veri_paketi_olustur.py --girdi urls/kedi.csv --ad kedi --boyut 512
```

Çıktı: `veri/kedi/goruntuler/` + `veri/kedi/manifest.csv` + `veri/kedi/ozet.json`.

**3. Adım (isteğe bağlı) — Paketi arşivle ve platforma yükle:**

```bash
cd veri && zip -r ../kedi_veri_paketi.zip kedi && cd ..
```

## Seçenekler

### url_toplayici.py

| Bayrak | Varsayılan | Açıklama |
|---|---|---|
| `--arama` | (zorunlu) | Bir veya daha fazla arama terimi |
| `--adet` | 100 | Terim başına istenen görsel sayısı |
| `--kaynak` | `her-ikisi` | `openverse` / `wikimedia` / `her-ikisi` |
| `--cikti` | `urls/<arama>.csv` | Çıktı CSV yolu |

### veri_paketi_olustur.py

| Bayrak | Varsayılan | Açıklama |
|---|---|---|
| `--girdi` | (zorunlu) | URL listesi CSV'si |
| `--ad` | `veri_paketi` | Paket adı → `veri/<ad>/` |
| `--boyut` | 512 | Görsel boyutu (merkezden kırpma) |
| `--is-sayisi` | 4 | Eşzamanlı indirme iş parçacığı |
| `--min-boyut` | 128 | Bu boyuttan küçük görselleri ele (px) |
| `--ham-temizle` | kapalı | İş sonrası `ham/` klasörünü sil |

## Manifest sütunları

| Sütun | İçerik |
|---|---|
| `dosya` | Paket içindeki göreli yol (`goruntuler/...jpg`) |
| `url` | Kaynak görselin URL'i |
| `caption` | Başlık/açıklama (etiket olarak kullanılabilir) |
| `kaynak` | Openverse / Wikimedia Commons vb. |
| `lisans` | CC lisansı (atıf için saklayın!) |
| `genislik`, `yukseklik` | İndirilen görselin boyutu |
| `sha256` | İçerik özeti (tekillik kanıtı) |

## İşlenen adımlar

1. **URL toplama** — Openverse ve Wikimedia Commons API'leri (anahtarsız, lisanslı).
2. **İndirme** — img2dataset ile çok iş parçacıklı, yeniden boyutlandırılmış, `incremental`
   (yarım kalan işi tamamlayan) indirme.
3. **Ayıklama** — bozuk görselleri açamayanları eleme, `--min-boyut` filtresi.
4. **Tekilleştirme** — SHA-256 ile birebir aynı görselleri elme.
5. **Paketleme** — tek klasör + `manifest.csv` + `ozet.json`.

## Notlar ve sorun giderme

* **`/dev/shm` yoksa:** Bazı konteyner ortamlarında POSIX semaforları kurulamaz; img2dataset
  bu yüzden `PermissionError` ile düşer. Bu depodaki `img2dataset_yama.py` bu durumu otomatik
  algılayıp iş parçacığı tabanlı taklitlerle çözer — sizin bir şey yapmanıza gerek yok.
* **SSL sertifika hatası:** `veri_paketi_olustur.py` ve `url_toplayici.py` `certifi` CA paketini
  otomatik kullanır; yine de hata alırsanız `pip install --upgrade certifi` deneyin.
* **Lisans/atıf:** Toplanan görsellerin çoğu Creative Commons'tır; AI eğitimi ve yayımda
  `lisans` sütunundaki atıf şartlarını yerine getirin. Ticari kullanım için `lisans` sütununu
  filtreleyin (ör. yalnızca `CC0`, `CC BY`).
* **Kotalar:** Openverse anonim kullanım için günlük kota uygular; büyük işlerde
  `--kaynak wikimedia` ile Commons'a yönelebilir veya listeyi kendi URL'lerinizle genişletebilirsiniz.
* **Büyük veri setleri:** 1M+ görselde `veri/<ad>/ham/` içindeki shard yapısını koruyup
  `manifest.csv`'yi parquet'e çevirmek daha pratiktir; img2dataset bu ölçekte `webdataset`
  (tar) formatını önerir.