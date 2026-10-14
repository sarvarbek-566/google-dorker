# 🔍 Google Dorker

**Google Dorker** — bitta domen kiritasiz, dastur esa o'zi tayyor *Google dork* so'rovlarini yaratib, chiroyli HTML hisobot beradi. Bu **passive OSINT recon** vositasi: targetga hech qanday to'g'ridan-to'g'ri so'rov yuborilmaydi, faqat qidiruv tizimlarining ommaviy indeksidan foydalaniladi.

> ⚠️ **Ogohlantirish:** faqat o'zingizga tegishli yoki yozma ruxsat berilgan targetlarda ishlating (bug bounty scope, shartnoma, TryHackMe/HTB kabi lablar). Mas'uliyat to'liq foydalanuvchida.

---

## 📖 Bu nima va nega kerak?

**Google dork** — Google'ning maxsus operatorlari (`site:`, `inurl:`, `filetype:`, `intitle:` ...) yordamida oddiy qidiruv bilan topib bo'lmaydigan narsalarni topish usuli. Masalan:

| Dork | Nima topadi |
|------|-------------|
| `site:example.com inurl:admin` | Admin panel sahifalari |
| `site:example.com filetype:sql` | Ochiq qolgan database dumplar |
| `site:example.com intitle:"index of"` | Ochiq papkalar (directory listing) |
| `site:example.com filetype:env` | Maxfiy konfiguratsiya fayllari |

Pentester yoki bug bounty ovchisi uchun bu **recon (razvedka)** bosqichining birinchi qadami. Qo'lda yuzlab dork yozib chiqish o'rniga, bu dastur ularni sizning o'rningizga tayyorlaydi.

## ✨ Imkoniyatlar

- 🎯 **Faqat bitta narsa so'raydi** — target domen (`example.com`).
- 📂 **11 ta kategoriya, 40+ tayyor dork:** login/admin panellar, directory listing, konfiguratsiya fayllari, database/backup, log fayllar, xatolik sahifalari, API va dev muhitlar, parametrli URL'lar, tashqi saytlardagi sizib chiqishlar (leaks), subdomenlar va h.k.
- 🚦 **Har bir dorkka xavf darajasi:** `YUQORI` / `O'RTA` / `INFO`.
- 🌐 **Har bir dork uchun tayyor havolalar** — Google, Bing, DuckDuckGo, Yandex (bir bosishda brauzerda ochiladi).
- 🤖 **Avtomat natija olish** (ixtiyoriy): Google Custom Search API yoki SearXNG orqali.
- 📊 **Chiroyli HTML dashboard:** qidiruv filtri, "nusxa olish" tugmasi, dark mode.
- 💾 **3 xil hisobot:** `.html`, `.txt`, `.json`.

## ⚙️ Qanday ishlaydi?

```
Domen kiritiladi
      │
      ▼
Kategoriyalar bo'yicha dorklar yasaladi   (site:example.com inurl:admin ...)
      │
      ▼
Natija olish rejimi avtomat tanlanadi:
   1) Google CSE API kaliti bor  → avtomat natijalar (eng ishonchli)
   2) Kalit yo'q, SearXNG ishlaydi → best-effort natijalar
   3) Ikkalasi ham bloklangan     → faqat clickable havolalar
      │
      ▼
HTML + TXT + JSON hisobot saqlanadi, HTML brauzerda ochiladi
```

**Nega 3 xil rejim?** Google, Bing va boshqalar avtomatik so'rovlarni anti-bot himoya bilan bloklaydi. Shuning uchun *har doim ishlaydigan* yo'l — dashboarddagi havolalar: ularni **sizning brauzeringiz** ochadi, demak hech qachon bloklanmaydi.

## 🚀 O'rnatish

Talab: **Python 3.8+**

```bash
git clone https://github.com/sarvarbek-566/google-dorker.git
cd google-dorker
pip install -r requirements.txt
```

## 🧪 Foydalanish

```bash
# Interaktiv: dastur o'zi domen so'raydi
python3 main.py

# Domenni to'g'ridan-to'g'ri berish
python3 main.py -d example.com

# Brauzerni avtomat ochmaslik
python3 main.py -d example.com --no-open

# Faqat bitta kategoriya
python3 main.py -d example.com -c "Login va admin panellar"

# Mavjud kategoriyalar ro'yxati
python3 main.py --list-categories
```

### Barcha parametrlar

| Parametr | Ma'nosi | Default |
|----------|---------|---------|
| `-d`, `--domain` | Target domen | so'raladi |
| `-c`, `--categories` | Faqat shu kategoriyalar | hammasi |
| `-o`, `--output` | Hisobot fayl nomi (kengaytmasiz) | `dorks_<domen>` |
| `--engine` | `auto`, `cse`, `searxng`, `links` | `auto` |
| `--delay` | Live so'rovlar orasidagi kutish (soniya) | `2` |
| `--limit` | Har bir dork uchun maksimal natija | `8` |
| `--timeout` | So'rov timeouti (soniya) | `15` |
| `--no-open` | HTML'ni brauzerda ochmaslik | o'chiq |
| `--list-categories` | Kategoriyalarni ko'rsatib chiqish | — |

## 🔑 Google CSE API'ni yoqish (ixtiyoriy)

Natijalarni avtomat olish uchun (bepul kvota: **kuniga 100 so'rov**):

1. **API kalit** oling: <https://developers.google.com/custom-search/v1/introduction> → "Get a Key".
2. **Search Engine ID (cx)** oling: <https://programmablesearchengine.google.com/> → "Add" → *"Search the entire web"* ni yoqing.
3. Kalitlarni quyidagi usullardan biri bilan bering:

   **a) Environment variable:**
   ```bash
   export GOOGLE_API_KEY="AIza..."
   export GOOGLE_CSE_ID="0123:abcd"
   ```

   **b) Config fayl** `~/.config/google-dorker/config.json`:
   ```json
   {"api_key": "AIza...", "cse_id": "0123:abcd"}
   ```

   **c) `.env` fayl** (loyiha papkasida):
   ```
   GOOGLE_API_KEY=AIza...
   GOOGLE_CSE_ID=0123:abcd
   ```

> 🔒 API kalitingizni hech qachon GitHub'ga yuklamang. `.env` fayl `.gitignore`da allaqachon bor.

## 📁 Natija fayllari

Skaner tugagach quyidagilar yaratiladi (masalan `example.com` uchun):

| Fayl | Vazifasi |
|------|----------|
| `dorks_example_com.html` | Asosiy dashboard — brauzerda ochiladi |
| `dorks_example_com.txt` | Oddiy matnli hisobot |
| `dorks_example_com.json` | Boshqa vositalar uchun mashina o'qiydigan format |

## 🛡️ Huquqiy eslatma

Bu vosita faqat **ta'lim, mudofaa va ruxsat berilgan xavfsizlik tekshiruvlari** uchun. Dorklar ommaviy indekslangan sahifalarni topadi, lekin topilgan ma'lumotdan ruxsatsiz foydalanish qonunbuzarlikdir. Muallif noto'g'ri ishlatilishi uchun javobgar emas.

## 🤝 Hissa qo'shish

Yangi dork kategoriyalari yoki yaxshilanishlar uchun Pull Request yoki Issue oching. Yangi dork qo'shish uchun `main.py` dagi `DORKS` lug'atiga yozuv qo'shish kifoya.
