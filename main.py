#!/usr/bin/env python3
"""
Google Dorker — professional OSINT recon vositasi.

Sizdan FAQAT bitta narsa so'raydi: target sayt (masalan example.com).
Qolgan hamma ishni o'zi qiladi.

ISHLASH TARTIBI
---------------
1. Target domen uchun keng, kategoriyalarga ajratilgan dork to'plamini
   tayyorlaydi (login panellar, ochiq fayllar, konfiguratsiya, backup,
   directory listing, xatolik sahifalari, sizib chiqishlar va h.k.).
2. Natijalarni OLISHGA harakat qiladi (ikki yo'l bilan):
     a) Google Custom Search API — agar kalit sozlangan bo'lsa (ENG ISHONCHLI,
        hech qachon bloklanmaydi). Sozlash 2 daqiqa — pastdagi izohga qarang.
     b) SearXNG meta-qidiruv — kalitsiz, best-effort. Ba'zi tarmoqlarda
        ishlaydi, ba'zilarida anti-bot himoya tufayli bloklanadi.
3. BLOKLANISHDAN QAT'I NAZAR — har bir dork uchun to'g'ridan-to'g'ri
   bosiladigan Google / Bing / DuckDuckGo / Yandex havolalarini o'z ichiga
   olgan chiroyli HTML dashboard yaratadi va uni brauzerda avtomat ochadi.
   Havolalarni SIZNING brauzeringiz ochadi — shuning uchun hech qachon
   bloklanmaydi. Bu "100% ishlaydi" degan halol kafolat.

NEGA SHUNDAY?
------------
2026-yilda Google, Bing, DuckDuckGo va boshqa qidiruv tizimlari avtomatik
so'rovlarni JavaScript/anti-bot challenge bilan bloklaydi. Oddiy skript
(requests) ularning natijalarini ishonchli ololmaydi. Shuning uchun:
  - ishonchli AVTOMAT natija = Google CSE API (rasmiy, bepul kvota).
  - har doim ishlaydigan yo'l = brauzerda ochiladigan clickable havolalar.

GOOGLE CSE API'NI YOQISH (ixtiyoriy, natijalarni avtomat olish uchun)
--------------------------------------------------------------------
  1. API kalit:  https://developers.google.com/custom-search/v1/introduction
                 ("Get a Key" tugmasi) → kalitni nusxa oling.
  2. Search Engine ID (cx):  https://programmablesearchengine.google.com/
                 "Add" → "Search the entire web" yoqing → cx (ID) ni oling.
  3. Keyin quyidagicha ishlating (bir martalik):
       export GOOGLE_API_KEY="AIza..."
       export GOOGLE_CSE_ID="0123:abcd"
     yoki ~/.config/google-dorker/config.json faylida saqlang:
       {"api_key": "AIza...", "cse_id": "0123:abcd"}
  Bepul kvota: kuniga 100 so'rov.

OGOHLANTIRISH
-------------
Bu passive recon vositasi. Faqat O'ZINGIZGA tegishli yoki ruxsat berilgan
targetlarda (bug bounty scope, yozma shartnoma, TryHackMe/HTB kabi lab)
ishlating. Dorklar odatda ommaviy indekslangan sahifalarni topadi, lekin
mas'uliyat butunlay foydalanuvchida.

FOYDALANISH
-----------
    python3 main.py
    python3 main.py -d example.com
    python3 main.py -d example.com --no-open        # brauzerni ochmaslik
    python3 main.py -d example.com -c "Login va admin panellar"
    python3 main.py --list-categories
"""

import argparse
import json
import os
import random
import re
import sys
import time
import webbrowser
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlparse

try:
    import requests
except ImportError:
    sys.exit("[!] 'requests' kutubxonasi kerak:  pip install requests")

# --- Qidiruv havolasi shablonlari (clickable report uchun) -----------------
ENGINES = {
    "Google": "https://www.google.com/search?q={q}",
    "Bing": "https://www.bing.com/search?q={q}",
    "DuckDuckGo": "https://duckduckgo.com/?q={q}",
    "Yandex": "https://yandex.com/search/?text={q}",
}

# Best-effort live fetch uchun ommaviy SearXNG instancelari (rotatsiya).
SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.inetol.net",
    "https://baresearch.org",
    "https://priv.au",
    "https://search.rhscz.eu",
    "https://opnxng.com",
    "https://search.hbubli.cc",
    "https://paulgo.io",
    "https://search.disroot.org",
]

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

# Kategoriya -> (severity, [dork shablonlari]).  {d} domen bilan almashtiriladi.
# severity: "high" | "med" | "info"
DORKS = {
    "Login va admin panellar": ("med", [
        "site:{d} inurl:admin",
        "site:{d} inurl:login OR inurl:signin OR inurl:auth",
        'site:{d} intitle:"dashboard" OR intitle:"control panel"',
        "site:{d} inurl:wp-admin OR inurl:wp-login",
        "site:{d} inurl:phpmyadmin OR inurl:pma",
        "site:{d} inurl:cpanel OR inurl:webmail",
    ]),
    "Directory listing (ochiq papkalar)": ("high", [
        'site:{d} intitle:"index of"',
        'site:{d} intitle:"index of" "parent directory"',
        'site:{d} intitle:"index of" (backup OR admin OR uploads OR private)',
    ]),
    "Hujjatlar": ("info", [
        "site:{d} filetype:pdf",
        "site:{d} filetype:doc OR filetype:docx",
        "site:{d} filetype:xls OR filetype:xlsx OR filetype:csv",
        "site:{d} filetype:ppt OR filetype:pptx",
        "site:{d} filetype:txt",
    ]),
    "Konfiguratsiya va maxfiy fayllar": ("high", [
        "site:{d} filetype:env OR filetype:ini OR filetype:conf OR filetype:cfg",
        "site:{d} filetype:xml OR filetype:yml OR filetype:yaml",
        "site:{d} inurl:.git OR inurl:.svn OR inurl:.env",
        'site:{d} filetype:json intext:"api_key" OR intext:"secret"',
        'site:{d} intext:"BEGIN RSA PRIVATE KEY" OR intext:"BEGIN PRIVATE KEY"',
    ]),
    "Database va backup": ("high", [
        "site:{d} filetype:sql OR filetype:db OR filetype:sqlite",
        "site:{d} filetype:bak OR filetype:old OR filetype:backup",
        "site:{d} filetype:zip OR filetype:tar OR filetype:gz OR filetype:rar",
        'site:{d} intitle:"index of" (dump OR .sql OR backup)',
    ]),
    "Log fayllar": ("med", [
        "site:{d} filetype:log",
        'site:{d} filetype:log intext:"password" OR intext:"error"',
    ]),
    "Xatolik / stack trace sahifalari": ("med", [
        'site:{d} intext:"sql syntax near" OR intext:"mysql_fetch"',
        'site:{d} intext:"Warning:" intext:"on line"',
        'site:{d} intext:"Traceback (most recent call last)"',
        'site:{d} intext:"Fatal error" OR intext:"Uncaught exception"',
    ]),
    "API va dev muhitlar": ("med", [
        "site:{d} inurl:api OR inurl:swagger OR inurl:graphql",
        "site:{d} inurl:dev OR inurl:test OR inurl:staging OR inurl:uat",
        'site:{d} inurl:wp-json',
        "site:{d} ext:json inurl:api",
    ]),
    "Parametrli URL'lar (potensial zaifliklar)": ("med", [
        "site:{d} inurl:id= OR inurl:page= OR inurl:file=",
        "site:{d} inurl:redirect= OR inurl:url= OR inurl:next= OR inurl:return=",
        "site:{d} inurl:cmd= OR inurl:exec= OR inurl:query=",
    ]),
    "Tashqi saytlarda sizib chiqish (leaks)": ("high", [
        '"{d}" site:pastebin.com',
        '"{d}" site:github.com',
        '"{d}" site:gitlab.com OR site:bitbucket.org',
        '"{d}" site:trello.com OR site:s3.amazonaws.com',
        '"@{d}" site:github.com password OR secret OR api_key',
    ]),
    "Subdomenlar va hostlar": ("info", [
        "site:*.{d} -www",
        "site:{d} -inurl:www",
    ]),
}

SEV_LABEL = {"high": "YUQORI", "med": "O'RTA", "info": "INFO"}


class C:
    """Terminal ranglari."""
    H = "\033[95m"; B = "\033[94m"; G = "\033[92m"; Y = "\033[93m"
    R = "\033[91m"; GRAY = "\033[90m"; E = "\033[0m"; BOLD = "\033[1m"


BANNER = rf"""{C.B}{C.BOLD}
  ____                   _        ____             _
 / ___| ___   ___   __ _| | ___  |  _ \  ___  _ __| | _____ _ __
| |  _ / _ \ / _ \ / _` | |/ _ \ | | | |/ _ \| '__| |/ / _ \ '__|
| |_| | (_) | (_) | (_| | |  __/ | |_| | (_) | |  |   <  __/ |
 \____|\___/ \___/ \__, |_|\___| |____/ \___/|_|  |_|\_\___|_|
                   |___/        professional OSINT dork skaneri
{C.E}"""

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


# --------------------------------------------------------------------------
# Yordamchi funksiyalar
# --------------------------------------------------------------------------
def normalize_domain(raw: str) -> str:
    """URL yoki domen kiritilsa, toza domen qismini ajratib oladi."""
    d = raw.strip().lower()
    d = re.sub(r"^\w+://", "", d)
    d = d.split("/")[0].split("@")[-1].split(":")[0]
    return d


def engine_links(dork: str) -> dict:
    q = quote_plus(dork)
    return {name: tpl.format(q=q) for name, tpl in ENGINES.items()}


# --------------------------------------------------------------------------
# Live natija olish — Google CSE (ishonchli) va SearXNG (best-effort)
# --------------------------------------------------------------------------
def load_cse_credentials():
    """API kalitini env / config.json / .env dan topadi."""
    key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    if key and cx:
        return key, cx

    cfg = Path.home() / ".config" / "google-dorker" / "config.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            k = data.get("api_key"); c = data.get("cse_id")
            if k and c:
                return k, c
        except (ValueError, OSError):
            pass

    envf = Path(".env")
    if envf.is_file():
        try:
            txt = envf.read_text(encoding="utf-8")
            k = re.search(r"GOOGLE_API_KEY\s*=\s*['\"]?([^'\"\n]+)", txt)
            c = re.search(r"GOOGLE_CSE_ID\s*=\s*['\"]?([^'\"\n]+)", txt)
            if k and c:
                return k.group(1).strip(), c.group(1).strip()
        except OSError:
            pass
    return None, None


def cse_search(session, api_key, cx, query, limit, timeout):
    """Google Custom Search API orqali qidiradi. (status, urls) qaytaradi."""
    try:
        resp = session.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query,
                    "num": min(limit, 10)},
            timeout=timeout)
    except requests.RequestException:
        return "error", []
    if resp.status_code == 429:
        return "quota", []
    if resp.status_code != 200:
        return "error", []
    try:
        items = resp.json().get("items", []) or []
    except ValueError:
        return "error", []
    urls = [it.get("link") for it in items if it.get("link")][:limit]
    return ("found" if urls else "empty"), urls


def searxng_search(session, instances, query, limit, timeout):
    """Best-effort SearXNG qidiruvi. Instancelarni navbatma-navbat sinaydi."""
    patterns = [
        re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*class="url_header"'),
        re.compile(r'<h3>\s*<a[^>]+href="(https?://[^"]+)"'),
        re.compile(r'class="result[^"]*"[^>]*>\s*<a[^>]+href="(https?://[^"]+)"'),
    ]
    for base in instances:
        headers = {"User-Agent": random.choice(USER_AGENTS),
                   "Accept": "application/json, text/html"}
        # Avval JSON
        try:
            r = session.get(f"{base}/search",
                            params={"q": query, "format": "json"},
                            headers=headers, timeout=timeout)
            if r.status_code == 200 and "json" in r.headers.get(
                    "content-type", ""):
                res = r.json().get("results", []) or []
                urls = [x.get("url") for x in res if x.get("url")][:limit]
                if urls:
                    return "found", urls, base
                return "empty", [], base
        except (requests.RequestException, ValueError):
            pass
        # Keyin HTML
        try:
            r = session.get(f"{base}/search", params={"q": query},
                            headers=headers, timeout=timeout)
            if r.status_code == 200 and "verifying your browser" \
                    not in r.text.lower():
                found, seen = [], set()
                for pat in patterns:
                    for href in pat.findall(r.text):
                        u = unescape(href)
                        if u not in seen and "searx" not in urlparse(u).netloc:
                            seen.add(u); found.append(u)
                found = found[:limit]
                if found:
                    return "found", found, base
        except requests.RequestException:
            pass
    return "blocked", [], None


def probe_searxng(session, timeout=6):
    """SearXNG ishlayotganini tez tekshiradi (2 instance)."""
    for base in SEARXNG_INSTANCES[:2]:
        st, urls, _ = searxng_search(
            session, [base], "site:wikipedia.org test", 2, timeout)
        if st == "found":
            return True
    return False


# --------------------------------------------------------------------------
# Skanerlash
# --------------------------------------------------------------------------
def run_scan(domain, categories, delay, limit, timeout, mode):
    """
    mode: "cse" | "searxng" | "links"
    Har bir dork uchun natija dict qaytaradi.
    """
    session = requests.Session()
    api_key = cx = None
    if mode == "cse":
        api_key, cx = load_cse_credentials()

    tasks = []
    for cat, (sev, templates) in DORKS.items():
        if categories and cat not in categories:
            continue
        for tpl in templates:
            tasks.append((cat, sev, tpl.format(d=domain)))

    total = len(tasks)
    mode_label = {
        "cse": "Google Custom Search API (avtomat natijalar)",
        "searxng": "SearXNG meta-qidiruv (best-effort)",
        "links": "faqat clickable havolalar (live fetch bloklangan)",
    }[mode]
    print(f"{C.G}[+] {domain} uchun {total} ta dork tayyorlandi.{C.E}")
    print(f"{C.G}[+] Rejim: {mode_label}{C.E}\n")

    results = []
    current_cat = None
    for i, (cat, sev, dork) in enumerate(tasks, 1):
        if cat != current_cat:
            print(f"{C.H}{C.BOLD}[ {cat} ]{C.E}")
            current_cat = cat

        status, urls = "links", []
        if mode == "cse":
            sys.stdout.write(f"  {C.GRAY}({i}/{total}){C.E} "
                             f"{dork[:58]:<58} ")
            sys.stdout.flush()
            status, urls = cse_search(session, api_key, cx, dork, limit, timeout)
        elif mode == "searxng":
            sys.stdout.write(f"  {C.GRAY}({i}/{total}){C.E} "
                             f"{dork[:58]:<58} ")
            sys.stdout.flush()
            status, urls, _ = searxng_search(
                session, SEARXNG_INSTANCES, dork, limit, timeout)

        results.append({
            "category": cat, "severity": sev, "dork": dork,
            "status": status, "urls": urls, "links": engine_links(dork),
        })

        if mode in ("cse", "searxng"):
            if status == "found":
                print(f"{C.G}✔ TOPILDI ({len(urls)}){C.E}")
                for u in urls:
                    print(f"       {C.B}{u}{C.E}")
            elif status == "empty":
                print(f"{C.GRAY}✘ topilmadi{C.E}")
            elif status == "quota":
                print(f"{C.Y}⚠ kvota tugadi{C.E}")
            elif status == "blocked":
                print(f"{C.Y}⚠ bloklandi{C.E}")
            else:
                print(f"{C.R}⚠ xato{C.E}")
            if i < total:
                time.sleep(delay + random.uniform(0, delay * 0.3))
        else:
            # links rejimi: jim, faqat sanaymiz
            pass

    if mode == "links":
        print(f"{C.G}[+] {total} ta dork uchun clickable havolalar "
              f"tayyorlandi.{C.E}")

    return results, mode


# --------------------------------------------------------------------------
# Hisobot
# --------------------------------------------------------------------------
def print_summary(domain, results, mode):
    found = [r for r in results if r["status"] == "found"]
    total_urls = sum(len(r["urls"]) for r in found)
    print(f"\n{C.BOLD}{'=' * 64}{C.E}")
    print(f"{C.BOLD}  XULOSA — {domain}{C.E}")
    print(f"{C.BOLD}{'=' * 64}{C.E}")
    print(f"  Jami dork        : {len(results)} ta")
    if mode in ("cse", "searxng"):
        print(f"  {C.G}Natija topildi   : {len(found)} ta dork, "
              f"{total_urls} ta URL{C.E}")
    print(f"  {C.B}Clickable havola : har bir dork uchun "
          f"Google/Bing/DDG/Yandex{C.E}")
    if found:
        print(f"\n  {C.G}{C.BOLD}Natija topilgan dorklar:{C.E}")
        for r in found:
            print(f"    {C.G}•{C.E} [{r['category']}] "
                  f"{C.GRAY}{r['dork']}{C.E} → {len(r['urls'])} ta")


def save_reports(base, domain, results, mode):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- JSON ---
    base.with_suffix(".json").write_text(json.dumps(
        {"domain": domain, "generated": stamp, "mode": mode,
         "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- TXT ---
    lines = [f"Google Dork hisoboti — {domain}", f"Yaratilgan: {stamp}",
             f"Rejim: {mode}", "=" * 64]
    for r in results:
        lines.append("")
        lines.append(f"[{SEV_LABEL[r['severity']]}] [{r['category']}] "
                     f"{r['dork']}")
        if r["urls"]:
            lines.append("  Topilgan natijalar:")
            for u in r["urls"]:
                lines.append(f"    - {u}")
        lines.append("  Qidiruv havolalari:")
        for name, url in r["links"].items():
            lines.append(f"    {name}: {url}")
    base.with_suffix(".txt").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")

    # --- HTML dashboard ---
    html_path = base.with_suffix(".html")
    html_path.write_text(render_html(domain, results, mode, stamp),
                         encoding="utf-8")
    return (base.with_suffix(".txt"), html_path, base.with_suffix(".json"))


def render_html(domain, results, mode, stamp):
    sev_color = {"high": "#f85149", "med": "#d29922", "info": "#58a6ff"}
    eng_color = {"Google": "#4285f4", "Bing": "#008373",
                 "DuckDuckGo": "#de5833", "Yandex": "#ff0000"}
    total_urls = sum(len(r["urls"]) for r in results)

    rows = []
    current = None
    for r in results:
        if r["category"] != current:
            if current is not None:
                rows.append("</div>")
            rows.append(
                f"<h2 class='cat'>{escape(r['category'])}</h2><div class='grp'>")
            current = r["category"]
        sev = r["severity"]
        dork_safe = escape(r["dork"])
        badge = (f"<span class='sev' style='background:{sev_color[sev]}22;"
                 f"color:{sev_color[sev]};border:1px solid {sev_color[sev]}55'>"
                 f"{SEV_LABEL[sev]}</span>")
        btns = "".join(
            "<a class='eng' style='--c:{c}' href='{u}' target='_blank' "
            "rel='noopener'>{n}</a>".format(
                c=eng_color.get(name, "#888"), u=escape(url), n=name)
            for name, url in r["links"].items())
        result_html = ""
        if r["urls"]:
            items = "".join(
                f"<li><a href='{escape(u)}' target='_blank' "
                f"rel='noopener'>{escape(u)}</a></li>" for u in r["urls"])
            result_html = (f"<ul class='res'><li class='res-h'>"
                           f"✔ {len(r['urls'])} ta natija topildi:</li>"
                           f"{items}</ul>")
        rows.append(
            f"<div class='dork' data-text='{dork_safe.lower()}'>"
            f"<div class='dork-top'>{badge}"
            f"<code>{dork_safe}</code>"
            f"<button class='copy' onclick=\"cp(this)\" "
            f"data-d='{dork_safe}'>nusxa</button></div>"
            f"<div class='engs'>{btns}</div>{result_html}</div>")
    if current is not None:
        rows.append("</div>")

    mode_note = {
        "cse": "Natijalar Google Custom Search API orqali avtomat olindi.",
        "searxng": "Natijalar SearXNG meta-qidiruv orqali olindi (best-effort).",
        "links": ("Live fetch bu tarmoqda bloklangan — quyidagi havolalarni "
                  "bosganingizda qidiruv SIZNING brauzeringizda ochiladi "
                  "va hech qachon bloklanmaydi."),
    }[mode]

    return f"""<!doctype html>
<html lang="uz" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dork hisoboti — {escape(domain)}</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--card2:#1c2230;--br:#30363d;
--tx:#c9d1d9;--mut:#8b949e;--acc:#58a6ff;--grn:#3fb950}}
*{{box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--tx);margin:0;padding:0 16px 64px;
line-height:1.5}}
.wrap{{max-width:980px;margin:0 auto}}
header{{padding:32px 0 20px;border-bottom:1px solid var(--br);margin-bottom:8px}}
h1{{color:var(--acc);margin:0 0 6px;font-size:1.7rem}}
h1 span{{color:var(--tx)}}
.meta{{color:var(--mut);font-size:.9rem}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}
.stat{{background:var(--card);border:1px solid var(--br);border-radius:10px;
padding:12px 18px;flex:1;min-width:120px}}
.stat b{{display:block;font-size:1.5rem;color:var(--acc)}}
.stat span{{color:var(--mut);font-size:.82rem}}
.note{{background:var(--card);border:1px solid var(--br);border-left:3px solid
var(--acc);border-radius:8px;padding:12px 16px;margin:14px 0;color:var(--mut);
font-size:.9rem}}
#filter{{width:100%;padding:11px 14px;background:var(--card);border:1px solid
var(--br);border-radius:8px;color:var(--tx);font-size:.95rem;margin:10px 0 6px}}
#filter:focus{{outline:none;border-color:var(--acc)}}
h2.cat{{color:#bc8cff;font-size:1.05rem;margin:26px 0 10px;
border-bottom:1px solid var(--br);padding-bottom:6px}}
.grp{{display:flex;flex-direction:column;gap:10px}}
.dork{{background:var(--card);border:1px solid var(--br);border-radius:10px;
padding:12px 14px}}
.dork-top{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.sev{{font-size:.68rem;font-weight:700;padding:2px 8px;border-radius:20px;
letter-spacing:.04em;white-space:nowrap}}
code{{color:#7ee787;font-size:.9rem;word-break:break-all;flex:1;min-width:200px}}
.copy{{background:var(--card2);border:1px solid var(--br);color:var(--mut);
border-radius:6px;padding:4px 10px;font-size:.78rem;cursor:pointer}}
.copy:hover{{color:var(--tx);border-color:var(--acc)}}
.engs{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.eng{{text-decoration:none;font-size:.82rem;font-weight:600;padding:5px 13px;
border-radius:7px;color:var(--c);border:1px solid var(--c);background:transparent;
transition:.15s}}
.eng:hover{{background:var(--c);color:#fff}}
.res{{list-style:none;margin:12px 0 2px;padding:10px 12px;background:var(--card2);
border-radius:8px}}
.res-h{{color:var(--grn);font-weight:700;font-size:.85rem;margin-bottom:6px}}
.res li a{{color:var(--acc);text-decoration:none;word-break:break-all;
font-size:.85rem}}
.res li{{margin:3px 0}}.res li a:hover{{text-decoration:underline}}
footer{{margin-top:40px;color:var(--mut);font-size:.8rem;text-align:center;
border-top:1px solid var(--br);padding-top:20px}}
.hidden{{display:none}}
</style></head><body><div class="wrap">
<header>
<h1>🔍 Dork hisoboti — <span>{escape(domain)}</span></h1>
<div class="meta">Yaratilgan: {stamp}</div>
</header>
<div class="stats">
<div class="stat"><b>{len(results)}</b><span>jami dork</span></div>
<div class="stat"><b>{len(DORKS)}</b><span>kategoriya</span></div>
<div class="stat"><b>{total_urls}</b><span>topilgan URL</span></div>
</div>
<div class="note">{escape(mode_note)}</div>
<div class="note" style="border-left-color:var(--grn)">
⚠️ Faqat ruxsat berilgan targetlarda ishlating (bug bounty scope, shartnoma,
lab). Har bir qatordagi tugmani bosib qidiruvni brauzerda oching.</div>
<input id="filter" type="text" placeholder="Dorklarni filtrlash... (masalan: filetype, admin, .env)"
oninput="flt(this.value)">
{''.join(rows)}
<footer>Google Dorker — professional OSINT recon vositasi.<br>
Havolalarni brauzeringiz ochadi, shuning uchun hech qachon bloklanmaydi.</footer>
</div>
<script>
function cp(b){{navigator.clipboard.writeText(b.dataset.d).then(()=>{{
 const t=b.textContent;b.textContent='✓ nusxalandi';
 setTimeout(()=>b.textContent=t,1200);}});}}
function flt(v){{v=v.toLowerCase().trim();
 document.querySelectorAll('.dork').forEach(d=>{{
  d.classList.toggle('hidden', v && !d.dataset.text.includes(v));}});
 document.querySelectorAll('.grp').forEach(g=>{{
  const any=[...g.querySelectorAll('.dork')].some(d=>!d.classList.contains('hidden'));
  g.previousElementSibling.classList.toggle('hidden',!any);
  g.classList.toggle('hidden',!any);}});}}
</script></body></html>"""


# --------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Professional Google dork OSINT skaneri.")
    p.add_argument("-d", "--domain", help="Target domen (masalan: example.com)")
    p.add_argument("-c", "--categories", nargs="+",
                   help="Faqat shu kategoriyalar (default: hammasi)")
    p.add_argument("-o", "--output", default=None,
                   help="Hisobot fayllari nomi (kengaytmasiz)")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Live so'rovlar orasidagi kutish, soniya (default: 2)")
    p.add_argument("--limit", type=int, default=8,
                   help="Har bir dork uchun maksimal natija (default: 8)")
    p.add_argument("--timeout", type=int, default=15,
                   help="So'rov timeout, soniya (default: 15)")
    p.add_argument("--engine", choices=["auto", "cse", "searxng", "links"],
                   default="auto", help="Natija manbasi (default: auto)")
    p.add_argument("--no-open", action="store_true",
                   help="HTML hisobotni brauzerda ochmaslik")
    p.add_argument("--list-categories", action="store_true",
                   help="Mavjud kategoriyalarni ko'rsatish va chiqish")
    return p.parse_args()


def choose_mode(requested):
    """auto rejimda eng yaxshi mavjud manbani tanlaydi."""
    if requested != "auto":
        return requested
    key, cx = load_cse_credentials()
    if key and cx:
        print(f"{C.G}[+] Google CSE kaliti topildi — avtomat natijalar "
              f"rejimi.{C.E}")
        return "cse"
    print(f"{C.GRAY}[*] Google CSE kaliti yo'q — SearXNG tekshirilmoqda...{C.E}")
    if probe_searxng(requests.Session()):
        print(f"{C.G}[+] SearXNG ishlayapti — best-effort natija rejimi.{C.E}")
        return "searxng"
    print(f"{C.Y}[!] Live fetch bu tarmoqda bloklangan. Clickable havolalar "
          f"rejimiga o'tildi (har doim ishlaydi).{C.E}")
    return "links"


def main():
    args = parse_args()
    print(BANNER)

    if args.list_categories:
        print(f"{C.Y}Mavjud kategoriyalar:{C.E}")
        for cat, (sev, templates) in DORKS.items():
            print(f"  [{SEV_LABEL[sev]:5}] {cat}  ({len(templates)} dork)")
        return

    raw = args.domain or input(
        f"{C.Y}Target sayt (masalan example.com): {C.E}")
    domain = normalize_domain(raw)
    if not DOMAIN_RE.match(domain):
        print(f"{C.R}[!] '{raw}' to'g'ri domenga o'xshamaydi.{C.E}")
        sys.exit(1)

    if args.categories:
        noma = [c for c in args.categories if c not in DORKS]
        if noma:
            print(f"{C.R}[!] Noma'lum kategoriya: {', '.join(noma)}{C.E}")
            print(f"    Ro'yxat: python3 main.py --list-categories")
            sys.exit(1)

    print(f"{C.R}{C.BOLD}[!] Faqat ruxsat berilgan targetlarda ishlating "
          f"(bug bounty scope, shartnoma, lab).{C.E}\n")

    mode = choose_mode(args.engine)
    print()
    results, mode = run_scan(domain, args.categories, args.delay,
                             args.limit, args.timeout, mode)
    print_summary(domain, results, mode)

    base = Path(args.output or f"dorks_{domain.replace('.', '_')}")
    txt, html_path, js = save_reports(base, domain, results, mode)
    print(f"\n{C.G}[+] Hisobot saqlandi:{C.E}")
    print(f"    {html_path}  {C.GRAY}(asosiy — brauzerda ochiladi){C.E}")
    print(f"    {txt}")
    print(f"    {js}")

    if not args.no_open:
        try:
            webbrowser.open(f"file://{html_path.resolve()}")
            print(f"\n{C.G}[+] Hisobot brauzerda ochildi. Dork tugmalarini "
                  f"bosib qidiruvni boshlang.{C.E}")
        except Exception:
            print(f"\n{C.Y}[*] Brauzerni avtomat ochib bo'lmadi. Qo'lda oching: "
                  f"{html_path}{C.E}")

    if mode == "links":
        print(f"\n{C.GRAY}[i] Natijalarni AVTOMAT olish uchun Google CSE "
              f"API'ni yoqing — main.py boshidagi izohga qarang.{C.E}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.R}To'xtatildi.{C.E}")
        sys.exit(130)
