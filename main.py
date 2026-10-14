#!/usr/bin/env python3

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
from urllib.parse import quote_plus, urlparse

try:
    import requests
except ImportError:
    sys.exit("[!] The 'requests' library is required:  pip install requests")

ENGINES = {
    "Google": "https://www.google.com/search?q={q}",
    "Bing": "https://www.bing.com/search?q={q}",
    "DuckDuckGo": "https://duckduckgo.com/?q={q}",
    "Yandex": "https://yandex.com/search/?text={q}",
}

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

DORKS = {
    "Login and admin panels": ("med", [
        "site:{d} inurl:admin",
        "site:{d} inurl:login OR inurl:signin OR inurl:auth",
        'site:{d} intitle:"dashboard" OR intitle:"control panel"',
        "site:{d} inurl:wp-admin OR inurl:wp-login",
        "site:{d} inurl:phpmyadmin OR inurl:pma",
        "site:{d} inurl:cpanel OR inurl:webmail",
    ]),
    "Directory listing (open folders)": ("high", [
        'site:{d} intitle:"index of"',
        'site:{d} intitle:"index of" "parent directory"',
        'site:{d} intitle:"index of" (backup OR admin OR uploads OR private)',
    ]),
    "Documents": ("info", [
        "site:{d} filetype:pdf",
        "site:{d} filetype:doc OR filetype:docx",
        "site:{d} filetype:xls OR filetype:xlsx OR filetype:csv",
        "site:{d} filetype:ppt OR filetype:pptx",
        "site:{d} filetype:txt",
    ]),
    "Configuration and secret files": ("high", [
        "site:{d} filetype:env OR filetype:ini OR filetype:conf OR filetype:cfg",
        "site:{d} filetype:xml OR filetype:yml OR filetype:yaml",
        "site:{d} inurl:.git OR inurl:.svn OR inurl:.env",
        'site:{d} filetype:json intext:"api_key" OR intext:"secret"',
        'site:{d} intext:"BEGIN RSA PRIVATE KEY" OR intext:"BEGIN PRIVATE KEY"',
    ]),
    "Database and backups": ("high", [
        "site:{d} filetype:sql OR filetype:db OR filetype:sqlite",
        "site:{d} filetype:bak OR filetype:old OR filetype:backup",
        "site:{d} filetype:zip OR filetype:tar OR filetype:gz OR filetype:rar",
        'site:{d} intitle:"index of" (dump OR .sql OR backup)',
    ]),
    "Log files": ("med", [
        "site:{d} filetype:log",
        'site:{d} filetype:log intext:"password" OR intext:"error"',
    ]),
    "Error / stack trace pages": ("med", [
        'site:{d} intext:"sql syntax near" OR intext:"mysql_fetch"',
        'site:{d} intext:"Warning:" intext:"on line"',
        'site:{d} intext:"Traceback (most recent call last)"',
        'site:{d} intext:"Fatal error" OR intext:"Uncaught exception"',
    ]),
    "API and dev environments": ("med", [
        "site:{d} inurl:api OR inurl:swagger OR inurl:graphql",
        "site:{d} inurl:dev OR inurl:test OR inurl:staging OR inurl:uat",
        'site:{d} inurl:wp-json',
        "site:{d} ext:json inurl:api",
    ]),
    "Parameterized URLs (potential vulnerabilities)": ("med", [
        "site:{d} inurl:id= OR inurl:page= OR inurl:file=",
        "site:{d} inurl:redirect= OR inurl:url= OR inurl:next= OR inurl:return=",
        "site:{d} inurl:cmd= OR inurl:exec= OR inurl:query=",
    ]),
    "Leaks on third-party sites": ("high", [
        '"{d}" site:pastebin.com',
        '"{d}" site:github.com',
        '"{d}" site:gitlab.com OR site:bitbucket.org',
        '"{d}" site:trello.com OR site:s3.amazonaws.com',
        '"@{d}" site:github.com password OR secret OR api_key',
    ]),
    "Subdomains and hosts": ("info", [
        "site:*.{d} -www",
        "site:{d} -inurl:www",
    ]),
}

SEV_LABEL = {"high": "HIGH", "med": "MEDIUM", "info": "INFO"}


class C:
    H = "\033[95m"; B = "\033[94m"; G = "\033[92m"; Y = "\033[93m"
    R = "\033[91m"; GRAY = "\033[90m"; E = "\033[0m"; BOLD = "\033[1m"


BANNER = rf"""{C.B}{C.BOLD}
  ____                   _        ____             _
 / ___| ___   ___   __ _| | ___  |  _ \  ___  _ __| | _____ _ __
| |  _ / _ \ / _ \ / _` | |/ _ \ | | | |/ _ \| '__| |/ / _ \ '__|
| |_| | (_) | (_) | (_| | |  __/ | |_| | (_) | |  |   <  __/ |
 \____|\___/ \___/ \__, |_|\___| |____/ \___/|_|  |_|\_\___|_|
                   |___/        professional OSINT dork scanner
{C.E}"""

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


def normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    d = re.sub(r"^\w+://", "", d)
    d = d.split("/")[0].split("@")[-1].split(":")[0]
    return d


def engine_links(dork: str) -> dict:
    q = quote_plus(dork)
    return {name: tpl.format(q=q) for name, tpl in ENGINES.items()}


def load_cse_credentials():
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
    patterns = [
        re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*class="url_header"'),
        re.compile(r'<h3>\s*<a[^>]+href="(https?://[^"]+)"'),
        re.compile(r'class="result[^"]*"[^>]*>\s*<a[^>]+href="(https?://[^"]+)"'),
    ]
    for base in instances:
        headers = {"User-Agent": random.choice(USER_AGENTS),
                   "Accept": "application/json, text/html"}
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
    for base in SEARXNG_INSTANCES[:2]:
        st, urls, _ = searxng_search(
            session, [base], "site:wikipedia.org test", 2, timeout)
        if st == "found":
            return True
    return False


def run_scan(domain, categories, delay, limit, timeout, mode):
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
        "cse": "Google Custom Search API (automatic results)",
        "searxng": "SearXNG meta-search (best-effort)",
        "links": "clickable links only (live fetch blocked)",
    }[mode]
    print(f"{C.G}[+] Prepared {total} dorks for {domain}.{C.E}")
    print(f"{C.G}[+] Mode: {mode_label}{C.E}\n")

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
                print(f"{C.G}✔ FOUND ({len(urls)}){C.E}")
                for u in urls:
                    print(f"       {C.B}{u}{C.E}")
            elif status == "empty":
                print(f"{C.GRAY}✘ nothing found{C.E}")
            elif status == "quota":
                print(f"{C.Y}⚠ quota exhausted{C.E}")
            elif status == "blocked":
                print(f"{C.Y}⚠ blocked{C.E}")
            else:
                print(f"{C.R}⚠ error{C.E}")
            if i < total:
                time.sleep(delay + random.uniform(0, delay * 0.3))

    if mode == "links":
        print(f"{C.G}[+] Clickable links prepared for {total} dorks.{C.E}")

    return results, mode


def print_summary(domain, results, mode):
    found = [r for r in results if r["status"] == "found"]
    total_urls = sum(len(r["urls"]) for r in found)
    print(f"\n{C.BOLD}{'=' * 64}{C.E}")
    print(f"{C.BOLD}  SUMMARY — {domain}{C.E}")
    print(f"{C.BOLD}{'=' * 64}{C.E}")
    print(f"  Total dorks      : {len(results)}")
    if mode in ("cse", "searxng"):
        print(f"  {C.G}Results found    : {len(found)} dorks, "
              f"{total_urls} URLs{C.E}")
    print(f"  {C.B}Clickable links  : Google/Bing/DDG/Yandex for "
          f"every dork{C.E}")
    if found:
        print(f"\n  {C.G}{C.BOLD}Dorks with results:{C.E}")
        for r in found:
            print(f"    {C.G}•{C.E} [{r['category']}] "
                  f"{C.GRAY}{r['dork']}{C.E} → {len(r['urls'])}")


def save_reports(base, domain, results, mode):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    base.with_suffix(".json").write_text(json.dumps(
        {"domain": domain, "generated": stamp, "mode": mode,
         "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"Google Dork report — {domain}", f"Generated: {stamp}",
             f"Mode: {mode}", "=" * 64]
    for r in results:
        lines.append("")
        lines.append(f"[{SEV_LABEL[r['severity']]}] [{r['category']}] "
                     f"{r['dork']}")
        if r["urls"]:
            lines.append("  Results found:")
            for u in r["urls"]:
                lines.append(f"    - {u}")
        lines.append("  Search links:")
        for name, url in r["links"].items():
            lines.append(f"    {name}: {url}")
    base.with_suffix(".txt").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")

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
                           f"✔ {len(r['urls'])} results found:</li>"
                           f"{items}</ul>")
        rows.append(
            f"<div class='dork' data-text='{dork_safe.lower()}'>"
            f"<div class='dork-top'>{badge}"
            f"<code>{dork_safe}</code>"
            f"<button class='copy' onclick=\"cp(this)\" "
            f"data-d='{dork_safe}'>copy</button></div>"
            f"<div class='engs'>{btns}</div>{result_html}</div>")
    if current is not None:
        rows.append("</div>")

    mode_note = {
        "cse": "Results were fetched automatically via the Google Custom "
               "Search API.",
        "searxng": "Results were fetched via SearXNG meta-search "
                   "(best-effort).",
        "links": ("Live fetch is blocked on this network — clicking the links "
                  "below opens the search in YOUR browser and it is never "
                  "blocked."),
    }[mode]

    return f"""<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dork report — {escape(domain)}</title>
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
<h1>🔍 Dork report — <span>{escape(domain)}</span></h1>
<div class="meta">Generated: {stamp}</div>
</header>
<div class="stats">
<div class="stat"><b>{len(results)}</b><span>total dorks</span></div>
<div class="stat"><b>{len(DORKS)}</b><span>categories</span></div>
<div class="stat"><b>{total_urls}</b><span>URLs found</span></div>
</div>
<div class="note">{escape(mode_note)}</div>
<div class="note" style="border-left-color:var(--grn)">
⚠️ Use only on authorized targets (bug bounty scope, contract, lab).
Click the buttons on each row to open the search in your browser.</div>
<input id="filter" type="text" placeholder="Filter dorks... (e.g. filetype, admin, .env)"
oninput="flt(this.value)">
{''.join(rows)}
<footer>Google Dorker — professional OSINT recon tool.<br>
The links are opened by your browser, so they are never blocked.</footer>
</div>
<script>
function cp(b){{navigator.clipboard.writeText(b.dataset.d).then(()=>{{
 const t=b.textContent;b.textContent='✓ copied';
 setTimeout(()=>b.textContent=t,1200);}});}}
function flt(v){{v=v.toLowerCase().trim();
 document.querySelectorAll('.dork').forEach(d=>{{
  d.classList.toggle('hidden', v && !d.dataset.text.includes(v));}});
 document.querySelectorAll('.grp').forEach(g=>{{
  const any=[...g.querySelectorAll('.dork')].some(d=>!d.classList.contains('hidden'));
  g.previousElementSibling.classList.toggle('hidden',!any);
  g.classList.toggle('hidden',!any);}});}}
</script></body></html>"""


def parse_args():
    p = argparse.ArgumentParser(
        description="Professional Google dork OSINT scanner.")
    p.add_argument("-d", "--domain", help="Target domain (e.g. example.com)")
    p.add_argument("-c", "--categories", nargs="+",
                   help="Only these categories (default: all)")
    p.add_argument("-o", "--output", default=None,
                   help="Report file name (without extension)")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Delay between live requests, seconds (default: 2)")
    p.add_argument("--limit", type=int, default=8,
                   help="Max results per dork (default: 8)")
    p.add_argument("--timeout", type=int, default=15,
                   help="Request timeout, seconds (default: 15)")
    p.add_argument("--engine", choices=["auto", "cse", "searxng", "links"],
                   default="auto", help="Result source (default: auto)")
    p.add_argument("--no-open", action="store_true",
                   help="Don't open the HTML report in the browser")
    p.add_argument("--list-categories", action="store_true",
                   help="Show available categories and exit")
    return p.parse_args()


def choose_mode(requested):
    if requested != "auto":
        return requested
    key, cx = load_cse_credentials()
    if key and cx:
        print(f"{C.G}[+] Google CSE key found — automatic results "
              f"mode.{C.E}")
        return "cse"
    print(f"{C.GRAY}[*] No Google CSE key — checking SearXNG...{C.E}")
    if probe_searxng(requests.Session()):
        print(f"{C.G}[+] SearXNG is working — best-effort results mode.{C.E}")
        return "searxng"
    print(f"{C.Y}[!] Live fetch is blocked on this network. Switched to "
          f"clickable links mode (always works).{C.E}")
    return "links"


def main():
    args = parse_args()
    print(BANNER)

    if args.list_categories:
        print(f"{C.Y}Available categories:{C.E}")
        for cat, (sev, templates) in DORKS.items():
            print(f"  [{SEV_LABEL[sev]:6}] {cat}  ({len(templates)} dorks)")
        return

    raw = args.domain or input(
        f"{C.Y}Target site (e.g. example.com): {C.E}")
    domain = normalize_domain(raw)
    if not DOMAIN_RE.match(domain):
        print(f"{C.R}[!] '{raw}' doesn't look like a valid domain.{C.E}")
        sys.exit(1)

    if args.categories:
        unknown = [c for c in args.categories if c not in DORKS]
        if unknown:
            print(f"{C.R}[!] Unknown category: {', '.join(unknown)}{C.E}")
            print(f"    List: python3 main.py --list-categories")
            sys.exit(1)

    print(f"{C.R}{C.BOLD}[!] Use only on authorized targets "
          f"(bug bounty scope, contract, lab).{C.E}\n")

    mode = choose_mode(args.engine)
    print()
    results, mode = run_scan(domain, args.categories, args.delay,
                             args.limit, args.timeout, mode)
    print_summary(domain, results, mode)

    base = Path(args.output or f"dorks_{domain.replace('.', '_')}")
    txt, html_path, js = save_reports(base, domain, results, mode)
    print(f"\n{C.G}[+] Report saved:{C.E}")
    print(f"    {html_path}  {C.GRAY}(main — opens in the browser){C.E}")
    print(f"    {txt}")
    print(f"    {js}")

    if not args.no_open:
        try:
            webbrowser.open(f"file://{html_path.resolve()}")
            print(f"\n{C.G}[+] Report opened in the browser. Click the dork "
                  f"buttons to start searching.{C.E}")
        except Exception:
            print(f"\n{C.Y}[*] Couldn't open the browser automatically. "
                  f"Open manually: {html_path}{C.E}")

    if mode == "links":
        print(f"\n{C.GRAY}[i] To fetch results AUTOMATICALLY, enable the "
              f"Google CSE API — see the notes at the top of main.py.{C.E}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.R}Interrupted.{C.E}")
        sys.exit(130)
