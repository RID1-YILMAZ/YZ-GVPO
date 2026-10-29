#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
url_toplayici.py — Veri paketi için görsel URL listesi toplar.

Anahtar gerektirmeyen açık kaynaklar:
  * Openverse   (https://api.openverse.org)  — Flickr, Wikimedia, NASA vb. CC görselleri
  * Wikimedia Commons (commons.wikimedia.org) — CC / kamu malı görseller

Çıktı: urls/<isim>.csv  (img2dataset'in beklediği sütunlar: url, caption, + kaynak/lisans)
Kullanım:
  python3 scriptler/url_toplayici.py --arama "golden retriever" --adet 100
  python3 scriptler/url_toplayici.py --arama "kedi" "köpek" --kaynak her-ikisi --adet 50
"""

import argparse
import csv
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request

USER_AGENT = "veripaketiolusturma/1.0 (dataset builder; educational use)"
TIMEOUT = 30


def _ssl_baglam():
    """Güvenilir SSL bağlamı: certifi varsa onu, yoksa sistem CA paketini kullan."""
    for ca_yolu in (None, "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        try:
            if ca_yolu is None:
                import certifi  # noqa
                ca_yolu = certifi.where()
            return ssl.create_default_context(cafile=ca_yolu)
        except Exception:
            continue
    return ssl.create_default_context()


SSL_BAGLAM = _ssl_baglam()


def _http_json(url):
    """Basit GET isteği, JSON döndürür."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_BAGLAM) as resp:
        return json.loads(resp.read().decode("utf-8"))


def openverse_arama(sorgu, adet):
    """Openverse üzerinden lisanslı görsel URL'leri toplar."""
    sonuclar = []
    sayfa = 1
    sayfa_basina = 20  # Openverse anonim limiti
    while len(sonuclar) < adet and sayfa <= 20:
        url = (
            "https://api.openverse.org/v1/images/?"
            + urllib.parse.urlencode(
                {
                    "q": sorgu,
                    "page": sayfa,
                    "page_size": sayfa_basina,
                    "license_type": "all-cc",  # ticari kullanım dahil tüm CC lisansları
                    "size": "large",
                    "mature": "false",
                }
            )
        )
        try:
            veri = _http_json(url)
        except Exception as hata:
            print("  [uyarı] Openverse isteği başarısız: %s" % hata, file=sys.stderr)
            break
        sonuc_listesi = veri.get("results", [])
        if not sonuc_listesi:
            break
        for s in sonuc_listesi:
            goruntu_url = s.get("url")
            if not goruntu_url:
                continue
            sonuclar.append(
                {
                    "url": goruntu_url,
                    "caption": (s.get("title") or sorgu).strip(),
                    "kaynak": s.get("source") or "openverse",
                    "lisans": "%s %s" % (s.get("license", ""), s.get("license_version", "") or ""),
                    "sayfa": s.get("foreign_landing_url", ""),
                    "arama": sorgu,
                }
            )
            if len(sonuclar) >= adet:
                break
        sayfa += 1
        time.sleep(0.5)
    return sonuclar


def wikimedia_arama(sorgu, adet, genislik=1600):
    """Wikimedia Commons araması; boyutlandırılmış kopya (thumb) URL'leri döndürür."""
    sonuclar = []
    devam = ""
    while len(sonuclar) < adet:
        url = (
            "https://commons.wikimedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": "filetype:bitmap %s" % sorgu,
                    "gsrnamespace": "6",
                    "gsrlimit": str(min(50, adet - len(sonuclar))),
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata|size",
                    "iiurlwidth": str(genislik),
                    "format": "json",
                    "gsroffset": devam or "0",
                }
            )
        )
        try:
            veri = _http_json(url)
        except Exception as hata:
            print("  [uyarı] Wikimedia isteği başarısız: %s" % hata, file=sys.stderr)
            break
        sayfalar = (veri.get("query") or {}).get("pages") or {}
        if not sayfalar:
            break
        for sayfa in sayfalar.values():
            bilgi = (sayfa.get("imageinfo") or [{}])[0]
            goruntu_url = bilgi.get("thumburl") or bilgi.get("url")
            if not goruntu_url:
                continue
            meta = bilgi.get("extmetadata") or {}
            lisans = (meta.get("LicenseShortName", {}).get("value") or "").strip()
            aciklama = (meta.get("ImageDescription", {}).get("value") or "").strip()
            # HTML etiketlerini kaba biçimde temizle
            aciklama = aciklama.replace("<p>", " ").replace("</p>", " ")
            if "<" in aciklama:
                aciklama = "".join(
                    parca for parca in _etiket_ayir(aciklama) if not parca.startswith("<")
                )
            sonuclar.append(
                {
                    "url": goruntu_url,
                    "caption": (sayfa.get("title", "").replace("File:", "") or sorgu).strip(),
                    "kaynak": "wikimedia commons",
                    "lisans": lisans,
                    "sayfa": bilgi.get("descriptionurl", ""),
                    "arama": sorgu,
                }
            )
            if len(sonuclar) >= adet:
                break
        devam = str(int(devam or 0) + 50)
        if int(devam) > 400:  # Commons arama derinliği sınırı
            break
        time.sleep(0.3)
    return sonuclar


def _etiket_ayir(metin):
    """Basit HTML etiket ayırıcı (yardımcı)."""
    parcalar = []
    kalan = metin
    while "<" in kalan:
        on, kalan = kalan.split("<", 1)
        parcalar.append(on)
        if ">" in kalan:
            etiket, kalan = kalan.split(">", 1)
            parcalar.append("<" + etiket + ">")
    parcalar.append(kalan)
    return parcalar


def csv_yaz(kayitlar, dosya_yolu):
    alanlar = ["url", "caption", "kaynak", "lisans", "sayfa", "arama"]
    with open(dosya_yolu, "w", newline="", encoding="utf-8") as f:
        yazici = csv.DictWriter(f, fieldnames=alanlar)
        yazici.writeheader()
        for k in kayitlar:
            yazici.writerow({a: k.get(a, "") for a in alanlar})


def main():
    p = argparse.ArgumentParser(description="Veri paketi için görsel URL toplayıcı")
    p.add_argument("--arama", nargs="+", required=True, help="Arama terimleri (bir veya daha fazla)")
    p.add_argument("--adet", type=int, default=100, help="Arama terimi başına istenen görsel sayısı")
    p.add_argument(
        "--kaynak",
        choices=["openverse", "wikimedia", "her-ikisi"],
        default="her-ikisi",
        help="Hangi kaynak(lar) kullanılsın",
    )
    p.add_argument("--cikti", default=None, help="Çıktı CSV yolu (varsayılan: urls/<arama>.csv)")
    args = p.parse_args()

    tumu = []
    for sorgu in args.arama:
        print("Aranıyor: %s (kaynak: %s, hedef: %d)" % (sorgu, args.kaynak, args.adet))
        bulunan = []
        if args.kaynak in ("openverse", "her-ikisi"):
            o = openverse_arama(sorgu, args.adet)
            print("  Openverse: %d görsel" % len(o))
            bulunan.extend(o)
        if args.kaynak in ("wikimedia", "her-ikisi"):
            w = wikimedia_arama(sorgu, args.adet)
            print("  Wikimedia Commons: %d görsel" % len(w))
            bulunan.extend(w)
        tumu.extend(bulunan)

    # Tekrar eden URL'leri ele
    gorulen = set()
    benzersiz = []
    for k in tumu:
        if k["url"] not in gorulen:
            gorulen.add(k["url"])
            benzersiz.append(k)

    if not benzersiz:
        print("Hiç görsel bulunamadı; ağ bağlantısını ve arama terimlerini kontrol edin.", file=sys.stderr)
        sys.exit(1)

    cikti = args.cikti or ("urls/" + args.arama[0].replace(" ", "_") + ".csv")
    csv_yaz(benzersiz, cikti)
    print("Toplam %d benzersiz URL → %s" % (len(benzersiz), cikti))
    print("Sonraki adım: python3 scriptler/veri_paketi_olustur.py --girdi %s" % cikti)


if __name__ == "__main__":
    main()