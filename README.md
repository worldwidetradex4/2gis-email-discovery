# 2GIS B2B Real Email Discovery System

> Otonom email keşif sistemi — 2GIS veritabanında websitesi olan ama email'i olmayan B2B şirketlerinden gerçek email adreslerini keşfeder.

---

## Güncel İstatistikler (10 Eylül 2026)

| Metrik | Değer |
|---|---|
| Toplam şirket | 5,640,436 |
| Email keşfedilen şirket | **246,456** |
| Keşif oranı | **%4.37** |
| Kalan eligible şirket | 861,886 |
| Son tamamlanan batch | BATCH-75 |
| Toplam batch | 76 (hâlâ çalışıyor) |
| Hata oranı | %0 |

---

## Ülke Bazlı İlerleme

| Ülke | cid | Toplam | Email | Tükenmiş | Hâlâ Eligible | Email % |
|---|---:|---:|---:|---:|---:|---:|
| Russia | 1 | 3,750,359 | 178,618 | 28,508 | 3,543,233 | 4.76% |
| Kazakhstan | 2 | 1,078,769 | 54,305 | 6,270 | 1,018,194 | 5.03% |
| Kyrgyzstan | 5 | 333,979 | 8,172 | 0 | 325,807 | 2.45% |
| Azerbaijan | 6 | 89,247 | 2 | 0 | 89,245 | 0.00% |
| Belarus | 4 | 85,189 | 931 | 0 | 84,258 | 1.09% |
| Czechia | 7 | 81,186 | 0 | 0 | 81,186 | 0.00% |
| Chile | 8 | 78,325 | 0 | 0 | 78,325 | 0.00% |
| Georgia | 10 | 63,237 | 873 | 439 | 61,925 | 1.38% |
| (ülkesiz) | - | 41,833 | 1,554 | 81 | 40,198 | 3.72% |
| Uzbekistan | 3 | 38,312 | 102 | 0 | 38,210 | 0.27% |

**Not:** Crawler global sırayla çalıştığı için iş çoğunlukla Russia ve Kazakhstan'ta yoğunlaşmış. 6 ülke (Kyrgyzstan, Azerbaijan, Belarus, Czechia, Chile, Uzbekistan) henüz hiç dokunulmamış.

---

## Nasıl Çalışır

### Otonom Döngü

```
supervisor.sh → loop_driver.sh → email_finder.py (500 şirket) → master.py (QC) → tekrar
```

1. **supervisor.sh**: Tek driver'ın çalıştığından emin olur (15 saniyede bir kontrol)
2. **loop_driver.sh**: Her batch'te 500 şirket seçer → crawler'ı başlatır → QC scripti çalıştırır → bir sonraki batch'e geçer
3. **email_finder.py**: Tek worker, sıralı BFS. Her şirket için website'yi crawl eder, gerçek email'leri `mailto:`, `@domain.com` pattern'lerinden çeker
4. **master.py**: Batch sonunda kalite kontrol — duplicate temizleme, false positive reddetme, source validation

### Başlatma

```bash
# Driver'ı arka planda başlat
nohup bash loop_driver.sh > driver_main.log 2>&1 &
disown

# Supervisor'ı başlat
nohup bash supervisor.sh > supervisor.log 2>&1 &
disown
```

### Durdurma

```bash
# Tüm process'leri öldür
powershell -NoProfile -ExecutionPolicy Bypass -File kill_loop.ps1
```

### Durum Kontrolü

```bash
# Çalışan process'leri listele
powershell -NoProfile -ExecutionPolicy Bypass -File check_loop.ps1

# İlerlemeyi kontrol et
python3 -c "import json;d=json.load(open('MASTER_PROGRESS.json'));print(d)"
```

---

## Veritabanı Şeması (SQLite — 2GB)

```
2gis.db
├── companies          — 5.64M şirket (id, name, website, city_id, has_email)
├── sectors            — Sektör listesi
├── cities             — Şehir listesi (id, name, country_id)
├── countries          — Ülke listesi (id, name, iso2)
├── company_emails     — Keşfedilen emailler (company_id, email, source, UNIQUE)
├── email_jobs         — İşlenen şirket kaydı (company_id, status, emails_found)
├── crawled_hosts      — Host dedup tablosu
└── cleanup_audit      — Temizlik denetim kayıtları
```

### Temel Sorgular

```sql
-- Email bulunan şirketler
SELECT co.name, ce.email, ce.source
FROM companies co
JOIN company_emails ce ON ce.company_id = co.id
WHERE co.has_email = 1
ORDER BY co.id DESC
LIMIT 100;

-- Ülke bazlı ilerleme
SELECT cn.name, COUNT(*) as emailed
FROM company_emails ce
JOIN companies co ON co.id = ce.company_id
JOIN cities ci ON ci.id = co.city_id
JOIN countries cn ON cn.id = ci.country_id
GROUP BY cn.id ORDER BY emailed DESC;

-- Eligible şirketler (hâlâ işlenmemiş)
SELECT COUNT(*) FROM companies
WHERE website LIKE 'http%'
AND has_email = 0
AND id NOT IN (SELECT company_id FROM email_jobs
               WHERE status IN ('completed','no_email_found',
                                'website_unavailable','error','blocked',
                                'duplicate_host','excluded_platform'));
```

---

## Güvenlik Kuralları (MASTER SPEC V5.0 — Değiştirilemez)

Bu kurallar proje boyunca KESİNLİKLE uygulanır:

| Kural | Açıklama |
|---|---|
| ASLA email tahmin etme | Domain'den email üretme, rol bazlı filtreleme |
| ASLA URL tahmin etme | `/contact` gibi path'ler üretilmez |
| 500 = 500 paralel DEĞİL | Tek worker, sıralı processing |
| DB yazma koruması | Dolu `companies.email` alanının üzerine ASLA yazma |
| UNIQUE koruma | `UNIQUE(company_id, email)` constraint korunmalı |
| REAL EMAIL + REAL SOURCE | Her email'in kaynak URL'si olmalı |
| ASLA TOPLU SİLEME | Cleanup sırasında gerçek email'leri topluca silme |
| Web search sadece email varsa | BRAVE_API_KEY yoksa devre dışı |
| Messenger domains yasak | t.me, max.ru, jivo.chat, tilda.ws crawler edilmez |

---

## Batch İşlem Özeti

Her batch 500 şirket işler. Tipik bir batch sonucu:

- **Hit rate:** %55-72 (şirket başına ortalama 2.3-2.6 email)
- **Süre:** 3-5 saat (şirket başına ~30-40 saniye)
- **Hata:** 0 (tolere edilmez, otomatik retry)
- **False positive:** ~900-1400/red (image TLD, phone-as-email, platform-internal)

### Son Batch Örnekleri

| Batch | Hit Rate | Email | FP Reddedilen |
|---|---|---|---|
| BATCH-55 | %54.8 (274/500) | 705 | 923 |
| BATCH-59 | %72.0 (360/500) | 832 | 1,468 |
| BATCH-75 | ~%55 | ~700 | ~1,000 |

---

## Dosya Yapısı

| Dosya | Amaç |
|---|---|
| `email_finder.py` | Ana crawler — BFS ile website crawl, email extraction |
| `loop_driver.sh` | Otonom döngü sürücüsü — batch seçimi, QC tetikleme |
| `supervisor.sh` | Driver monitor — tek driver guarantee |
| `master.py` | QC script — post-batch kalite kontrol |
| `MASTER_SPECIFICATION.md` | Tam teknik spesifikasyon (V5.0) |
| `MASTER_PROGRESS.json` | Çalışma durumu (runtime state) |
| `kill_loop.ps1` | Tüm process'leri durdurma |
| `check_loop.ps1` | Process sağlık kontrolü |
| `2gis.db` | Ana veritabanı (2GB, Git'e dahil DEĞİL) |

---

## Tech Stack

- **Dil:** Python 3.14, Bash, PowerShell
- **DB:** SQLite (WAL mode, busy_timeout=30s)
- **OS:** Windows 11, Git Bash
- **Network:** aiohttp (async HTTP), charset-normalizer
- **Spec:** MASTER SPECIFICATION V5.0

---

## Devam Etmek İçin

Bu sistem **BATCH-75'te** ve **861,886** şirket hâlâ eligible. Devam etmek için:

1. Veritabanını kopyala (`2gis.db` — 2GB)
2. `email_finder.py`, `loop_driver.sh`, `supervisor.sh`, `master.py` dosyalarını çalıştırılabilir ortama koy
3. `MASTER_PROGRESS.json`'ı sıfırla veya olduğu yerden devam et
4. `nohup bash loop_driver.sh > driver_main.log 2>&1 &` ile başlat

---

**Last Updated:** 2026-09-10
**Version:** 2.0.0
**Status:** Production — Autonomous Loop Running
