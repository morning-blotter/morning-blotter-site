# The Morning Blotter — site

The public site for [morningblotter.com](https://morningblotter.com): the blotter (home), the searchable archive of every edition, one page per edition in the email's look with the episode player and transcript, the cases we track, the podcast, and the subscribe form. Static, built by `build.py`, hosted on GitHub Pages, deployed by the workflow in `.github/workflows/pages.yml` on every push to `main`.

## How an edition gets onto the site

The daily run (the Claude task that writes and sends the brief) does not touch HTML. After Jeremy approves the edition it:

1. publishes the episode to Transistor (so the share URL exists),
2. sends the email — built by `emailer.py` from the edition JSON, with the **Listen** button and the **Read online** link,
3. commits `data/editions/YYYY-MM-DD.json` (and any updated `data/cases/*.json`) to this repo through the GitHub API.

The push triggers the workflow: `python build.py` regenerates every page (home, archive, edition pages, case pages, podcast, feeds, sitemap, share cards) and deploys them. Nothing else has to happen. A case page updates the same way — edit its JSON and push.

## Local build

```
pip install pillow          # optional: share-card images
python3 build.py --drafts   # include editions marked "draft": true (noindex, banner)
cd _site && python3 -m http.server 8000
```

## Edition JSON (`data/editions/YYYY-MM-DD.json`)

The one file both the email and the site are built from.

```jsonc
{
  "kind": "daily",                 // daily | sunday
  "vol": 1, "no": 1, "date": "2026-09-26",
  "headline": "…",                 // the top case in ≤ 12 words: page title, home hero, ledger row, share card
  "slug": "horsch-house-walls",    // optional; derived from the headline if absent. Never change after publishing.
  "subject": "The Morning Blotter — Nº 1 — Sat., Sept. 26: …",   // email subject (spec §7); derived if absent
  "summary": "…",                  // ≤ 200 chars: meta description, ledger row, feed
  "preheader": "…",                // hidden email preheader
  "intro_html": "<p>…</p>",
  "sections": [
    {"type": "top_case", "chip": "CHARGED", "headline": "…", "url": "…", "source": "AP", "jurisdiction": "Fulton County, GA",
     "state": "GA", "date": "2026-09-25", "body_html": "<p>…</p>", "case_notes": "…", "cases": ["case-slug"]},
    {"type": "blotter", "items": [{"chip": "…", "headline": "…", "url": "…", "source": "…", "jurisdiction": "…", "state": "..", "date": "…", "body_html": "…", "cases": []}]},
    {"type": "case_file", "no": 1, "title": "…", "body_html": "…", "pull_quote": "…", "cases": ["…"], "sources": [{"title": "…", "url": "…"}]},
    {"type": "microscope", "chip": "FORENSICS", "headline": "…", "url": "…", "source": "…", "date": "…", "body_html": "…"},   // optional
    {"type": "watch_list", "items": [{"title": "…", "kind": "DOC", "platform": "Netflix", "date": "Oct 3", "url": "…", "note": "…", "affiliate": false}]},  // optional
    {"type": "presented_by", "html": "…"},   // omit html for the beta self-copy
    {"type": "docket", "items": [{"date": "Sept. 27", "text": "…", "url": "…"}]}
  ],
  "episode": {"transistor_id": 0, "title": "…", "share_url": "https://share.transistor.fm/s/…", "media_url": "…mp3",
              "duration_s": 730, "notes_html": "…", "transcript": "[COLD OPEN]\nCASEY: …\nRAY: …"},   // null when no audio shipped
  "cases": ["case-slug"], "states": ["GA"],
  "sources": [{"title": "…", "outlet": "…", "date": "2026-09-25", "url": "…"}],
  "claims_reconciled": true,
  "draft": false
}
```

Section types render in order. `cases` slugs must match a file in `data/cases/`. `state` is a two-letter code (plus `US` for federal, `INTL`). Transcript lines are `SPEAKER: text`, segment markers `[NAME]`.

## Case JSON (`data/cases/<slug>.json`)

`name`, `short` (one line), `status`, `jurisdiction`, `state`, `updated` (YYYY-MM-DD), `summary_html` ("the record so far"), `people` [{name, text}], `timeline` [{date, text, source_title, source_url}], `what_next` [{date, text}], `tip_line`, `sources` [{title, outlet, date, url}]. Every edition that lists the slug in `cases` appears on the case page automatically.

## Podcast-only episodes (`data/episodes/*.json`)

For episodes with no email edition (Episode 0): `id`, `title`, `date`, `summary`, `notes_html`, `transistor_id`, `share_url`, `media_url`, `duration_s`, `transcript`.

## Site config (`data/site.json`)

Name, taglines, domain, emails, podcast directories, `subscribe_endpoint` (the Apps Script `/exec` URL — the form posts there; empty = mailto fallback), `search_console_tag` (Google's verification token, if the HTML-tag method is used).

## SEO layer (built in)

Headline-first `<title>`s, meta descriptions, canonical URLs, Open Graph and Twitter cards with a generated 1200×630 share card per edition, JSON-LD (`NewsMediaOrganization`, `WebSite` with `SearchAction`, `NewsArticle` + `PodcastEpisode` per edition, `PodcastSeries`, `Article` per case, breadcrumbs), `sitemap.xml`, `robots.txt`, `feed.xml` (site RSS with the episode enclosure), semantic HTML, every transcript on the page, internal links between editions and cases. Drafts are `noindex` and excluded from the sitemap and feed.
