#!/usr/bin/env python3
"""
The Morning Blotter — static site generator.

    python3 build.py                 # builds ./_site from ./data and ./static
    python3 build.py --drafts        # include editions marked "draft": true (preview builds; they are noindex'd)
    python3 build.py --out DIR --base https://morningblotter.com

Standard library only. Pillow (pip install pillow) is optional and adds the share-card images (og/*.png);
without it the build still succeeds and every page falls back to the default card.

Inputs
  data/site.json                 site configuration (name, domain, emails, podcast directories, endpoints)
  data/editions/YYYY-MM-DD.json  one file per email edition (see README for the schema; emailer.py reads the same file)
  data/cases/<slug>.json         one file per tracked case
  data/episodes/*.json           podcast-only episodes (Episode 0); daily episodes live inside their edition
  static/                        copied as-is (img/, fonts/ for the card generator)

Outputs (in --out, default _site/)
  /                              the blotter — today's entry, recent entries, cases, podcast, subscribe
  /editions/                     the archive: every entry, filterable by case, state, section and month, keyword search
  /editions/<date>-<slug>/       one page per edition, in the email's look, with the episode player and transcript
  /cases/ and /cases/<slug>/     tracked cases: the record so far, the timeline, every entry that touched it
  /podcast/ and /podcast/<id>/   the show, the directories, every episode
  /about/  /subscribe/  /privacy/  /404.html  /feed.xml  /sitemap.xml  /robots.txt  /og/*.png  /CNAME
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import unicodedata
from email.utils import format_datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
STATIC = os.path.join(ROOT, 'static')

STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
    'CT': 'Connecticut', 'DE': 'Delaware', 'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky',
    'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
    'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
    'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia',
    'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming', 'PR': 'Puerto Rico',
    'US': 'Federal', 'INTL': 'International',
}

SECTION_LABELS = {
    'top_case': 'The Top Case', 'blotter': 'The Blotter', 'case_file': 'The Case File',
    'microscope': 'Under the Microscope', 'watch_list': 'The Watch List', 'presented_by': 'Presented by',
    'docket': 'On the Docket', 'sunday_file': 'The Sunday File', 'mailbag': 'The Mailbag',
}
PRESENTED_BY_DEFAULT = ('…no one, yet. One sponsor per edition, clearly labeled, never inside the reporting. '
                        'Reach a daily audience of true-crime readers: <a href="mailto:partners@morningblotter.com">partners@morningblotter.com</a>.')


# ----------------------------------------------------------------------------------------------- helpers --

def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def slugify(s, maxlen=80):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
    if len(s) > maxlen:
        s = s[:maxlen].rsplit('-', 1)[0]
    return s or 'entry'


def parse_date(s):
    return dt.date.fromisoformat(str(s)[:10])


def long_date(d):
    return d.strftime('%A, %B %-d, %Y')


def short_date(d):
    return d.strftime('%a · %b %-d, %Y').upper()


def month_key(d):
    return d.strftime('%Y-%m')


def month_label(d):
    return d.strftime('%B %Y')


def mmss(seconds):
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ''
    return f'{s // 60}:{s % 60:02d}'


def iso_duration(seconds):
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ''
    return f'PT{s // 60}M{s % 60}S'


def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(s or ''))).strip()


def words(s):
    return len(strip_html(s).split())


def read_minutes(edition):
    total = words(edition.get('intro_html', ''))
    for sec in edition.get('sections', []):
        total += words(sec.get('body_html', '')) + words(sec.get('case_notes', '')) + words(sec.get('html', ''))
        for it in sec.get('items', []):
            total += words(it.get('body_html', '')) + words(it.get('text', '')) + words(it.get('note', '')) + words(it.get('headline', ''))
    return max(1, round(total / 220))


def no_str(n):
    return f'Nº {int(n)}' if str(n).strip() not in ('', 'None') else ''


def rfc2822(d):
    return format_datetime(dt.datetime(d.year, d.month, d.day, 11, 0, 0, tzinfo=dt.timezone.utc))


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace('</', '<\\/') + '</script>'


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


# --------------------------------------------------------------------------------------------- load data --

def load(site_dir=DATA, drafts=False):
    site = read_json(os.path.join(site_dir, 'site.json'))
    cases = {}
    cdir = os.path.join(site_dir, 'cases')
    if os.path.isdir(cdir):
        for fn in sorted(os.listdir(cdir)):
            if fn.endswith('.json'):
                c = read_json(os.path.join(cdir, fn))
                c.setdefault('slug', fn[:-5])
                c['url'] = f"/cases/{c['slug']}/"
                c['entries'] = []
                cases[c['slug']] = c
    editions = []
    edir = os.path.join(site_dir, 'editions')
    if os.path.isdir(edir):
        for fn in sorted(os.listdir(edir)):
            if not fn.endswith('.json'):
                continue
            e = read_json(os.path.join(edir, fn))
            if e.get('draft') and not drafts:
                continue
            normalize_edition(e, cases)
            editions.append(e)
    editions.sort(key=lambda e: (e['date_obj'], int(e.get('no') or 0)), reverse=True)
    for i, e in enumerate(editions):
        e['newer'] = editions[i - 1] if i > 0 else None
        e['older'] = editions[i + 1] if i + 1 < len(editions) else None
    episodes = []
    pdir = os.path.join(site_dir, 'episodes')
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            if fn.endswith('.json'):
                p = read_json(os.path.join(pdir, fn))
                p.setdefault('id', slugify(p.get('title', fn[:-5])))
                p['date_obj'] = parse_date(p['date'])
                p['url'] = f"/podcast/{p['id']}/"
                p['duration_mmss'] = mmss(p.get('duration_s'))
                p['edition'] = None
                episodes.append(p)
    for e in editions:
        if e.get('episode'):
            ep = dict(e['episode'])
            ep.setdefault('id', f"{e['date']}-no-{e.get('no', 0)}")
            ep.setdefault('title', e['title'])
            ep['date_obj'] = e['date_obj']
            ep['date'] = e['date']
            ep['url'] = e['url']
            ep['duration_mmss'] = mmss(ep.get('duration_s'))
            ep['edition'] = e
            ep.setdefault('summary', e.get('summary', ''))
            episodes.append(ep)
    episodes.sort(key=lambda p: p['date_obj'], reverse=True)
    for c in cases.values():
        c['entries'].sort(key=lambda e: e['date_obj'], reverse=True)
        c['updated_obj'] = parse_date(c.get('updated') or (c['entries'][0]['date'] if c['entries'] else '2026-01-01'))
    return site, editions, cases, episodes


def normalize_edition(e, cases):
    e['date_obj'] = parse_date(e['date'])
    e['kind'] = e.get('kind') or 'daily'
    e['headline'] = e.get('headline') or e.get('title') or f"Edition {e.get('no', '')}"
    e['title'] = e.get('title') or (f"{no_str(e.get('no'))} — {e['headline']}" if e.get('no') else e['headline'])
    e['slug'] = e.get('slug') or slugify(e['headline'])
    e['url'] = f"/editions/{e['date']}-{e['slug']}/"
    e['no_str'] = no_str(e.get('no'))
    e['weekday'] = e['date_obj'].strftime('%A')
    e['date_long'] = long_date(e['date_obj'])
    e['date_short'] = short_date(e['date_obj'])
    e['month'] = month_key(e['date_obj'])
    e['month_label'] = month_label(e['date_obj'])
    e['read_minutes'] = e.get('read_minutes') or read_minutes(e)
    e['summary'] = e.get('summary') or strip_html(e.get('intro_html', ''))[:200]
    # sections: fill labels, collect cases / states / chips
    case_slugs, states, chips, section_types = [], [], [], []
    for sec in e.get('sections', []):
        sec['label'] = sec.get('label') or SECTION_LABELS.get(sec.get('type', ''), sec.get('type', '').replace('_', ' ').title())
        section_types.append(sec.get('type', ''))
        for holder in [sec] + list(sec.get('items', [])):
            for cs in holder.get('cases', []) or []:
                if cs not in case_slugs:
                    case_slugs.append(cs)
            st = (holder.get('state') or '').upper()
            if st and st not in states:
                states.append(st)
            if holder.get('chip') and holder['chip'] not in chips:
                chips.append(holder['chip'])
    for cs in e.get('cases', []) or []:
        if cs not in case_slugs:
            case_slugs.append(cs)
    for st in e.get('states', []) or []:
        st = st.upper()
        if st not in states:
            states.append(st)
    e['case_slugs'] = case_slugs
    e['case_objs'] = [cases[cs] for cs in case_slugs if cs in cases]
    for c in e['case_objs']:
        c['entries'].append(e)
    e['states'] = states
    e['state_names'] = [STATE_NAMES.get(s, s) for s in states]
    e['chips'] = chips
    e['section_types'] = section_types
    top = next((s for s in e.get('sections', []) if s.get('type') == 'top_case'), None)
    e['top'] = top
    e['top_chip'] = (top or {}).get('chip', '')
    e['top_place'] = (top or {}).get('jurisdiction', '')
    parts = [e['headline'], e['summary'], e.get('subject', '')]
    for sec in e.get('sections', []):
        parts += [sec.get('headline', ''), sec.get('title', ''), strip_html(sec.get('body_html', ''))]
        parts += [it.get('headline', '') + ' ' + it.get('text', '') + ' ' + strip_html(it.get('body_html', '')) for it in sec.get('items', [])]
    parts += [c.get('name', '') for c in e['case_objs']] + e['state_names']
    e['search_text'] = re.sub(r'\s+', ' ', ' '.join(p for p in parts if p)).lower()


# --------------------------------------------------------------------------------------------------- css --

CSS = r"""
:root{
  --paper:#eee8db;--card:#fbf8f0;--rule:#d8d0bd;--ink:#16130e;--text:#2e2a24;--crimson:#a02128;--crimson-deep:#7c1a20;
  --muted:#77705f;--manila:#f5ecd7;--manila-rule:#dbcda4;--ledger:#d9dcd4;--margin:rgba(160,33,40,.45);
  --serif:Georgia,'Times New Roman',Times,serif;--display:'Playfair Display',Georgia,'Times New Roman',serif;
  --sans:Arial,Helvetica,sans-serif;--type:'Special Elite','Courier New',Courier,monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--serif);font-size:17px;line-height:1.6}
a{color:var(--crimson);text-decoration:none}
a:hover{text-decoration:underline}
img{max-width:100%;height:auto}
.bar{height:9px;background:var(--crimson)}
.wrap{max-width:980px;margin:0 auto;padding:0 16px}
.sr{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.label{font-family:var(--sans);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.chip{display:inline-block;font-family:var(--sans);font-size:10px;font-weight:bold;letter-spacing:.14em;text-transform:uppercase;
  color:var(--crimson);border:1px solid var(--crimson);padding:3px 7px 2px;margin:0 6px 6px 0;line-height:1.2;vertical-align:middle}
.chip-solid{background:var(--crimson);color:var(--card)}
.chip-ink{background:var(--ink);border-color:var(--ink);color:var(--card)}
.chip-muted{border-color:var(--muted);color:var(--muted)}
.btn{display:inline-block;background:var(--crimson);color:var(--card)!important;font-family:var(--sans);font-size:12px;font-weight:bold;
  letter-spacing:.14em;text-transform:uppercase;padding:12px 22px;border:0;cursor:pointer;line-height:1.2;text-decoration:none!important}
.btn:hover{background:var(--crimson-deep)}
.btn-ghost{background:transparent;color:var(--crimson)!important;border:1.5px solid var(--crimson)}
.btn-ghost:hover{background:var(--crimson);color:var(--card)!important}
/* masthead */
.site-head{text-align:center;padding:26px 16px 10px}
.masthead{display:block;color:var(--ink);text-decoration:none!important}
.masthead .tag{display:block;font-family:var(--sans);font-size:11px;letter-spacing:.42em;text-transform:uppercase;color:var(--muted);padding:0 0 0 .42em}
.masthead .rule{display:block;width:min(420px,70%);margin:10px auto;border-top:2px solid var(--ink);border-bottom:1px solid var(--ink);height:3px}
.wm{display:block;font-family:var(--display);font-weight:900;line-height:.95;letter-spacing:.02em;text-transform:uppercase}
.wm-the{display:block;font-size:clamp(22px,5vw,44px);color:var(--ink)}
.wm-blotter{display:block;font-size:clamp(40px,10vw,92px);color:var(--crimson);letter-spacing:.04em}
body.inner .wm-the{font-size:clamp(16px,3vw,22px)}
body.inner .wm-blotter{font-size:clamp(28px,6vw,46px)}
body.inner .masthead .rule{margin:6px auto;width:min(300px,60%)}
body.inner .site-head{padding-top:18px}
.nav{margin:14px 0 0;padding:10px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:6px 22px}
.nav a{font-family:var(--sans);font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--ink);font-weight:bold}
.nav a.on,.nav a:hover{color:var(--crimson);text-decoration:none}
.nav a.btn{padding:9px 16px;color:var(--card)!important}
main{padding:20px 0 40px}
h1,h2,h3{font-family:var(--serif);color:var(--ink);line-height:1.2;margin:0}
h1{font-size:clamp(26px,4.4vw,40px);font-weight:bold}
h2{font-size:clamp(21px,3vw,28px)}
h3{font-size:20px}
.sect-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:34px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
.sect-head .label{color:var(--ink);font-weight:bold;font-size:12px}
.sect-head a{font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase}
/* the card (the email's look) */
.card{background:var(--card);border:1px solid var(--rule);border-top:5px solid var(--crimson);padding:26px 28px;margin:0 0 22px}
.card-meta{font-family:var(--sans);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.stamp{display:inline-block;font-family:var(--type);font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--crimson);
  border:2px solid var(--crimson);padding:4px 10px 2px;transform:rotate(-3deg);opacity:.85;margin:0 0 12px}
/* ledger */
.ledger{list-style:none;margin:0;padding:0;background:var(--card);border:1px solid var(--rule);position:relative}
.ledger::before{content:"";position:absolute;top:0;bottom:0;left:112px;border-left:2px solid var(--margin)}
.ledger-head{display:grid;grid-template-columns:112px 1fr 130px;gap:0 16px;background:var(--ink);color:var(--card);font-family:var(--sans);
  font-size:10px;letter-spacing:.22em;text-transform:uppercase;padding:8px 14px;position:relative;z-index:1}
.entry{display:grid;grid-template-columns:112px 1fr 130px;gap:0 16px;padding:18px 14px 16px;border-top:1px solid var(--rule);position:relative}
.entry:first-of-type{border-top:0}
.entry:hover{background:rgba(255,255,255,.55)}
.entry-no{font-family:var(--type);color:var(--ink);font-size:15px;line-height:1.35;padding-right:12px;margin:-18px 0 -16px;padding-top:18px;
  background-image:repeating-linear-gradient(to bottom,transparent 0,transparent 27px,var(--ledger) 27px,var(--ledger) 28px)}
.entry-no time{display:block;font-size:11px;color:var(--muted);letter-spacing:.04em}
.entry-no .kind{display:block;font-size:10px;color:var(--crimson);letter-spacing:.1em;margin-top:6px}
.entry-title{font-size:20px;line-height:1.25;margin:2px 0 6px}
.entry-title a{color:var(--ink)}
.entry-title a:hover{color:var(--crimson);text-decoration:none}
.entry-sum{margin:0 0 6px;font-size:15.5px;line-height:1.5}
.entry-cases{margin:0;font-family:var(--sans);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.entry-cases a{color:var(--crimson-deep)}
.entry-act{display:flex;flex-direction:column;align-items:flex-end;gap:8px;font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:bold}
.entry-act .listen{color:var(--card);background:var(--ink);padding:7px 10px;white-space:nowrap}
.entry-act .listen:hover{background:var(--crimson);text-decoration:none}
.entry-act .read{color:var(--crimson);white-space:nowrap}
.entry.hidden{display:none}
.empty{padding:26px 14px;text-align:center;color:var(--muted);font-style:italic}
/* filters */
.filters{background:var(--card);border:1px solid var(--rule);padding:14px 16px;margin:0 0 14px;display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr auto;gap:10px;align-items:end}
.filters label{display:block;font-family:var(--sans);font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.filters input,.filters select{width:100%;font-family:var(--serif);font-size:15px;padding:9px 10px;border:1px solid var(--rule);background:#fff;color:var(--ink);border-radius:0}
.filters input:focus,.filters select:focus{outline:2px solid var(--crimson);outline-offset:0}
.filters .clear{font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;padding:11px 12px;background:transparent;border:1px solid var(--rule);color:var(--muted);cursor:pointer}
.count{font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
/* home hero */
.hero{display:grid;grid-template-columns:1.6fr 1fr;gap:26px;align-items:start}
.hero .card{margin:0}
.hero h2{font-size:clamp(24px,3.6vw,34px);margin:6px 0 10px}
.hero p{margin:0 0 14px}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 14px}
.player{background:#fff;border:1px solid var(--rule)}
.player iframe{display:block;width:100%;height:180px;border:0}
.aside .card{padding:20px 22px}
.aside h3{font-size:17px;margin:0 0 8px}
.aside p{font-size:15px;margin:0 0 10px}
.dir{margin:6px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:6px}
.dir a{display:inline-block;font-family:var(--sans);font-size:10px;letter-spacing:.12em;text-transform:uppercase;border:1px solid var(--rule);padding:6px 9px;color:var(--ink);background:#fff}
.dir a:hover{border-color:var(--crimson);color:var(--crimson);text-decoration:none}
/* subscribe */
.sub{background:var(--card);border:1.5px solid var(--crimson);padding:18px 20px;margin:0}
.sub h3{font-size:19px;margin:0 0 4px}
.sub p{margin:0 0 10px;font-size:15px}
.sub-row{display:flex;gap:8px;flex-wrap:wrap}
.sub-row input[type=email]{flex:1 1 220px;font-family:var(--serif);font-size:16px;padding:11px 12px;border:1px solid var(--rule);background:#fff;border-radius:0}
.sub-row input[type=email]:focus{outline:2px solid var(--crimson);outline-offset:0}
.sub-note{font-family:var(--sans);font-size:11px;color:var(--muted);letter-spacing:.04em;margin:8px 0 0}
.sub-msg{display:block;font-family:var(--serif);font-size:15px;margin-top:8px;color:var(--crimson-deep)}
.hp{position:absolute;left:-9999px;opacity:0;height:0;width:0}
.sub-wide{margin:34px 0 0}
/* cases */
.cases{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.case{background:var(--manila);border:1px solid var(--manila-rule);padding:16px 18px;position:relative}
.case::before{content:"";position:absolute;top:-1px;left:18px;width:64px;height:10px;background:var(--manila-rule)}
.case h3{font-size:18px;margin:6px 0 4px}
.case h3 a{color:var(--ink)}
.case p{margin:0 0 8px;font-size:15px}
.case .label{display:block;margin-top:6px}
/* edition page */
.edition .card{padding:0}
.ed-mast{text-align:center;padding:26px 28px 18px;border-bottom:1px solid var(--rule)}
.ed-mast .wm-the{font-size:14px}.ed-mast .wm-blotter{font-size:30px}
.ed-mast .tag{display:block;font-family:var(--sans);font-size:10px;letter-spacing:.32em;text-transform:uppercase;color:var(--muted);margin:2px 0 8px}
.ed-mast .card-meta{margin:10px 0 0;color:var(--ink)}
.ed-listen{padding:16px 28px;border-bottom:1px solid var(--rule);text-align:center;background:#fff8ea}
.ed-listen .btn{margin-bottom:12px}
.ed-body{padding:10px 28px 6px}
.ed-body h1{font-size:clamp(24px,3.6vw,34px);margin:14px 0 10px}
.ed-intro{font-size:17.5px}
.ed-sec{margin:26px 0 0;padding-top:12px;border-top:2px solid var(--ink)}
.ed-sec .label{color:var(--ink);font-weight:bold;font-size:12px;display:block;margin:0 0 10px}
.ed-item{margin:0 0 20px}
.ed-item h2,.ed-item h3{font-size:21px;line-height:1.25;margin:2px 0 4px}
.ed-item h2 a,.ed-item h3 a{color:var(--ink)}
.ed-item h2 a:hover,.ed-item h3 a:hover{color:var(--crimson);text-decoration:none}
.meta{font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.ed-item p{margin:0 0 8px}
.case-notes{font-style:italic;color:var(--crimson-deep)}
.file{background:var(--manila);border:1px solid var(--manila-rule);padding:18px 22px;margin:8px 0 6px}
.file h2{font-size:22px;margin:0 0 8px}
.pull{font-family:var(--display);font-size:22px;line-height:1.3;color:var(--crimson-deep);border-left:4px solid var(--crimson);padding:4px 0 4px 16px;margin:14px 0}
.filed{font-family:var(--sans);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin:10px 0 0}
.watch li{margin:0 0 10px}
.watch{padding-left:0;list-style:none;margin:0}
.presented{background:#f3eee2;border:1px dashed var(--rule);padding:12px 16px;font-size:15px;color:var(--muted)}
.docket{list-style:none;padding:0;margin:0}
.docket li{margin:0 0 10px;padding-left:0}
.docket b{color:var(--crimson);font-family:var(--sans);font-size:12px;letter-spacing:.1em;text-transform:uppercase;margin-right:6px}
.ed-foot{padding:18px 28px 22px;border-top:1px solid var(--rule);font-size:13px;color:var(--muted);line-height:1.55}
.ed-foot p{margin:0 0 8px}
.ed-after{margin:26px 0 0}
details.transcript{background:var(--card);border:1px solid var(--rule);padding:0 0 4px}
details.transcript summary{cursor:pointer;padding:14px 18px;font-family:var(--sans);font-size:12px;letter-spacing:.2em;text-transform:uppercase;font-weight:bold;color:var(--ink)}
details.transcript summary:hover{color:var(--crimson)}
.tx{padding:4px 18px 14px;font-size:15.5px;line-height:1.6}
.tx p{margin:0 0 10px}
.tx .spk{font-family:var(--sans);font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:bold;color:var(--crimson-deep);display:block}
.tx .seg{font-family:var(--type);color:var(--muted);font-size:13px;letter-spacing:.06em;margin:14px 0 6px;display:block}
.sources{font-size:14.5px;padding-left:20px}
.sources li{margin:0 0 6px}
.pager{display:flex;justify-content:space-between;gap:12px;margin:24px 0 0;font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:bold}
.pager a{color:var(--ink)}.pager a:hover{color:var(--crimson);text-decoration:none}
.crumbs{font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 12px}
.crumbs a{color:var(--muted)}
.draft{background:var(--crimson);color:var(--card);text-align:center;font-family:var(--sans);font-size:12px;letter-spacing:.2em;text-transform:uppercase;padding:9px 12px;margin:0 0 16px}
/* case page */
.timeline{list-style:none;margin:0;padding:0;border-left:2px solid var(--rule)}
.timeline li{position:relative;padding:0 0 16px 20px}
.timeline li::before{content:"";position:absolute;left:-7px;top:8px;width:10px;height:10px;background:var(--crimson);border:2px solid var(--card)}
.timeline time{display:block;font-family:var(--sans);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--crimson-deep);font-weight:bold;margin:0 0 2px}
.timeline .src{font-family:var(--sans);font-size:11px;color:var(--muted);letter-spacing:.04em}
.people{list-style:none;padding:0;margin:0}
.people li{margin:0 0 10px;padding:0 0 10px;border-bottom:1px solid var(--rule)}
.people b{color:var(--ink)}
.prose p{margin:0 0 14px}
.prose ul{padding-left:22px}
/* podcast */
.pod{display:grid;grid-template-columns:220px 1fr;gap:26px;align-items:start}
.pod img{border:1px solid var(--rule);width:100%}
.ep-list{list-style:none;padding:0;margin:0}
.ep-list li{background:var(--card);border:1px solid var(--rule);padding:16px 18px;margin:0 0 12px}
.ep-list h3{font-size:19px;margin:2px 0 6px}
.ep-list h3 a{color:var(--ink)}
.ep-list .meta{margin:0 0 6px}
.hosts{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.host{background:var(--card);border:1px solid var(--rule);padding:16px 18px}
.host h3{font-size:19px;margin:0 0 2px}
.host .label{display:block;margin:0 0 8px;color:var(--crimson-deep)}
.host p{margin:0;font-size:15px}
/* footer */
.site-foot{border-top:2px solid var(--ink);margin:10px 0 0;padding:26px 0 30px;font-size:13.5px;color:var(--muted);line-height:1.6}
.site-foot .fwm{font-family:var(--display);font-weight:900;color:var(--ink);font-size:20px;letter-spacing:.02em;margin:0 0 4px;text-transform:uppercase}
.site-foot .fwm span{color:var(--crimson)}
.foot-grid{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:22px}
.foot-grid ul{list-style:none;padding:0;margin:0}
.foot-grid li{margin:0 0 4px}
.foot-grid a{color:var(--ink)}
.foot-grid .label{display:block;margin:0 0 8px}
.foot-fine{margin:18px 0 0;padding-top:12px;border-top:1px solid var(--rule);font-size:12px}
@media (max-width:760px){
  .hero,.pod,.hosts,.foot-grid{grid-template-columns:1fr}
  .filters{grid-template-columns:1fr 1fr}
  .filters .q{grid-column:1/-1}
  .ledger::before{display:none}
  .ledger-head{display:none}
  .entry{grid-template-columns:1fr;gap:8px 0;padding:14px 14px}
  .entry-no{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;background-image:none;margin:0;padding-top:0}
  .entry-no time{display:inline}
  .entry-no .kind{display:inline;margin:0}
  .entry-act{flex-direction:row;align-items:center;justify-content:flex-start}
  .card,.ed-body,.ed-mast,.ed-listen,.ed-foot{padding-left:16px;padding-right:16px}
  .site-head{padding:18px 12px 8px}
  .nav{gap:6px 14px}
  .nav a{font-size:11px;letter-spacing:.14em}
}
"""

# ---------------------------------------------------------------------------------------------------- js --

SUBSCRIBE_JS = r"""
(function(){
  var forms=document.querySelectorAll('form[data-subscribe]');
  Array.prototype.forEach.call(forms,function(f){
    f.addEventListener('submit',function(ev){
      var email=f.querySelector('input[type=email]').value.trim();
      var hp=(f.querySelector('input[name=website]')||{}).value||'';
      var msg=f.querySelector('.sub-msg');var btn=f.querySelector('button');
      if(!f.action||f.action.indexOf('script.google.com')<0){return;} // no endpoint configured: let the form post normally
      ev.preventDefault();
      if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){msg.textContent='That address doesn’t look right — check it and try again.';return;}
      btn.disabled=true;var old=btn.textContent;btn.textContent='ONE MOMENT…';
      fetch(f.action,{method:'POST',mode:'cors',redirect:'follow',headers:{'Content-Type':'text/plain;charset=utf-8'},
        body:JSON.stringify({action:'subscribe',email:email,website:hp,src:f.dataset.src||'site',page:location.pathname})})
      .then(function(r){return r.json();})
      .then(function(d){
        btn.disabled=false;btn.textContent=old;
        if(d&&d.ok){msg.textContent=d.message||'Check your inbox — one click on the confirmation email and you’re in.';f.querySelector('input[type=email]').value='';}
        else{msg.textContent=(d&&d.error)||'Something went wrong — email subscribe@morningblotter.com and we’ll add you by hand.';}
      })
      .catch(function(){btn.disabled=false;btn.textContent=old;f.removeAttribute('data-subscribe');f.submit();});
    });
  });
})();
"""

ARCHIVE_JS = r"""
(function(){
  var q=document.getElementById('q'),cs=document.getElementById('f-case'),st=document.getElementById('f-state'),
      se=document.getElementById('f-section'),mo=document.getElementById('f-month'),clr=document.getElementById('f-clear'),
      rows=Array.prototype.slice.call(document.querySelectorAll('.ledger .entry')),count=document.getElementById('count'),
      empty=document.getElementById('empty');
  function norm(s){return (s||'').toLowerCase().replace(/[‘’]/g,"'").replace(/[“”]/g,'"');}
  function apply(push){
    var terms=norm(q.value).split(/\s+/).filter(Boolean),n=0;
    rows.forEach(function(r){
      var ok=true,txt=norm(r.getAttribute('data-search'));
      terms.forEach(function(t){if(txt.indexOf(t)<0)ok=false;});
      if(cs.value&&(' '+r.getAttribute('data-cases')+' ').indexOf(' '+cs.value+' ')<0)ok=false;
      if(st.value&&(' '+r.getAttribute('data-states')+' ').indexOf(' '+st.value+' ')<0)ok=false;
      if(se.value&&(' '+r.getAttribute('data-sections')+' ').indexOf(' '+se.value+' ')<0)ok=false;
      if(mo.value&&r.getAttribute('data-month')!==mo.value)ok=false;
      r.classList.toggle('hidden',!ok);if(ok)n++;
    });
    count.textContent=n+(n===1?' entry':' entries')+(rows.length!==n?' of '+rows.length:'');
    empty.style.display=n?'none':'block';
    if(push&&history.replaceState){
      var p=new URLSearchParams();if(q.value)p.set('q',q.value);if(cs.value)p.set('case',cs.value);if(st.value)p.set('state',st.value);
      if(se.value)p.set('section',se.value);if(mo.value)p.set('month',mo.value);
      history.replaceState(null,'',location.pathname+(p.toString()?'?'+p.toString():''));
    }
  }
  var p=new URLSearchParams(location.search);
  q.value=p.get('q')||'';cs.value=p.get('case')||'';st.value=p.get('state')||'';se.value=p.get('section')||'';mo.value=p.get('month')||'';
  [q,cs,st,se,mo].forEach(function(el){el.addEventListener('input',function(){apply(true);});el.addEventListener('change',function(){apply(true);});});
  clr.addEventListener('click',function(){q.value='';cs.value='';st.value='';se.value='';mo.value='';apply(true);q.focus();});
  apply(false);
})();
"""


# ------------------------------------------------------------------------------------------------ layout --

def masthead(site, home=False):
    return (
        '<header class="site-head"><a class="masthead" href="/" aria-label="' + esc(site['name']) + ' — home">'
        '<span class="tag">' + esc(site['tagline']) + '</span><span class="rule"></span>'
        '<span class="wm"><span class="wm-the">The Morning</span><span class="wm-blotter">Blotter</span></span>'
        '<span class="rule"></span><span class="tag">' + esc(site['tagline2']) + '</span></a>'
        + nav(site) + '</header>'
    )


def nav(site, on=''):
    items = [('/editions/', 'Editions', 'editions'), ('/cases/', 'Cases', 'cases'), ('/podcast/', 'Podcast', 'podcast'), ('/about/', 'About', 'about')]
    out = '<nav class="nav" aria-label="Site">'
    for href, label, key in items:
        out += f'<a href="{href}"{" class=on" if key == on else ""}>{label}</a>'
    out += '<a class="btn" href="/subscribe/">Subscribe free</a></nav>'
    return out


def subscribe_form(site, heading='Get the brief, free', blurb=None, src='site', wide=False):
    endpoint = site.get('subscribe_endpoint') or ''
    action = esc(endpoint) if endpoint else 'mailto:' + esc(site['email']['subscribe']) + '?subject=Subscribe%20-%20Morning%20Blotter'
    blurb = blurb or f"Every case, every headline, linked to its source — in your inbox at {site['send_time']}. One click to unsubscribe, any morning."
    uid = 'sub-' + re.sub(r'[^a-z0-9]', '', (heading + src).lower())[:16]
    return (
        f'<form class="sub{" sub-wide" if wide else ""}" action="{action}" method="post" data-subscribe data-src="{esc(src)}">'
        f'<h3>{esc(heading)}</h3><p>{esc(blurb)}</p>'
        '<input type="hidden" name="a" value="subscribe"><input type="hidden" name="src" value="' + esc(src) + '">'
        '<input class="hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">'
        f'<div class="sub-row"><label class="sr" for="{uid}">Email address</label>'
        f'<input id="{uid}" type="email" name="email" required autocomplete="email" placeholder="you@example.com">'
        '<button class="btn" type="submit">Subscribe free</button></div>'
        '<p class="sub-note">Free. No spam, no list sales. <span class="sub-msg" aria-live="polite"></span></p></form>'
    )


def footer(site):
    d = site['podcast']['directories']
    apple = next((x['url'] for x in d if x['name'] == 'Apple Podcasts'), '')
    spotify = next((x['url'] for x in d if x['name'] == 'Spotify'), '')
    return (
        '<footer class="site-foot"><div class="wrap"><div class="foot-grid">'
        '<div><p class="fwm">The Morning <span>Blotter</span></p>'
        f'<p>Filed daily at {esc(site["send_time"])}. {esc(site["ethics_line"])}</p></div>'
        '<div><span class="label">The desk</span><ul>'
        '<li><a href="/editions/">Every edition</a></li><li><a href="/cases/">Cases we track</a></li>'
        '<li><a href="/podcast/">The podcast</a></li><li><a href="/about/">About the Blotter</a></li>'
        '<li><a href="/subscribe/">Subscribe free</a></li><li><a href="/privacy/">Privacy</a></li></ul></div>'
        '<div><span class="label">Write to us</span><ul>'
        f'<li><a href="mailto:{esc(site["email"]["mailbag"])}">{esc(site["email"]["mailbag"])}</a> — questions for Ray and Casey (first names only on air)</li>'
        f'<li><a href="mailto:{esc(site["email"]["hello"])}">{esc(site["email"]["hello"])}</a> — the desk</li>'
        f'<li><a href="mailto:{esc(site["email"]["partners"])}">{esc(site["email"]["partners"])}</a> — sponsorship</li>'
        f'<li><a href="{esc(apple)}">Apple Podcasts</a> · <a href="{esc(spotify)}">Spotify</a> · <a href="{esc(site["podcast"]["feed_url"])}">Podcast RSS</a> · <a href="/feed.xml">Site feed</a></li>'
        '</ul></div></div>'
        f'<p class="foot-fine">{esc(site["ai_line"])} © {dt.date.today().year} {esc(site["name"])}. All rights reserved.</p>'
        '</div></footer>'
    )


def prefix_of(site):
    """'/morning-blotter-site' when the site is served under a path (GitHub project pages before the custom domain), else ''."""
    m = re.match(r'^https?://[^/]+(/.*)?$', site['url'].rstrip('/'))
    return (m.group(1) or '').rstrip('/') if m else ''


def rebase(html_text, site):
    pre = prefix_of(site)
    if not pre:
        return html_text
    return re.sub(r'((?:href|src|action|content)=")/(?!/)', r'\1' + pre + '/', html_text)


def layout(site, *, title, description, path, body, on='', home=False, ld=None, og_image=None, og_type='website',
           noindex=False, extra_head='', js=''):
    base = site['url'].rstrip('/')
    canonical = base + path
    og_image = og_image or (base + '/og/default.png')
    desc = esc(strip_html(description)[:300])
    sc = site.get('search_console_tag') or ''
    head = [
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{esc(title)}</title>',
        f'<meta name="description" content="{desc}">',
        f'<link rel="canonical" href="{esc(canonical)}">',
        '<meta name="robots" content="noindex,follow">' if noindex else '<meta name="robots" content="index,follow,max-image-preview:large">',
        f'<meta property="og:site_name" content="{esc(site["name"])}"><meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{desc}">',
        f'<meta property="og:url" content="{esc(canonical)}"><meta property="og:image" content="{esc(og_image)}">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{desc}"><meta name="twitter:image" content="{esc(og_image)}">',
        '<meta name="theme-color" content="#a02128">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.png" sizes="32x32">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        f'<link rel="alternate" type="application/rss+xml" title="{esc(site["name"])} — editions" href="{base}/feed.xml">',
        f'<link rel="alternate" type="application/rss+xml" title="{esc(site["name"])} — podcast" href="{esc(site["podcast"]["feed_url"])}">',
        '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Special+Elite&display=swap" rel="stylesheet">',
        f'<meta name="google-site-verification" content="{esc(sc)}">' if sc else '',
        '<style>' + CSS + '</style>',
        extra_head,
    ]
    for obj in (ld or []):
        head.append(jsonld(obj))
    head.append('</head>')
    cls = 'home' if home else 'inner'
    head_html = masthead(site, home)
    if on:
        head_html = head_html.replace(f'<a href="/{on}/">', f'<a href="/{on}/" class="on">')
    page = (''.join(head) + f'<body class="{cls}"><div class="bar"></div>' + head_html
            + '<main><div class="wrap">' + body + '</div></main>' + footer(site) + '<div class="bar"></div>'
            + '<script>' + SUBSCRIBE_JS + js + '</script></body></html>')
    return rebase(page, site)


def org_ld(site):
    base = site['url'].rstrip('/')
    same = [d['url'] for d in site['podcast']['directories'] if d['name'] in ('Apple Podcasts', 'Spotify')]
    return {
        '@context': 'https://schema.org', '@type': 'NewsMediaOrganization', 'name': site['name'], 'url': base + '/',
        'logo': {'@type': 'ImageObject', 'url': base + '/img/cover-1200.png', 'width': 1200, 'height': 1200},
        'sameAs': same, 'email': site['email']['hello'],
        'publishingPrinciples': base + '/about/',
    }


def website_ld(site):
    base = site['url'].rstrip('/')
    return {
        '@context': 'https://schema.org', '@type': 'WebSite', 'name': site['name'], 'url': base + '/',
        'potentialAction': {'@type': 'SearchAction', 'target': {'@type': 'EntryPoint', 'urlTemplate': base + '/editions/?q={search_term_string}'},
                            'query-input': 'required name=search_term_string'},
    }


def crumbs_ld(site, items):
    base = site['url'].rstrip('/')
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList',
            'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': n, 'item': base + u} for i, (n, u) in enumerate(items)]}


# ------------------------------------------------------------------------------------------- components --

def chips_html(e, limit=3):
    out = ''
    if e.get('kind') == 'sunday':
        out += '<span class="chip chip-ink">The Sunday File</span>'
    if e.get('top_chip'):
        out += f'<span class="chip chip-solid">{esc(e["top_chip"])}</span>'
    if e.get('top_place'):
        out += f'<span class="chip chip-muted">{esc(e["top_place"])}</span>'
    return out


def entry_row(e, cases):
    listen = ''
    if e.get('episode') and e['episode'].get('share_url'):
        listen = f'<a class="listen" href="{e["url"]}#listen" title="Listen to the episode">▶ {esc(mmss(e["episode"].get("duration_s")))}</a>'
    case_links = ''
    if e['case_objs']:
        case_links = '<p class="entry-cases">Case: ' + ' · '.join(f'<a href="{c["url"]}">{esc(c["name"])}</a>' for c in e['case_objs']) + '</p>'
    data = (f' data-search="{esc(e["search_text"])}" data-cases="{esc(" ".join(e["case_slugs"]))}" data-states="{esc(" ".join(e["states"]))}"'
            f' data-sections="{esc(" ".join(e["section_types"]))}" data-month="{e["month"]}" data-kind="{e["kind"]}"')
    kind = '<span class="kind">Sunday File</span>' if e['kind'] == 'sunday' else ''
    return (
        f'<li class="entry"{data}><div class="entry-no"><span class="no">{esc(e["no_str"]) or "—"}</span>'
        f'<time datetime="{e["date"]}">{esc(e["date_short"])}</time>{kind}</div>'
        f'<div class="entry-body"><div class="chips">{chips_html(e)}</div>'
        f'<h3 class="entry-title"><a href="{e["url"]}">{esc(e["headline"])}</a></h3>'
        f'<p class="entry-sum">{esc(e["summary"])}</p>{case_links}</div>'
        f'<div class="entry-act">{listen}<a class="read" href="{e["url"]}">Read →</a></div></li>'
    )


def ledger(editions, cases, head=True):
    if not editions:
        return '<ol class="ledger"><li class="empty">No entries yet — the first edition files soon.</li></ol>'
    h = '<div class="ledger-head"><span>Entry</span><span>Particulars</span><span style="text-align:right">Listen · Read</span></div>' if head else ''
    return h + '<ol class="ledger">' + ''.join(entry_row(e, cases) for e in editions) + '</ol>'


def player(share_url, transistor_id=None, title=''):
    if not share_url:
        return ''
    sid = share_url.rstrip('/').split('/')[-1]
    return (f'<div class="player"><iframe title="{esc(title or "Listen")}" loading="lazy" src="https://share.transistor.fm/e/{esc(sid)}" '
            'width="100%" height="180" frameborder="no" scrolling="no" seamless></iframe></div>')


def directory_links(site):
    return '<ul class="dir">' + ''.join(f'<li><a href="{esc(d["url"])}" rel="noopener">{esc(d["name"])}</a></li>' for d in site['podcast']['directories']) + '</ul>'


# --------------------------------------------------------------------------------------------- edition --

def item_html(it, h='h3'):
    chip = f'<span class="chip">{esc(it["chip"])}</span>' if it.get('chip') else ''
    head = f'<a href="{esc(it["url"])}" rel="noopener">{esc(it["headline"])}</a>' if it.get('url') else esc(it.get('headline', ''))
    meta = ' • '.join(esc(x) for x in [it.get('jurisdiction', ''), it.get('source', ''), fmt_item_date(it.get('date', ''))] if x)
    body = it.get('body_html') or (f'<p>{esc(it["text"])}</p>' if it.get('text') else '')
    return f'<div class="ed-item">{chip}<{h}>{head}</{h}>' + (f'<p class="meta">{meta}</p>' if meta else '') + body + '</div>'


def fmt_item_date(s):
    try:
        return parse_date(s).strftime('%b %-d, %Y')
    except Exception:
        return s or ''


def section_html(e, sec):
    t = sec.get('type', '')
    label = f'<span class="label">{esc(sec["label"])}</span>'
    if t == 'top_case':
        notes = f'<p class="case-notes"><b>Case notes:</b> {esc(sec["case_notes"])}</p>' if sec.get('case_notes') else ''
        it = dict(sec)
        it['chip'] = it.get('chip')
        body = item_html(it, 'h2').replace('<span class="chip">', '<span class="chip chip-solid">', 1)
        return f'<section class="ed-sec">{label}{body}{notes}</section>'
    if t == 'blotter':
        return f'<section class="ed-sec">{label}' + ''.join(item_html(it) for it in sec.get('items', [])) + '</section>'
    if t in ('case_file', 'sunday_file'):
        n = sec.get('no') or e.get('no')
        title = sec.get('title', '')
        pull = f'<blockquote class="pull">{esc(sec["pull_quote"])}</blockquote>' if sec.get('pull_quote') else ''
        src = ''
        if sec.get('sources'):
            src = '<p class="meta">Sources: ' + ' · '.join(f'<a href="{esc(s["url"])}" rel="noopener">{esc(s.get("title") or s.get("outlet") or s["url"])}</a>' for s in sec['sources']) + '</p>'
        lab = f'{sec["label"]} {no_str(n)}' if n else sec['label']
        return (f'<section class="ed-sec"><span class="label">{esc(lab)}</span><div class="file"><h2>{esc(title)}</h2>'
                + sec.get('body_html', '') + pull + src + '<p class="filed">— Filed by the Blotter desk</p></div></section>')
    if t == 'microscope':
        return f'<section class="ed-sec">{label}{item_html(sec)}</section>'
    if t == 'watch_list':
        lis = ''
        for it in sec.get('items', []):
            chips = ''.join(f'<span class="chip chip-ink">{esc(x)}</span>' for x in [it.get('kind', ''), it.get('platform', ''), it.get('date', '')] if x)
            title = f'<a href="{esc(it["url"])}" rel="noopener{" sponsored" if it.get("affiliate") else ""}">{esc(it["title"])}</a>' if it.get('url') else esc(it.get('title', ''))
            lis += f'<li>{chips}<div><b>{title}</b>' + (f' — {esc(it["note"])}' if it.get('note') else '') + '</div></li>'
        disc = ('<p class="meta">Some links are affiliate links; the Blotter may earn a commission. Coverage is never sponsored.</p>'
                if any(it.get('affiliate') for it in sec.get('items', [])) else '')
        return f'<section class="ed-sec">{label}<ul class="watch">{lis}</ul>{disc}</section>'
    if t == 'presented_by':
        return f'<section class="ed-sec">{label}<div class="presented">{sec.get("html") or PRESENTED_BY_DEFAULT}</div></section>'
    if t == 'docket':
        lis = ''
        for it in sec.get('items', []):
            txt = f'<a href="{esc(it["url"])}" rel="noopener">{esc(it["text"])}</a>' if it.get('url') else esc(it.get('text', ''))
            lis += f'<li><b>{esc(it.get("date", ""))}</b> {txt}</li>'
        return f'<section class="ed-sec">{label}<ul class="docket">{lis}</ul></section>'
    if t == 'mailbag':
        return f'<section class="ed-sec">{label}{sec.get("body_html", "")}</section>'
    return f'<section class="ed-sec">{label}{sec.get("body_html", sec.get("html", ""))}</section>'


def transcript_html(text):
    if not text:
        return ''
    out = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^\[(.+?)\]$', line)
        if m:
            out.append(f'<span class="seg">— {esc(m.group(1).title())} —</span>')
            continue
        m = re.match(r'^([A-Z][A-Z .\'-]{1,20}):\s*(.*)$', line)
        if m:
            out.append(f'<p><span class="spk">{esc(m.group(1).title())}</span>{esc(m.group(2))}</p>')
        else:
            out.append(f'<p>{esc(line)}</p>')
    return '<div class="tx">' + ''.join(out) + '</div>'


def edition_page(site, e, cases):
    base = site['url'].rstrip('/')
    ep = e.get('episode') or {}
    draft = '<div class="draft">Preview — sample edition, not published</div>' if e.get('draft') else ''
    listen = ''
    if ep.get('share_url'):
        listen = (f'<div class="ed-listen" id="listen"><a class="btn" href="{esc(ep["share_url"])}" rel="noopener">▶ Listen — {esc(mmss(ep.get("duration_s")))} with Ray &amp; Casey</a>'
                  + player(ep['share_url'], title=e['title']) + '</div>')
    mast = (f'<div class="ed-mast"><span class="wm"><span class="wm-the">The Morning</span><span class="wm-blotter">Blotter</span></span>'
            f'<span class="tag">{esc(site["tagline"])} — {esc(site["tagline2"])}</span>'
            f'<p class="card-meta">Vol. {esc(e.get("vol", ""))} • {esc(e["no_str"])} • {esc(e["date_long"])} • A {e["read_minutes"]}-minute read</p></div>')
    body = f'<div class="ed-body"><h1>{esc(e["headline"])}</h1>' + (f'<div class="ed-intro">{e.get("intro_html", "")}</div>' if e.get('intro_html') else '')
    for sec in e.get('sections', []):
        body += section_html(e, sec)
    body += '</div>'
    foot = (f'<div class="ed-foot"><p><b>Filed daily at {esc(site["send_time"])}.</b> {esc(site["ethics_line"])}</p>'
            f'<p>Questions for Ray and Casey: <a href="mailto:{esc(site["email"]["mailbag"])}">{esc(site["email"]["mailbag"])}</a> — first names only on air.</p>'
            f'<p>{esc(site["ai_line"])}</p></div>')
    after = '<div class="ed-after">'
    if ep.get('transcript'):
        after += '<details class="transcript" open><summary>Episode transcript</summary>' + transcript_html(ep['transcript']) + '</details>'
    if e['case_objs']:
        after += '<div class="sect-head"><span class="label">Cases in this edition</span></div><div class="cases">' + ''.join(case_card(c) for c in e['case_objs']) + '</div>'
    if e.get('sources'):
        after += '<div class="sect-head"><span class="label">Sources</span></div><ol class="sources">' + ''.join(
            f'<li><a href="{esc(s["url"])}" rel="noopener">{esc(s.get("title") or s["url"])}</a>' + (f' — {esc(s["outlet"])}' if s.get('outlet') else '') + (f', {esc(fmt_item_date(s["date"]))}' if s.get('date') else '') + '</li>'
            for s in e['sources']) + '</ol>'
    pager = '<div class="pager">'
    pager += f'<a href="{e["older"]["url"]}">← {esc(e["older"]["no_str"] or "Previous")}: {esc(e["older"]["headline"][:48])}</a>' if e.get('older') else '<span></span>'
    pager += f'<a href="{e["newer"]["url"]}">{esc(e["newer"]["no_str"] or "Next")}: {esc(e["newer"]["headline"][:48])} →</a>' if e.get('newer') else '<span></span>'
    pager += '</div>'
    after += pager + subscribe_form(site, heading='Get tomorrow’s edition', src='edition', wide=True) + '</div>'
    crumbs = f'<p class="crumbs"><a href="/">Blotter</a> › <a href="/editions/">Editions</a> › {esc(e["no_str"] or e["date_long"])}</p>'
    html_body = crumbs + draft + '<article class="edition"><div class="card">' + mast + listen + body + foot + '</div></article>' + after

    og = base + f'/og/{e["date"]}-{e["slug"]}.png'
    ld = [crumbs_ld(site, [('Blotter', '/'), ('Editions', '/editions/'), (e['no_str'] or e['date_long'], e['url'])])]
    art = {
        '@context': 'https://schema.org', '@type': 'NewsArticle', 'headline': e['headline'][:110], 'description': e['summary'],
        'datePublished': e['date'] + 'T11:00:00Z', 'dateModified': e['date'] + 'T11:00:00Z', 'url': base + e['url'],
        'mainEntityOfPage': base + e['url'], 'image': [og], 'articleSection': 'True crime',
        'author': {'@type': 'Organization', 'name': site['name'], 'url': base + '/about/'},
        'publisher': {'@type': 'Organization', 'name': site['name'], 'logo': {'@type': 'ImageObject', 'url': base + '/img/cover-1200.png'}},
        'isAccessibleForFree': True,
    }
    if e['case_objs']:
        art['about'] = [{'@type': 'Thing', 'name': c['name'], 'url': base + c['url']} for c in e['case_objs']]
    ld.append(art)
    if ep.get('share_url'):
        pe = {
            '@context': 'https://schema.org', '@type': 'PodcastEpisode', 'name': ep.get('title') or e['title'], 'url': base + e['url'] + '#listen',
            'datePublished': e['date'], 'description': strip_html(ep.get('notes_html') or e['summary'])[:500],
            'partOfSeries': {'@type': 'PodcastSeries', 'name': site['podcast']['title'], 'url': base + '/podcast/', 'webFeed': site['podcast']['feed_url']},
        }
        if ep.get('duration_s'):
            pe['timeRequired'] = iso_duration(ep['duration_s'])
        if ep.get('media_url'):
            pe['associatedMedia'] = {'@type': 'MediaObject', 'contentUrl': ep['media_url'], 'encodingFormat': 'audio/mpeg'}
        if ep.get('transcript'):
            pe['transcript'] = ep['transcript'][:5000]
        ld.append(pe)
    title = f'{e["headline"]} — The Morning Blotter {e["no_str"]}'.strip(' —')
    return layout(site, title=title, description=e['summary'], path=e['url'], body=html_body, on='editions', ld=ld,
                  og_image=og, og_type='article', noindex=bool(e.get('draft')))


# --------------------------------------------------------------------------------------------- cases --

def case_card(c):
    n = len(c['entries'])
    return (f'<div class="case"><span class="label">{esc(c.get("jurisdiction", ""))}</span><h3><a href="{c["url"]}">{esc(c["name"])}</a></h3>'
            f'<p>{esc(c.get("short", ""))}</p><span class="label">Updated {esc(c["updated_obj"].strftime("%b %-d, %Y"))}'
            + (f' · {n} {"entry" if n == 1 else "entries"}' if n else '') + '</span></div>')


def case_page(site, c, cases):
    base = site['url'].rstrip('/')
    crumbs = f'<p class="crumbs"><a href="/">Blotter</a> › <a href="/cases/">Cases</a> › {esc(c["name"])}</p>'
    head = (f'<div class="card"><p class="card-meta">{esc(c.get("jurisdiction", ""))} • Case file • Updated {esc(c["updated_obj"].strftime("%B %-d, %Y"))}</p>'
            f'<h1>{esc(c["name"])}</h1>' + (f'<p class="case-notes" style="margin:10px 0 0">{esc(c["status"])}</p>' if c.get('status') else '') + '</div>')
    body = ''
    if c.get('summary_html'):
        body += '<div class="sect-head"><span class="label">The record so far</span></div><div class="card prose">' + c['summary_html'] + '</div>'
    if c.get('people'):
        body += '<div class="sect-head"><span class="label">The people</span></div><div class="card"><ul class="people">' + ''.join(
            f'<li><b>{esc(p["name"])}</b> — {esc(p["text"])}</li>' for p in c['people']) + '</ul></div>'
    if c.get('timeline'):
        items = sorted(c['timeline'], key=lambda t: t.get('date', ''))
        body += '<div class="sect-head"><span class="label">Timeline</span></div><div class="card"><ol class="timeline">' + ''.join(
            f'<li><time datetime="{esc(t.get("date", ""))}">{esc(fmt_item_date(t.get("date", "")) if len(t.get("date", "")) == 10 else t.get("date", ""))}</time>{esc(t["text"])}'
            + (f' <span class="src">— <a href="{esc(t["source_url"])}" rel="noopener">{esc(t.get("source_title") or "source")}</a></span>' if t.get('source_url') else '') + '</li>'
            for t in items) + '</ol></div>'
    if c.get('what_next'):
        body += '<div class="sect-head"><span class="label">On the docket</span></div><div class="card"><ul class="docket">' + ''.join(
            f'<li><b>{esc(w.get("date", ""))}</b> {esc(w["text"])}</li>' for w in c['what_next']) + '</ul></div>'
    body += '<div class="sect-head"><span class="label">In the Blotter</span><a href="/editions/?case=' + esc(c['slug']) + '">Filter the archive</a></div>'
    body += ledger(c['entries'], cases, head=False) if c['entries'] else '<div class="card"><p class="empty">No editions have filed on this case yet.</p></div>'
    if c.get('sources'):
        body += '<div class="sect-head"><span class="label">Sources</span></div><ol class="sources">' + ''.join(
            f'<li><a href="{esc(s["url"])}" rel="noopener">{esc(s.get("title") or s["url"])}</a>' + (f' — {esc(s["outlet"])}' if s.get('outlet') else '') + (f', {esc(fmt_item_date(s["date"]))}' if s.get('date') else '') + '</li>'
            for s in c['sources']) + '</ol>'
    if c.get('tip_line'):
        body += f'<div class="card"><p class="meta">Tips</p><p>{esc(c["tip_line"])}</p></div>'
    body += subscribe_form(site, heading=f'Follow this case', blurb=f'Every development in {c["name"]} — and every other case on the desk — in your inbox at {site["send_time"]}.', src='case', wide=True)
    ld = [crumbs_ld(site, [('Blotter', '/'), ('Cases', '/cases/'), (c['name'], c['url'])]), {
        '@context': 'https://schema.org', '@type': 'Article', 'headline': f'{c["name"]}: what we know', 'description': c.get('short', ''),
        'dateModified': c['updated_obj'].isoformat(), 'url': base + c['url'], 'mainEntityOfPage': base + c['url'],
        'author': {'@type': 'Organization', 'name': site['name']}, 'publisher': {'@type': 'Organization', 'name': site['name'], 'logo': {'@type': 'ImageObject', 'url': base + '/img/cover-1200.png'}},
        'image': [base + '/og/default.png'],
    }]
    return layout(site, title=f'{c["name"]}: what we know — The Morning Blotter', description=c.get('short', ''), path=c['url'],
                  body=crumbs + head + body, on='cases', ld=ld, og_type='article')


def cases_index(site, cases):
    cs = sorted(cases.values(), key=lambda c: c['updated_obj'], reverse=True)
    body = ('<p class="crumbs"><a href="/">Blotter</a> › Cases</p><div class="card"><h1>Cases we track</h1>'
            '<p style="margin:10px 0 0">The cases the desk follows day to day: the record so far, the timeline, what is on the docket, and every edition that touched them. '
            'Nobody who has not been charged is speculated about here; what the record says is what these pages say.</p></div>')
    body += '<div class="cases">' + ''.join(case_card(c) for c in cs) + '</div>' if cs else '<div class="card"><p class="empty">No case files yet.</p></div>'
    body += subscribe_form(site, heading='Every case, every morning', src='cases', wide=True)
    return layout(site, title='Cases we track — The Morning Blotter', description='The cases The Morning Blotter follows day to day: the record so far, the timeline, and every edition that touched them.',
                  path='/cases/', body=body, on='cases', ld=[crumbs_ld(site, [('Blotter', '/'), ('Cases', '/cases/')])])


# -------------------------------------------------------------------------------------------- podcast --

def episode_row(p, site):
    where = p['url'] + ('#listen' if p.get('edition') else '')
    ttl = f'<a href="{where}">{esc(p["title"])}</a>'
    meta = f'{esc(fmt_item_date(p["date"]))}' + (f' • {esc(p["duration_mmss"])}' if p.get('duration_mmss') else '')
    return (f'<li><p class="meta">{meta}</p><h3>{ttl}</h3><p>{esc(p.get("summary", ""))}</p>'
            f'<p><a class="btn btn-ghost" href="{where}">▶ Listen</a> ' + (f'<a href="{esc(p["share_url"])}" rel="noopener" style="margin-left:10px;font-family:var(--sans);font-size:11px;letter-spacing:.14em;text-transform:uppercase">Share page</a>' if p.get('share_url') else '') + '</p></li>')


def podcast_page(site, episodes):
    base = site['url'].rstrip('/')
    p = site['podcast']
    hosts = ''.join(f'<div class="host"><h3>{esc(h["name"])}</h3><span class="label">{esc(h["role"])}</span><p>{esc(h["blurb"])}</p></div>' for h in p['hosts'])
    latest = episodes[0] if episodes else None
    body = ('<p class="crumbs"><a href="/">Blotter</a> › Podcast</p>'
            '<div class="pod"><div><img src="/img/cover-1200.png" width="1200" height="1200" alt="The Morning Blotter podcast cover"></div>'
            f'<div><h1>The Morning Blotter, on the air</h1><p>Every morning at seven, two people sit down at the crime desk: <b>Casey Quinn</b>, the courts reporter who says the victims’ names, and <b>Ray Sullivan</b>, the Bronx cop turned FBI profiler who takes the case apart. '
            'Ten to fifteen minutes a day — the top case, the Wire, the Case File, the Docket. Sundays, <b>The Sunday File</b> goes deep on one case.</p>'
            '<p class="meta">Listen on</p>' + directory_links(site) + '</div></div>')
    if latest:
        body += '<div class="sect-head"><span class="label">Latest episode</span></div><div class="card"><p class="meta">' + esc(fmt_item_date(latest['date'])) + (f' • {esc(latest["duration_mmss"])}' if latest.get('duration_mmss') else '') + f'</p><h2><a href="{latest["url"]}{"#listen" if latest.get("edition") else ""}">{esc(latest["title"])}</a></h2><p>{esc(latest.get("summary", ""))}</p>' + player(latest.get('share_url'), title=latest['title']) + '</div>'
    body += '<div class="sect-head"><span class="label">The hosts</span></div><div class="hosts">' + hosts + '</div>'
    body += '<div class="sect-head"><span class="label">Every episode</span></div><ul class="ep-list">' + ''.join(episode_row(x, site) for x in episodes) + '</ul>'
    body += ('<div class="card"><p class="meta">How this program is made</p><p>The Morning Blotter is a produced program: Ray and Casey are AI-voiced storytellers, written and edited by a human desk, and every fact they say comes from the sources linked in that morning’s email edition. '
             'The audio is the companion to the brief — the brief is where the links live.</p></div>')
    body += subscribe_form(site, heading='The brief behind the program, free', src='podcast', wide=True)
    ld = [crumbs_ld(site, [('Blotter', '/'), ('Podcast', '/podcast/')]), {
        '@context': 'https://schema.org', '@type': 'PodcastSeries', 'name': p['title'], 'url': base + '/podcast/', 'webFeed': p['feed_url'],
        'image': base + '/img/cover-1200.png', 'description': strip_html(site['description']),
        'author': {'@type': 'Organization', 'name': site['name']}, 'inLanguage': 'en',
        'sameAs': [d['url'] for d in p['directories'] if d['name'] != 'RSS'],
    }]
    return layout(site, title='The Morning Blotter podcast — Ray Sullivan and Casey Quinn at the crime desk', description='The daily true-crime podcast from The Morning Blotter: Casey Quinn and Ray Sullivan on the top case, the Wire, the Case File and the Docket, ten to fifteen minutes every morning.',
                  path='/podcast/', body=body, on='podcast', ld=ld)


def episode_page(site, p):
    base = site['url'].rstrip('/')
    crumbs = f'<p class="crumbs"><a href="/">Blotter</a> › <a href="/podcast/">Podcast</a> › {esc(p["title"])}</p>'
    body = (crumbs + f'<article><div class="card"><p class="card-meta">Podcast • {esc(fmt_item_date(p["date"]))}' + (f' • {esc(p["duration_mmss"])}' if p.get('duration_mmss') else '') + '</p>'
            f'<h1>{esc(p["title"])}</h1><div class="ed-listen" id="listen" style="margin:16px -28px 0;border-top:1px solid var(--rule)">'
            f'<a class="btn" href="{esc(p.get("share_url", "#"))}" rel="noopener">▶ Listen — {esc(p.get("duration_mmss", ""))}</a>' + player(p.get('share_url'), title=p['title']) + '</div>'
            '<div class="prose" style="margin-top:18px">' + (p.get('notes_html') or f'<p>{esc(p.get("summary", ""))}</p>') + '</div>'
            '<p class="meta">Listen on</p>' + directory_links(site) + '</div>')
    if p.get('transcript'):
        body += '<details class="transcript" open><summary>Transcript</summary>' + transcript_html(p['transcript']) + '</details>'
    body += '</article>' + subscribe_form(site, heading='The brief behind the program, free', src='episode', wide=True)
    ld = [crumbs_ld(site, [('Blotter', '/'), ('Podcast', '/podcast/'), (p['title'], p['url'])]), {
        '@context': 'https://schema.org', '@type': 'PodcastEpisode', 'name': p['title'], 'url': base + p['url'], 'datePublished': p['date'],
        'description': strip_html(p.get('notes_html') or p.get('summary', ''))[:500],
        'partOfSeries': {'@type': 'PodcastSeries', 'name': site['podcast']['title'], 'url': base + '/podcast/', 'webFeed': site['podcast']['feed_url']},
        **({'timeRequired': iso_duration(p['duration_s'])} if p.get('duration_s') else {}),
        **({'associatedMedia': {'@type': 'MediaObject', 'contentUrl': p['media_url'], 'encodingFormat': 'audio/mpeg'}} if p.get('media_url') else {}),
    }]
    return layout(site, title=f'{p["title"]} — The Morning Blotter podcast', description=p.get('summary', ''), path=p['url'], body=body, on='podcast', ld=ld, og_type='article')


# --------------------------------------------------------------------------------------- home / archive --

def home_page(site, editions, cases, episodes):
    latest = editions[0] if editions else None
    latest_ep = episodes[0] if episodes else None
    if latest:
        ep = latest.get('episode') or {}
        hero = (f'<div class="card"><span class="stamp">Filed {esc(latest["date_obj"].strftime("%b %-d"))} · {esc(site["send_time"])}</span>'
                f'<p class="card-meta">Vol. {esc(latest.get("vol", ""))} • {esc(latest["no_str"])} • {esc(latest["date_long"])}</p>'
                f'<div class="chips">{chips_html(latest)}</div><h2><a href="{latest["url"]}" style="color:var(--ink)">{esc(latest["headline"])}</a></h2>'
                f'<p>{esc(latest["summary"])}</p><div class="hero-actions"><a class="btn" href="{latest["url"]}">Read the brief</a>'
                + (f'<a class="btn btn-ghost" href="{latest["url"]}#listen">▶ Listen — {esc(mmss(ep.get("duration_s")))}</a>' if ep.get('share_url') else '') + '</div>'
                + (player(ep['share_url'], title=latest['title']) if ep.get('share_url') else '') + '</div>')
    else:
        hero = ('<div class="card"><span class="stamp">Desk opening</span><h2>The first edition files soon.</h2>'
                '<p>True crime every morning at seven — the top case, the wire, one case told properly, and what is on the docket. Every headline links to its original source.</p>'
                + (f'<div class="hero-actions"><a class="btn btn-ghost" href="{latest_ep["url"]}#listen">▶ Listen — {esc(latest_ep["title"])}</a></div>' + player(latest_ep.get('share_url'), title=latest_ep['title']) if latest_ep else '') + '</div>')
    aside = '<div class="aside">' + subscribe_form(site, heading='Get the brief, free', src='home') + '</div>'
    body = '<div class="hero">' + hero + aside + '</div>'
    recent = editions[:12]
    body += '<div class="sect-head"><span class="label">The blotter — recent entries</span><a href="/editions/">All entries &amp; search →</a></div>' + ledger(recent, cases)
    tracked = sorted(cases.values(), key=lambda c: c['updated_obj'], reverse=True)[:6]
    if tracked:
        body += '<div class="sect-head"><span class="label">Cases we’re tracking</span><a href="/cases/">All cases →</a></div><div class="cases">' + ''.join(case_card(c) for c in tracked) + '</div>'
    body += ('<div class="sect-head"><span class="label">The podcast</span><a href="/podcast/">Every episode →</a></div>'
             '<div class="pod"><div><a href="/podcast/"><img src="/img/cover-600.png" width="600" height="600" alt="The Morning Blotter podcast cover"></a></div>'
             '<div class="card" style="margin:0"><h3 style="margin:0 0 8px">Ray Sullivan and Casey Quinn, every morning</h3>'
             '<p style="margin:0 0 10px">Casey says the victims’ names. Ray takes the case apart from the record. Ten to fifteen minutes a day, and The Sunday File on Sundays.</p>'
             + (f'<p style="margin:0 0 10px"><b>Latest:</b> <a href="{latest_ep["url"]}{"#listen" if latest_ep.get("edition") else ""}">{esc(latest_ep["title"])}</a>' + (f' ({esc(latest_ep["duration_mmss"])})' if latest_ep.get('duration_mmss') else '') + '</p>' if latest_ep else '')
             + '<p class="meta">Listen on</p>' + directory_links(site) + '</div></div>')
    ld = [org_ld(site), website_ld(site)]
    return layout(site, title='The Morning Blotter — True crime, every morning, reported with care', description=site['description'], path='/', body=body, home=True, ld=ld)


def archive_page(site, editions, cases):
    case_opts = ''.join(f'<option value="{esc(c["slug"])}">{esc(c["name"])}</option>' for c in sorted(cases.values(), key=lambda c: c['name']) if c['entries'])
    states = sorted({s for e in editions for s in e['states']})
    state_opts = ''.join(f'<option value="{esc(s)}">{esc(STATE_NAMES.get(s, s))}</option>' for s in states)
    months = []
    for e in editions:
        if (e['month'], e['month_label']) not in months:
            months.append((e['month'], e['month_label']))
    month_opts = ''.join(f'<option value="{m}">{esc(l)}</option>' for m, l in months)
    sect_opts = ''.join(f'<option value="{k}">{esc(v)}</option>' for k, v in SECTION_LABELS.items() if k in {t for e in editions for t in e['section_types']})
    filters = ('<form class="filters" onsubmit="return false" role="search"><div class="q"><label for="q">Search the blotter</label>'
               '<input id="q" type="search" placeholder="A name, a place, a case…" autocomplete="off"></div>'
               f'<div><label for="f-case">Case</label><select id="f-case"><option value="">All cases</option>{case_opts}</select></div>'
               f'<div><label for="f-state">State</label><select id="f-state"><option value="">All states</option>{state_opts}</select></div>'
               f'<div><label for="f-section">Section</label><select id="f-section"><option value="">All sections</option>{sect_opts}</select></div>'
               f'<div><label for="f-month">Month</label><select id="f-month"><option value="">All months</option>{month_opts}</select></div>'
               '<button id="f-clear" class="clear" type="button">Clear</button></form>')
    body = ('<p class="crumbs"><a href="/">Blotter</a> › Editions</p><div class="card" style="padding:20px 24px"><h1>Every entry in the blotter</h1>'
            '<p style="margin:8px 0 0">Every edition we have filed, newest first. Search by a name, a place or a case; filter by case, state, section or month. Each entry opens the full brief with its sources, the episode, and the transcript.</p></div>'
            + filters + f'<p class="count" id="count">{len(editions)} entries</p>' + ledger(editions, cases)
            + '<p class="empty" id="empty" style="display:none">Nothing matches — clear a filter or try another word.</p>'
            + subscribe_form(site, heading='Tomorrow’s entry, in your inbox', src='archive', wide=True))
    ld = [crumbs_ld(site, [('Blotter', '/'), ('Editions', '/editions/')]), {
        '@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'The Morning Blotter — every edition', 'url': site['url'].rstrip('/') + '/editions/',
        'hasPart': [{'@type': 'NewsArticle', 'headline': e['headline'][:110], 'url': site['url'].rstrip('/') + e['url'], 'datePublished': e['date']} for e in editions[:50]],
    }]
    return layout(site, title='Every edition — The Morning Blotter archive, searchable', description='The searchable archive of The Morning Blotter: every daily true-crime brief, filterable by case, state, section and month.',
                  path='/editions/', body=body, on='editions', ld=ld, js=ARCHIVE_JS)


# ------------------------------------------------------------------------------------------ static pages --

def about_page(site):
    p = site['podcast']
    hosts = ''.join(f'<div class="host"><h3>{esc(h["name"])}</h3><span class="label">{esc(h["role"])}</span><p>{esc(h["blurb"])}</p></div>' for h in p['hosts'])
    body = ('<p class="crumbs"><a href="/">Blotter</a> › About</p><div class="card prose"><h1>About The Morning Blotter</h1>'
            '<p style="margin-top:12px">Every police station in America keeps a book — who came in, what happened to them, what time. They called it the blotter. '
            'The Morning Blotter is that book for the whole country, kept properly: a free daily email at 7:00 AM ET with the day’s top case, the wire, one case told start to finish, and what is on the docket — '
            'and a two-host podcast edition that puts a courts reporter and a former profiler at the desk together.</p>'
            '<h2>How we source</h2><p>Court records and filings first; then official statements from police, prosecutors and medical examiners; then established news outlets and credible legal and genre trade press. '
            'Never forums, never unverified social posts, never rumor. Every headline in the brief links to its original source, and every link is checked before the edition goes out — details can evolve, so check the link before repeating them.</p>'
            '<h2>How we report</h2><p>Victims are named with respect, and named again. The accused are presumed innocent until a jury says otherwise. Nobody who has not been charged gets speculated about. '
            'We leave out details that would make somebody’s worst day into entertainment, and we say so when we do. We don’t try cases in the mailbag.</p>'
            '<h2>The program</h2><p>The podcast is a produced program. Ray Sullivan and Casey Quinn are AI-voiced storytellers, written and edited by a human desk; every fact they say comes from the sources linked in that morning’s brief. '
            'We say this in every episode’s notes and here, because a listener is owed it.</p></div>'
            '<div class="sect-head"><span class="label">The hosts</span></div><div class="hosts">' + hosts + '</div>'
            '<div class="card prose" style="margin-top:22px"><h2>Write to the desk</h2>'
            f'<p><b>Questions for Ray and Casey:</b> <a href="mailto:{esc(site["email"]["mailbag"])}">{esc(site["email"]["mailbag"])}</a> — first names only on the air; we don’t read tips about private people.</p>'
            f'<p><b>Corrections and everything else:</b> <a href="mailto:{esc(site["email"]["hello"])}">{esc(site["email"]["hello"])}</a>. '
            f'<b>Sponsorship:</b> one sponsor per edition, clearly labeled, never inside the reporting — <a href="mailto:{esc(site["email"]["partners"])}">{esc(site["email"]["partners"])}</a>.</p></div>'
            + subscribe_form(site, heading='Get the brief, free', src='about', wide=True))
    ld = [crumbs_ld(site, [('Blotter', '/'), ('About', '/about/')]), org_ld(site)]
    return layout(site, title='About The Morning Blotter — how we source and how we report', description='What The Morning Blotter is, how it sources, how it reports on victims and the accused, and who Ray Sullivan and Casey Quinn are.',
                  path='/about/', body=body, on='about', ld=ld)


def subscribe_page(site):
    body = ('<p class="crumbs"><a href="/">Blotter</a> › Subscribe</p><div class="card"><h1>Subscribe to The Morning Blotter</h1>'
            f'<p style="margin:12px 0 0">Free, every morning at {esc(site["send_time"])}: the top case, the wire, the Case File, the Docket — every headline linked to its source — with the podcast edition one tap away. '
            'You confirm with one click; you leave with one click, from the footer of any edition.</p></div>'
            + subscribe_form(site, heading='Your address, and that’s it', src='subscribe-page', wide=True)
            + '<div class="card" style="margin-top:22px"><p class="meta">What happens next</p><p>We send one confirmation email. Click it and your first edition arrives the next morning. We don’t sell, rent or share the list, and we don’t track opens.</p>'
            f'<p class="meta" style="margin-top:14px">Prefer email?</p><p>Send <b>Subscribe - Morning Blotter</b> to <a href="mailto:{esc(site["email"]["subscribe"])}?subject=Subscribe%20-%20Morning%20Blotter">{esc(site["email"]["subscribe"])}</a> and the desk will do the same thing by hand.</p></div>')
    return layout(site, title='Subscribe free — The Morning Blotter', description='Get The Morning Blotter free: the daily true-crime brief in your inbox at 7:00 AM ET, every headline linked to its source.',
                  path='/subscribe/', body=body, on='', ld=[crumbs_ld(site, [('Blotter', '/'), ('Subscribe', '/subscribe/')])])


def privacy_page(site):
    body = ('<p class="crumbs"><a href="/">Blotter</a> › Privacy</p><div class="card prose"><h1>Privacy</h1>'
            '<p style="margin-top:12px"><b>What we keep.</b> If you subscribe, we keep your email address, the date you subscribed and confirmed, and where the subscription came from (this site or an email to the desk). That is the whole record.</p>'
            '<p><b>What we do with it.</b> We send you the edition. We don’t sell, rent or share the list, and we don’t track whether you open the emails or click the links.</p>'
            '<p><b>Leaving.</b> Every edition carries a one-click unsubscribe. It removes you the moment you use it. You can also write to the desk.</p>'
            '<p><b>This site.</b> It is a static site — no accounts, no advertising trackers, no analytics cookies. The podcast player is embedded from our hosting provider, Transistor, which serves the audio; fonts are served by Google Fonts.</p>'
            f'<p><b>Questions.</b> <a href="mailto:{esc(site["email"]["hello"])}">{esc(site["email"]["hello"])}</a>.</p></div>')
    return layout(site, title='Privacy — The Morning Blotter', description='What The Morning Blotter keeps when you subscribe, what it does with it, and how to leave.', path='/privacy/', body=body)


def not_found_page(site):
    body = ('<div class="card" style="text-align:center;padding:40px 24px"><span class="stamp">No such entry</span><h1>Nothing in the book at that address.</h1>'
            '<p style="margin:12px 0 18px">The page may have moved, or the link was copied short. Try the archive — it is searchable.</p>'
            '<p><a class="btn" href="/editions/">Search the blotter</a> <a class="btn btn-ghost" href="/">Home</a></p></div>')
    return layout(site, title='Not found — The Morning Blotter', description='Nothing in the book at that address.', path='/404.html', body=body, noindex=True)


# ---------------------------------------------------------------------------------------- feeds & seo --

def feed_xml(site, editions):
    base = site['url'].rstrip('/')
    items = ''
    for e in editions[:30]:
        if e.get('draft'):
            continue
        link = base + e['url']
        desc = esc(e['summary'])
        enclosure = ''
        ep = e.get('episode') or {}
        if ep.get('media_url'):
            enclosure = f'<enclosure url="{esc(ep["media_url"])}" type="audio/mpeg" length="0"/>'
        items += (f'<item><title>{esc(e["title"])}</title><link>{link}</link><guid isPermaLink="true">{link}</guid>'
                  f'<pubDate>{rfc2822(e["date_obj"])}</pubDate><description>{desc}</description>{enclosure}</item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f'<title>{esc(site["name"])} — editions</title><link>{base}/</link><description>{esc(strip_html(site["description"]))}</description>'
            f'<language>en-us</language><atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>'
            f'<image><url>{base}/img/cover-600.png</url><title>{esc(site["name"])}</title><link>{base}/</link></image>'
            + items + '</channel></rss>')


def sitemap_xml(site, editions, cases, episodes):
    base = site['url'].rstrip('/')
    today = dt.date.today().isoformat()
    urls = [('/', today, 'daily', '1.0'), ('/editions/', today, 'daily', '0.9'), ('/cases/', today, 'weekly', '0.8'),
            ('/podcast/', today, 'daily', '0.8'), ('/about/', today, 'monthly', '0.5'), ('/subscribe/', today, 'monthly', '0.7'), ('/privacy/', today, 'yearly', '0.2')]
    for e in editions:
        if not e.get('draft'):
            urls.append((e['url'], e['date'], 'never', '0.8' if e is editions[0] else '0.6'))
    for c in cases.values():
        urls.append((c['url'], c['updated_obj'].isoformat(), 'weekly', '0.7'))
    for p in episodes:
        if not p.get('edition'):
            urls.append((p['url'], p['date'], 'never', '0.5'))
    body = ''.join(f'<url><loc>{base}{esc(u)}</loc><lastmod>{m}</lastmod><changefreq>{f}</changefreq><priority>{p}</priority></url>' for u, m, f, p in urls)
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + '</urlset>'


def robots_txt(site):
    return f'User-agent: *\nAllow: /\nSitemap: {site["url"].rstrip("/")}/sitemap.xml\n'


# --------------------------------------------------------------------------------------------- images --

def make_images(out, site, editions):
    """Cover derivatives, favicons and share cards. Needs Pillow; skipped (with a notice) when it is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print('  [images] Pillow not installed — share cards skipped (pip install pillow)', file=sys.stderr)
        return
    img_dir = os.path.join(out, 'img')
    og_dir = os.path.join(out, 'og')
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(og_dir, exist_ok=True)
    cover_src = os.path.join(STATIC, 'img', 'cover.png')
    if os.path.exists(cover_src):
        cover = Image.open(cover_src).convert('RGB')
        for size in (1200, 600, 180, 32):
            name = {1200: 'cover-1200.png', 600: 'cover-600.png', 180: 'apple-touch-icon.png', 32: 'favicon.png'}[size]
            im = cover.resize((size, size), Image.LANCZOS)
            im.save(os.path.join(img_dir if size >= 600 else out, name), optimize=True)
    fonts = os.path.join(STATIC, 'fonts')

    def font(name, size):
        try:
            return ImageFont.truetype(os.path.join(fonts, name), size)
        except OSError:
            return ImageFont.load_default()

    def card(headline, kicker, footer_text, path):
        W, H = 1200, 630
        im = Image.new('RGB', (W, H), '#fbf8f0')
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 22], fill='#a02128')
        d.rectangle([0, H - 22, W, H], fill='#a02128')
        f_wm = font('PlayfairDisplay-Black.ttf', 44)
        d.text((80, 62), 'THE MORNING', font=f_wm, fill='#16130e')
        w = d.textlength('THE MORNING ', font=f_wm)
        d.text((80 + w, 62), 'BLOTTER', font=f_wm, fill='#a02128')
        d.line([80, 122, W - 80, 122], fill='#16130e', width=3)
        d.line([80, 128, W - 80, 128], fill='#16130e', width=1)
        f_k = font('SpecialElite-Regular.ttf', 26)
        d.text((80, 150), kicker.upper(), font=f_k, fill='#77705f')
        # headline, wrapped
        size = 66 if len(headline) < 60 else 56 if len(headline) < 90 else 46
        f_h = font('PlayfairDisplay-Bold.ttf', size)
        lines, cur = [], ''
        for word in headline.split():
            t = (cur + ' ' + word).strip()
            if d.textlength(t, font=f_h) > W - 160 and cur:
                lines.append(cur)
                cur = word
            else:
                cur = t
        if cur:
            lines.append(cur)
        lines = lines[:4]
        y = 205
        for ln in lines:
            d.text((80, y), ln, font=f_h, fill='#16130e')
            y += int(size * 1.18)
        f_f = font('SpecialElite-Regular.ttf', 22)
        d.text((80, H - 78), footer_text.upper(), font=f_f, fill='#a02128')
        im.save(path, optimize=True)

    card('True crime, every morning — reported with care.', 'The daily brief · 7:00 AM ET · free', 'morningblotter.com', os.path.join(og_dir, 'default.png'))
    for e in editions:
        kicker = f'{e["no_str"]} · {e["date_long"]}' if e['no_str'] else e['date_long']
        card(e['headline'], kicker, 'morningblotter.com · read the brief, listen to the episode', os.path.join(og_dir, f'{e["date"]}-{e["slug"]}.png'))


FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#fbf8f0"/>'
               '<rect width="64" height="7" fill="#a02128"/><rect y="57" width="64" height="7" fill="#a02128"/>'
               '<text x="32" y="46" text-anchor="middle" font-family="Georgia,serif" font-weight="bold" font-size="40" fill="#a02128">B</text></svg>')


# ----------------------------------------------------------------------------------------------- main --

def build(out='_site', drafts=False, base=None, site_dir=DATA):
    site, editions, cases, episodes = load(site_dir, drafts=drafts)
    if base:
        site['url'] = base
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    # static
    if os.path.isdir(os.path.join(STATIC, 'img')):
        shutil.copytree(os.path.join(STATIC, 'img'), os.path.join(out, 'img'), dirs_exist_ok=True)
    write(os.path.join(out, 'favicon.svg'), FAVICON_SVG)
    make_images(out, site, editions)
    # pages
    pages = {
        'index.html': home_page(site, editions, cases, episodes),
        'editions/index.html': archive_page(site, editions, cases),
        'cases/index.html': cases_index(site, cases),
        'podcast/index.html': podcast_page(site, episodes),
        'about/index.html': about_page(site),
        'subscribe/index.html': subscribe_page(site),
        'privacy/index.html': privacy_page(site),
        '404.html': not_found_page(site),
        'feed.xml': feed_xml(site, editions),
        'sitemap.xml': sitemap_xml(site, editions, cases, episodes),
        'robots.txt': robots_txt(site),
    }
    for e in editions:
        pages[e['url'].strip('/') + '/index.html'] = edition_page(site, e, cases)
    for c in cases.values():
        pages[c['url'].strip('/') + '/index.html'] = case_page(site, c, cases)
    for p in episodes:
        if not p.get('edition'):
            pages[p['url'].strip('/') + '/index.html'] = episode_page(site, p)
    for rel, text in pages.items():
        write(os.path.join(out, rel), text)
    host = re.sub(r'^https?://', '', site['url']).strip('/')
    if '/' not in host and not host.endswith('github.io'):
        write(os.path.join(out, 'CNAME'), host + '\n')
    write(os.path.join(out, '.nojekyll'), '')
    print(f'built {len(pages)} pages → {out}/  ({len(editions)} editions, {len(cases)} cases, {len(episodes)} episodes)')
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(ROOT, '_site'))
    ap.add_argument('--drafts', action='store_true', help='include editions marked draft (preview builds)')
    ap.add_argument('--base', default=None, help='override the site URL (e.g. a preview host)')
    ap.add_argument('--data', default=DATA)
    a = ap.parse_args()
    build(a.out, drafts=a.drafts, base=a.base, site_dir=a.data)


if __name__ == '__main__':
    main()
