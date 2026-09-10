# 2GIS Email Discovery Project — Astra Working Brief

## Proje Özü

2GIS (2gis.com), Rusya merkezli bir işletme rehberi. Veritabanında **5.64 milyon şirket** var. Bu şirketlerin çoğunda website var ama email yok. Biz bu şirketlerin website'lerini crawl ederek **gerçek email adreslerini** buluyoruz.

Şu ana kadar **246,456 email** keşfedildi (%4.37 hit rate). Hâlâ **861,886 şirket** email bekliyor.

## Ne Yapmanı İstiyoruz

Senin görevin: `companies_no_email.csv.gz` dosyasındaki şirketlerin website'lerini crawl edip email bulmak.

## Veri Setleri

### 1. `companies_with_emails.csv.gz` (6.9 MB — 320,453 satır)
Bizim daha önce bulduğumuz emailler. Bu dosyayı referans olarak kullan — aynı email'leri tekrar bulmana gerek yok.

Sütunlar: `company_id, company_name, website, email, source_url, source_type, city, country, sector`

### 2. `companies_no_email.csv.gz` (58.7 MB — 2,411,936 satır)
**Senin çalışman gereken dosya.** Bu şirketlerin henüz email'i yok.

Sütunlar: `company_id, company_name, website, phone, city, country, sector`

**Önemli:** Bu dosyadaki şirketlerin hepsinin `website` alanı var (`http://...` ile başlıyor). Email'leri yok (`has_email=0`). Daha önce crawl edilmemiş veya email bulunamamış.

## Nasıl Email Bulunur

Her şirket için websitesine gidip şu kaynaklarda email ara:

1. **Sayfa HTML'inde** `mailto:` linkleri
2. **Contact/İletişim sayfaları** — genellikle `/contacts`, `/contact`, `/about`, `/kontakty` path'lerinde
3. **Footer** — alt bilgi kısmında email
4. **Raw HTML** — `info@domain.com`, `sales@domain.com`, `mail@gmail.com` gibi pattern'ler
5. **Telefon numaraları yakınında** — genellikle email ile birlikte bulunur

### Dikkat Edilmesi Gerekenler

- **SADECE gerçek email'leri al** — `test@`, `example@`, `noreply@` gibi fake email'leri alma
- **URL tahmin etme** — `/contact` gibi path'leri tahmin etme, sadece site içindeki linkleri takip et
- **Max 18 sayfa crawl et** — her şirket için en fazla 18 sayfa tara
- **Timeout 10 saniye** — site açılmıyorsa atla
- **Messenger linklerini atlama** — t.me, max.ru, jivo.chat, tilda.ws olanları tarama

## Çıktı Formatı

Bulduğun email'leri şu formatta kaydet:

```csv
company_id,company_name,website,email,source_url,source_type
12345,Örnek Firma,http://example.com,info@example.com,http://example.com/contacts,website
```

- `source_type`: email'in bulunduğu yer (`website`, `search`, `social`)
- `source_url`: email'in bulunduğu tam URL
- `email`: küçük harfe çevir, trimle
- `UNIQUE`: aynı company_id + email kombinasyonunu tekrarlama

## İlerleme Takibi

Her 500 şirkette bir:
1. Bulunan email'leri CSV'ye yaz
2. Kaç şirket işlendiğini, kaç email bulunduğunu raporla
3. Hata oranı varsa belirt

## Örnek Başarılı Buluşlar

Daha önceki batch'lerde şu tür emailler bulundu:
- `sales@paramerus.com` — iletişim sayfasından
- `ufa@centrsvet.ru` — contact sayfasından
- `zakaz@samenural.ru` — ana sayfa footer'dan
- `info@monitor-dv.ru` — kontakt sayfasından
- `gostev@metprof.ru` — contacts sayfasından

## Hız ve Verimlilik

- Bizim crawler'ımız batch başına 500 şirketi **3-5 saat**te işliyor (şirket başına ~30-40 sn)
- Hit rate: %55-72 (her 100 şirketten 55-72'sinde email bulunuyor)
- Ortalama şirket başına 2.3-2.6 email
- Sen daha hızlı olabilirsin — biz tek worker, sıralı processing yapıyoruz

## Ne Zaman Dur

- Tüm 2.4M şirket işlendiğinde
- Veya hit rate çok düştüğünde (< %10, 1000 şirket arka arkaya email bulamıyorsa)

## Sonuç

Bulduğun email'leri `companies_with_emails_found_by_astra.csv` olarak kaydet, GitHub'a push et. Biz de `git pull` ile çekip veritabanına ekleyeceğiz.

**Soru varsa README.md dosyasına bak: https://github.com/worldwidetradex4/2gis-email-discovery**
