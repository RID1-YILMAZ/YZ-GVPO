#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
veri_paketi_olustur.py — img2dataset tabanlı veri paketi oluşturucu.

Akış:
  1. urls/*.csv içindeki URL listesini img2dataset ile indirir
     (yeniden boyutlandırma, çoklu iş parçacığı, kaldığı yerden devam).
  2. İndirilen görselleri tek bir klasörde toplar (veri/goruntuler/).
  3. Tekrar edenleri SHA-256 ile eler, bozuk/küçük görselleri ayıklar.
  4. veri/manifest.csv + veri/ozet.json üretir (AI platformuna yüklenebilir paket).

Kullanım:
  python3 scriptler/veri_paketi_olustur.py --girdi urls/kedi.csv --ad kedi
  python3 scriptler/veri_paketi_olustur.py --girdi urls/kedi.csv --boyut 512 --is-sayisi 8
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import ssl
import sys
import tarfile


def _ssl_duzenle():
    """Bazı ortamlarda Python varsayılan CA paketini bulamaz; certifi ile düzelt."""
    if ssl.get_default_verify_paths().cafile:
        return
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        for yol in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
            if os.path.exists(yol):
                os.environ.setdefault("SSL_CERT_FILE", yol)
                break


_ssl_duzenle()

# Pillow img2dataset ile gelir; yedek olarak buradan da import edilir.
try:
    from PIL import Image
except ImportError:
    print("Pillow bulunamadı: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def img2dataset_calistir(girdi, cikti_klasoru, boyut, is_sayisi, min_boyut):
    """img2dataset kütüphanesini doğrudan Python API'siyle çalıştırır."""
    # /dev/shm olmayan ortamlar için iş parçacığı yamasını uygula
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import img2dataset_yama
    img2dataset_yama.yamala()

    from img2dataset import download

    print("img2dataset çalıştırılıyor: %s -> %s" % (girdi, cikti_klasoru))
    download(
        url_list=os.path.abspath(girdi),
        input_format="parquet" if girdi.endswith(".parquet") else "csv",
        url_col="url",
        caption_col="caption",
        output_folder=cikti_klasoru,
        output_format="files",
        image_size=boyut,
        resize_mode="center_crop",
        resize_only_if_bigger=False,
        encode_format="jpg",
        encode_quality=95,
        processes_count=max(1, is_sayisi // 2),
        thread_count=max(4, is_sayisi * 4),
        number_sample_per_shard=1000,
        save_additional_columns=["kaynak", "lisans", "sayfa", "arama"],
        compute_hash="sha256",
        extract_exif=True,
        min_image_size=min_boyut,
        timeout=15,
        enable_wandb=False,
        incremental_mode="incremental",  # kaldığı yerden devam
    )


def tarlari_ac(kaynak_klasor, hedef_klasor):
    """webdataset tar arşivlerini düz klasöre açar; (dosya_yolu, meta) listesi döndürür."""
    os.makedirs(hedef_klasor, exist_ok=True)
    kayitlar = []
    for kok, _, dosyalar in os.walk(kaynak_klasor):
        for ad in sorted(dosyalar):
            yol = os.path.join(kok, ad)
            if not ad.endswith(".tar"):
                continue
            with tarfile.open(yol) as tf:
                for uyelik in tf.getmembers():
                    if not uyelik.isfile():
                        continue
                    veri = tf.extractfile(uyelik).read()
                    hedef_yol = os.path.join(hedef_klasor, os.path.basename(uyelik.name))
                    with open(hedef_yol, "wb") as f:
                        f.write(veri)
                    if hedef_yol.endswith(".json"):
                        try:
                            kayitlar.append((hedef_yol, json.loads(veri.decode("utf-8"))))
                        except Exception:
                            pass
    return kayitlar


def dosyalari_tara(klasor):
    """files çıktısındaki düz görselleri ve yanlarındaki .json meta dosyalarını eşler."""
    kayitlar = []
    for kok, _, dosyalar in os.walk(klasor):
        for ad in sorted(dosyalar):
            if not (ad.endswith(".jpg") or ad.endswith(".png") or ad.endswith(".webp")):
                continue
            yol = os.path.join(kok, ad)
            meta_yol = os.path.splitext(yol)[0] + ".json"
            meta = {}
            if os.path.exists(meta_yol):
                try:
                    with open(meta_yol, encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            kayitlar.append((yol, meta))
    return kayitlar


def isle_ve_paketle(indirme_klasoru, veri_klasoru, min_boyut):
    """Görselleri ayıklar, tekilleştirir, manifest.csv + ozet.json üretir."""
    goruntu_klasoru = os.path.join(veri_klasoru, "goruntuler")
    os.makedirs(goruntu_klasoru, exist_ok=True)

    # Hem tar arşivleri hem düz dosyalar varsa ikisini de tara, json meta olanı öncelikli.
    adaylar = dosyalari_tara(indirme_klasoru)
    if not adaylar:
        adaylar = tarlari_ac(indirme_klasoru, goruntu_klasoru)

    gorulen_hash = set()
    manifest = []
    atlanan = {"bozuk": 0, "kucuk": 0, "tekrar": 0}

    for kaynak_yol, meta in adaylar:
        try:
            with open(kaynak_yol, "rb") as f:
                ham = f.read()
            ozet = hashlib.sha256(ham).hexdigest()
            if ozet in gorulen_hash:
                atlanan["tekrar"] += 1
                continue
            with open(kaynak_yol, "rb") as f:
                with Image.open(f) as im:
                    genislik, yukseklik = im.size
                    im.verify()
            if genislik < min_boyut or yukseklik < min_boyut:
                atlanan["kucuk"] += 1
                continue
        except Exception:
            atlanan["bozuk"] += 1
            continue

        gorulen_hash.add(ozet)
        ad = "%s_%s" % (ozet[:12], os.path.basename(kaynak_yol))
        hedef = os.path.join(goruntu_klasoru, ad)
        if os.path.abspath(kaynak_yol) != os.path.abspath(hedef):
            shutil.copy2(kaynak_yol, hedef)

        manifest.append(
            {
                "dosya": os.path.join("goruntuler", ad),
                "url": meta.get("url", ""),
                "caption": meta.get("caption", meta.get("original_caption", "")),
                "kaynak": meta.get("kaynak", ""),
                "lisans": meta.get("lisans", ""),
                "genislik": genislik,
                "yukseklik": yukseklik,
                "sha256": ozet,
            }
        )

    manifest_yolu = os.path.join(veri_klasoru, "manifest.csv")
    alanlar = ["dosya", "url", "caption", "kaynak", "lisans", "genislik", "yukseklik", "sha256"]
    with open(manifest_yolu, "w", newline="", encoding="utf-8") as f:
        yazici = csv.DictWriter(f, fieldnames=alanlar)
        yazici.writeheader()
        for k in manifest:
            yazici.writerow(k)

    ozet = {
        "gecerli_gorsel": len(manifest),
        "atlanan": atlanan,
        "goruntu_klasoru": goruntu_klasoru,
        "manifest": manifest_yolu,
    }
    with open(os.path.join(veri_klasoru, "ozet.json"), "w", encoding="utf-8") as f:
        json.dump(ozet, f, ensure_ascii=False, indent=2)
    return ozet


def main():
    p = argparse.ArgumentParser(description="img2dataset ile veri paketi oluşturucu")
    p.add_argument("--girdi", required=True, help="URL listesi CSV'si (url, caption sütunlu)")
    p.add_argument("--ad", default="veri_paketi", help="Paket adı (çıktı klasörü veri/<ad> olur)")
    p.add_argument("--boyut", type=int, default=512, help="Görsel boyutu (kısa kenar)")
    p.add_argument("--is-sayisi", type=int, default=4, help="Eşzamanlı iş parçacığı sayısı")
    p.add_argument("--min-boyut", type=int, default=128, help="Bu boyuttan küçük görselleri ele (px)")
    p.add_argument("--ham-temizle", action="store_true", help="İşlemden sonra ham indirme klasörünü sil")
    args = p.parse_args()

    if not os.path.exists(args.girdi):
        print("Girdi dosyası yok: %s" % args.girdi, file=sys.stderr)
        sys.exit(1)

    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    indirme_klasoru = os.path.join(kok, "veri", args.ad, "ham")
    veri_klasoru = os.path.join(kok, "veri", args.ad)

    img2dataset_calistir(args.girdi, indirme_klasoru, args.boyut, args.is_sayisi, args.min_boyut)
    ozet = isle_ve_paketle(indirme_klasoru, veri_klasoru, args.min_boyut)

    if args.ham_temizle:
        shutil.rmtree(indirme_klasoru, ignore_errors=True)

    print("\n=== Veri paketi hazır ===")
    print("Geçerli görsel : %d" % ozet["gecerli_gorsel"])
    print("Atlanan        : %s" % ozet["atlanan"])
    print("Görseller      : %s" % ozet["goruntu_klasoru"])
    print("Manifest       : %s" % ozet["manifest"])


if __name__ == "__main__":
    main()