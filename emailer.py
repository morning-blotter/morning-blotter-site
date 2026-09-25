#!/usr/bin/env python3
"""
The Morning Blotter — the email edition, built from the same edition JSON the site uses.

    python3 emailer.py data/editions/2026-09-26.json --out edition.html
    python3 emailer.py data/editions/2026-09-26.json --site data/site.json --page-url https://morningblotter.com/editions/2026-09-26-.../ --out edition.html

Table-based, every style inline, Outlook-safe (no flexbox/grid/external CSS), 640px container, under 95 KB.
The footer's unsubscribe button links to the literal {{UNSUB_URL}} — the send endpoint replaces it per recipient.
Standard library only, so the daily run can fetch this one file from the site repo and import it.
"""
import argparse
import datetime as dt
import html
import json
import os
import re

INK, TEXT, CRIMSON, DEEP, MUTED = '#16130e', '#2e2a24', '#a02128', '#7c1a20', '#77705f'
PAPER, CARD, RULE, MANILA, MANILA_RULE = '#eee8db', '#fbf8f0', '#d8d0bd', '#f5ecd7', '#dbcda4'
SERIF = "Georgia,'Times New Roman',Times,serif"
SANS = 'Arial,Helvetica,sans-serif'

SECTION_LABELS = {
    'top_case': 'THE TOP CASE', 'blotter': 'THE BLOTTER', 'case_file': 'THE CASE FILE', 'microscope': 'UNDER THE MICROSCOPE',
    'watch_list': 'THE WATCH LIST', 'presented_by': 'PRESENTED BY', 'docket': 'ON THE DOCKET', 'sunday_file': 'THE SUNDAY FILE', 'mailbag': 'THE MAILBAG',
}
PRESENTED_BY_DEFAULT = ('…no one, yet. One sponsor per edition, clearly labeled, never inside the reporting. '
                        'Reach a daily audience of true-crime readers: <a href="mailto:partners@morningblotter.com" style="color:#a02128;">partners@morningblotter.com</a>.')


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(s or ''))).strip()


def words(s):
    return len(strip_html(s).split())


def read_minutes(e):
    total = words(e.get('intro_html', ''))
    for sec in e.get('sections', []):
        total += words(sec.get('body_html', '')) + words(sec.get('case_notes', '')) + words(sec.get('html', ''))
        for it in sec.get('items', []):
            total += words(it.get('body_html', '')) + words(it.get('text', '')) + words(it.get('note', '')) + words(it.get('headline', ''))
    return max(1, round(total / 220))


def mmss(seconds):
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ''
    return f'{s // 60}:{s % 60:02d}'


def date_long(s):
    d = dt.date.fromisoformat(str(s)[:10])
    return d.strftime('%A, %B %-d, %Y').upper()


def short_date(s):
    d = dt.date.fromisoformat(str(s)[:10])
    return d.strftime('%a., %b. %-d').replace('May.', 'May').replace('Jun.', 'June').replace('Jul.', 'July').replace('Sep.', 'Sept.')


def subject(e):
    """`The Morning Blotter — Nº {N} — {Wkdy}., {Mon}. {D}: {top case ≤8 words}` — prefix and date token are load-bearing."""
    if e.get('subject'):
        return e['subject']
    return f"The Morning Blotter — Nº {e.get('no', '')} — {short_date(e['date'])}: {e.get('headline', '')}"


def fmt_item_date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]).strftime('%b %-d, %Y')
    except Exception:
        return s or ''


# ------------------------------------------------------------------------------------------ pieces --

def p(text, extra=''):
    return f'<p style="margin:0 0 12px 0;font-family:{SERIF};font-size:16px;line-height:24px;color:{TEXT};{extra}">{text}</p>'


def body_html(s):
    """Inline the paragraph style into author-supplied body HTML (it arrives as plain <p>…</p> blocks)."""
    s = str(s or '')
    s = re.sub(r'<p(?![^>]*style=)', f'<p style="margin:0 0 12px 0;font-family:{SERIF};font-size:16px;line-height:24px;color:{TEXT};"', s)
    s = re.sub(r'<a (?![^>]*style=)', f'<a style="color:{CRIMSON};" ', s)
    return s


def chip(text, kind='outline'):
    if not text:
        return ''
    if kind == 'solid':
        st = f'background:{CRIMSON};color:{CARD};border:1px solid {CRIMSON};'
    elif kind == 'ink':
        st = f'background:{INK};color:{CARD};border:1px solid {INK};'
    else:
        st = f'background:transparent;color:{CRIMSON};border:1px solid {CRIMSON};'
    return (f'<span style="display:inline-block;{st}font-family:{SANS};font-size:10px;font-weight:bold;letter-spacing:1.5px;'
            f'text-transform:uppercase;padding:3px 7px 2px 7px;margin:0 6px 6px 0;line-height:12px;">{esc(text)}</span>')


def label(text):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 12px 0;"><tr>'
            f'<td style="border-top:2px solid {INK};padding:10px 0 0 0;font-family:{SANS};font-size:12px;font-weight:bold;letter-spacing:3px;'
            f'text-transform:uppercase;color:{INK};">{esc(text)}</td></tr></table>')


def meta(parts):
    txt = ' • '.join(esc(x) for x in parts if x)
    return f'<div style="font-family:{SANS};font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{MUTED};margin:0 0 8px 0;">{txt}</div>' if txt else ''


def headline(it, size=20):
    h = esc(it.get('headline', ''))
    if it.get('url'):
        h = f'<a href="{esc(it["url"])}" style="color:{INK};text-decoration:none;">{h}</a>'
    return f'<div style="font-family:{SERIF};font-size:{size}px;line-height:{size + 5}px;font-weight:bold;color:{INK};margin:0 0 4px 0;">{h}</div>'


def item(it, top=False):
    return (chip(it.get('chip'), 'solid' if top else 'outline') + headline(it, 22 if top else 19)
            + meta([it.get('jurisdiction'), it.get('source'), fmt_item_date(it.get('date'))]) + body_html(it.get('body_html') or (f'<p>{esc(it["text"])}</p>' if it.get('text') else ''))
            + '<div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>')


def button(text, url, color=CRIMSON):
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;"><tr>'
            f'<td style="background:{color};padding:12px 24px;" align="center"><a href="{esc(url)}" style="display:inline-block;color:{CARD};font-family:{SANS};'
            f'font-size:13px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;text-decoration:none;">{text}</a></td></tr></table>')


# ------------------------------------------------------------------------------------------ sections --

def section(e, sec):
    t = sec.get('type', '')
    lab = sec.get('label') or SECTION_LABELS.get(t, t.replace('_', ' ').upper())
    if t == 'top_case':
        notes = p(f'<i><b>Case notes:</b> {esc(sec["case_notes"])}</i>', f'color:{DEEP};') if sec.get('case_notes') else ''
        return label(lab) + item(sec, top=True) + notes
    if t == 'blotter':
        return label(lab) + ''.join(item(it) for it in sec.get('items', []))
    if t in ('case_file', 'sunday_file'):
        n = sec.get('no') or e.get('no')
        title = f'{lab} Nº {n}' if n else lab
        pull = ''
        if sec.get('pull_quote'):
            pull = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 14px 0;"><tr>'
                    f'<td style="border-left:4px solid {CRIMSON};padding:4px 0 4px 14px;font-family:{SERIF};font-size:20px;line-height:27px;color:{DEEP};font-weight:bold;">'
                    f'{esc(sec["pull_quote"])}</td></tr></table>')
        src = ''
        if sec.get('sources'):
            src = (f'<div style="font-family:{SANS};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{MUTED};margin:0 0 10px 0;">Sources: '
                   + ' · '.join(f'<a href="{esc(s["url"])}" style="color:{DEEP};">{esc(s.get("title") or s.get("outlet") or s["url"])}</a>' for s in sec['sources']) + '</div>')
        inner = (f'<div style="font-family:{SERIF};font-size:22px;line-height:27px;font-weight:bold;color:{INK};margin:0 0 10px 0;">{esc(sec.get("title", ""))}</div>'
                 + body_html(sec.get('body_html', '')) + pull + src
                 + f'<div style="font-family:{SANS};font-size:11px;letter-spacing:3px;text-transform:uppercase;color:{MUTED};">— Filed by the Blotter desk</div>')
        return (label(title) + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                f'<td style="background:{MANILA};border:1px solid {MANILA_RULE};padding:18px 20px;">{inner}</td></tr></table>')
    if t == 'microscope':
        return label(lab) + item(sec)
    if t == 'watch_list':
        rows = ''
        for it in sec.get('items', []):
            chips = ''.join(chip(x, 'ink') for x in [it.get('kind'), it.get('platform'), it.get('date')] if x)
            ttl = f'<a href="{esc(it["url"])}" style="color:{INK};">{esc(it["title"])}</a>' if it.get('url') else esc(it.get('title', ''))
            rows += (f'<div style="margin:0 0 10px 0;">{chips}<div style="font-family:{SERIF};font-size:16px;line-height:24px;color:{TEXT};"><b>{ttl}</b>'
                     + (f' — {esc(it["note"])}' if it.get('note') else '') + '</div></div>')
        disc = (f'<div style="font-family:{SANS};font-size:11px;color:{MUTED};margin:4px 0 0 0;">Some links are affiliate links; the Blotter may earn a commission. Coverage is never sponsored.</div>'
                if any(it.get('affiliate') for it in sec.get('items', [])) else '')
        return label(lab) + rows + disc
    if t == 'presented_by':
        return (label(lab) + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:#f3eee2;border:1px dashed {RULE};padding:12px 16px;'
                f'font-family:{SERIF};font-size:15px;line-height:22px;color:{MUTED};">{sec.get("html") or PRESENTED_BY_DEFAULT}</td></tr></table>')
    if t == 'docket':
        rows = ''
        for it in sec.get('items', []):
            txt = f'<a href="{esc(it["url"])}" style="color:{TEXT};">{esc(it["text"])}</a>' if it.get('url') else esc(it.get('text', ''))
            rows += (f'<div style="font-family:{SERIF};font-size:16px;line-height:24px;color:{TEXT};margin:0 0 8px 0;">'
                     f'<span style="font-family:{SANS};font-size:12px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;color:{CRIMSON};">{esc(it.get("date", ""))}</span>&nbsp; {txt}</div>')
        return label(lab) + rows
    return label(lab) + body_html(sec.get('body_html', sec.get('html', '')))


# ---------------------------------------------------------------------------------------------- email --

def email_html(e, site=None, page_url=None):
    site = site or {}
    base = (site.get('url') or 'https://morningblotter.com').rstrip('/')
    emails = site.get('email', {})
    mailbag = emails.get('mailbag', 'mailbag@morningblotter.com')
    feed = (site.get('podcast') or {}).get('feed_url', 'https://feeds.transistor.fm/the-morning-blotter')
    ethics = site.get('ethics_line') or ('We report with care. Victims are named with respect, the accused are presumed innocent until conviction, and every headline '
                                          'links to its original source — details can evolve, so check the link before repeating them.')
    ep = e.get('episode') or {}
    pre = esc(e.get('preheader') or e.get('summary') or '')
    vol, no = e.get('vol', ''), e.get('no', '')
    mins = e.get('read_minutes') or read_minutes(e)
    mast_meta = f'VOL. {esc(vol)} • Nº {esc(no)} • {esc(date_long(e["date"]))} • A {"FOUR" if mins == 4 else mins}-MINUTE READ'

    listen = ''
    if ep.get('share_url'):
        listen = ('<div style="height:14px;line-height:14px;font-size:14px;">&nbsp;</div>'
                  + button(f'▶ LISTEN — {esc(mmss(ep.get("duration_s")))} WITH RAY &amp; CASEY', ep['share_url']))
    online = ''
    if page_url:
        online = (f'<div style="font-family:{SANS};font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{MUTED};margin:12px 0 0 0;">'
                  f'<a href="{esc(page_url)}" style="color:{MUTED};">Read online</a> · <a href="{base}/editions/" style="color:{MUTED};">Every edition</a></div>')

    sections = ''.join(section(e, s) for s in e.get('sections', []))
    intro = body_html(e.get('intro_html', ''))

    parts = [
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{esc(subject(e))}</title></head>',
        f'<body style="margin:0;padding:0;background:{PAPER};">',
        f'<div style="display:none;font-size:1px;color:{PAPER};line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{pre}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;</div>',
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAPER};"><tr><td align="center" style="padding:20px 10px;">',
        f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%;background:{CARD};border:1px solid {RULE};border-top:5px solid {CRIMSON};">',
        # masthead
        f'<tr><td align="center" style="padding:26px 28px 18px 28px;border-bottom:1px solid {RULE};">',
        f'<div style="font-family:{SANS};font-size:10px;letter-spacing:4px;text-transform:uppercase;color:{MUTED};">True crime, every morning</div>',
        f'<div style="font-family:{SERIF};font-size:16px;font-weight:bold;letter-spacing:2px;color:{INK};margin:6px 0 0 0;">THE MORNING</div>',
        f'<div style="font-family:{SERIF};font-size:38px;line-height:40px;font-weight:bold;letter-spacing:2px;color:{CRIMSON};">BLOTTER</div>',
        f'<div style="font-family:{SANS};font-size:10px;letter-spacing:4px;text-transform:uppercase;color:{MUTED};margin:4px 0 10px 0;">Reported with care</div>',
        f'<div style="font-family:{SANS};font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{INK};">{mast_meta}</div>',
        listen, online, '</td></tr>',
        # body
        '<tr><td style="padding:22px 28px 10px 28px;">',
        f'<div style="font-family:{SERIF};font-size:24px;line-height:30px;font-weight:bold;color:{INK};margin:0 0 12px 0;">{esc(e.get("headline", ""))}</div>',
        intro, sections,
        '</td></tr>',
        # footer
        f'<tr><td style="padding:18px 28px 22px 28px;border-top:1px solid {RULE};font-family:{SERIF};font-size:12px;line-height:18px;color:{MUTED};">',
        f'<div style="font-family:{SERIF};font-size:15px;font-weight:bold;letter-spacing:1px;color:{INK};">THE MORNING <span style="color:{CRIMSON};">BLOTTER</span></div>',
        f'<div style="font-family:{SANS};font-size:10px;letter-spacing:3px;text-transform:uppercase;color:{MUTED};margin:2px 0 10px 0;">Filed daily at 7:00 AM ET</div>',
        f'<p style="margin:0 0 8px 0;">{esc(ethics)}</p>',
        f'<p style="margin:0 0 8px 0;">Questions for Ray and Casey: <a href="mailto:{esc(mailbag)}" style="color:{CRIMSON};">{esc(mailbag)}</a> — first names only on air.</p>',
        f'<p style="margin:0 0 12px 0;"><a href="{feed}" style="color:{CRIMSON};">The podcast</a> · <a href="{base}/editions/" style="color:{CRIMSON};">Every edition</a> · <a href="{base}/cases/" style="color:{CRIMSON};">Cases we track</a></p>',
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:{CRIMSON};padding:9px 16px;"><a href="{{{{UNSUB_URL}}}}" style="color:{CARD};font-family:{SANS};font-size:11px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;text-decoration:none;">Unsubscribe</a></td></tr></table>',
        f'<p style="margin:12px 0 0 0;font-size:11px;line-height:16px;">© {dt.date.today().year} The Morning Blotter. Compiled with AI-assisted research; every item verified against the linked source before send. The podcast’s hosts are AI-voiced.</p>',
        '</td></tr></table></td></tr></table></body></html>',
    ]
    out = ''.join(parts)
    if len(out.encode('utf-8')) > 95_000:
        raise ValueError(f'email is {len(out.encode("utf-8")) // 1000} KB — Gmail clips at 102 KB; shorten the edition')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edition')
    ap.add_argument('--site', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'site.json'))
    ap.add_argument('--page-url', default=None)
    ap.add_argument('--out', default='edition.html')
    a = ap.parse_args()
    with open(a.edition, encoding='utf-8') as f:
        e = json.load(f)
    site = {}
    if os.path.exists(a.site):
        with open(a.site, encoding='utf-8') as f:
            site = json.load(f)
    html_out = email_html(e, site, a.page_url)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'{a.out}: {len(html_out.encode("utf-8")) // 1000} KB — subject: {subject(e)}')


if __name__ == '__main__':
    main()
