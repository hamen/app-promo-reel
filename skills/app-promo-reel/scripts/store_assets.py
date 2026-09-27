#!/usr/bin/env python3
"""Fetch store facts and screenshots for an app.

App Store: iTunes lookup (by --app-store-id or --bundle) in the --country storefront and the
--lang language -> metadata.json + screens/NN.png at full size. Lookup failure, zero results
or zero screenshots exit 2 (only when an App Store app was requested).
Google Play (--play <package>): best-effort. Title and description from the public page, and
the "Contains ads" / "In-app purchases" labels only on an exact string match for --lang.
On any parse failure it writes nothing for that field and says so. It never guesses.

Ratings, review counts and download counts are deliberately not saved: the video must not
show them (see references/copy-rules.md).

Usage: store_assets.py --out DIR [--app-store-id ID | --bundle ID] [--play PACKAGE]
                       [--country us] [--lang en]
"""
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
FULL_SIZE = "1290x2796bb.png"
_SIZE_SEGMENT = re.compile(r"/\d+x\d+bb\.(png|jpg|jpeg|webp)$")

# Exact Play Store label strings per language. Add a language only with strings copied
# from a real Play page in that language.
PLAY_LABELS = {
    "en": {"contains_ads": "Contains ads", "in_app_purchases": "In-app purchases"},
    "it": {"contains_ads": "Contiene annunci", "in_app_purchases": "Acquisti in-app"},
}


def log(msg):
    print(msg, file=sys.stderr)


def full_size_url(url):
    """Rewrite an Apple screenshot URL to the 1290x2796 PNG rendition.
    A URL without a trailing <w>x<h>bb.<ext> segment is returned unchanged."""
    if not _SIZE_SEGMENT.search(url):
        log(f"note: no size segment in {url}; using it as is")
        return url
    return _SIZE_SEGMENT.sub("/" + FULL_SIZE, url)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def lookup_url(app_store_id=None, bundle=None, country="us", lang="en"):
    q = {"country": country, "lang": lang, "entity": "software"}
    q["id" if app_store_id else "bundleId"] = app_store_id or bundle
    return "https://itunes.apple.com/lookup?" + urllib.parse.urlencode(q)


def parse_lookup(doc):
    """Keep only the facts a video may use. Returns None when there is no result."""
    if not doc.get("resultCount") or not doc.get("results"):
        return None
    r = doc["results"][0]
    return {
        "name": r.get("trackName"),
        "seller": r.get("sellerName"),
        "bundle_id": r.get("bundleId"),
        "description": r.get("description"),
        "release_notes": r.get("releaseNotes"),
        "version": r.get("version"),
        "price": r.get("formattedPrice"),
        "genres": r.get("genres"),
        "icon": r.get("artworkUrl512"),
        "screenshots": r.get("screenshotUrls") or [],
        "store_url": r.get("trackViewUrl"),
    }


def download_screenshot(url, dest, fetch_fn=fetch):
    """Download the full-size rendition; on a 404 fall back to the original URL."""
    big = full_size_url(url)
    try:
        data = fetch_fn(big)
    except urllib.error.HTTPError as e:
        if e.code != 404 or big == url:
            raise
        log(f"note: {big} is 404; using {url}")
        data = fetch_fn(url)
        dest = dest.with_suffix(Path(urllib.parse.urlparse(url).path).suffix or ".png")
    dest.write_bytes(data)
    return dest


def _meta(page, attr, name):
    m = re.search(rf'<meta[^>]+{attr}="{re.escape(name)}"[^>]+content="([^"]*)"', page)
    if not m:
        m = re.search(rf'<meta[^>]+content="([^"]*)"[^>]+{attr}="{re.escape(name)}"', page)
    return html.unescape(m.group(1)) if m else None


def strip_store_suffix(title):
    """og:title is "Name - Apps on Google Play" (localised); keep the app name only."""
    return re.sub(r"\s+[-\u2013\u2014]\s+[^-\u2013\u2014]*Google Play\s*$", "", title)


def parse_play(page, lang):
    """Facts from a Play Store page. Labels only on an exact match; unknown lang -> no labels."""
    out = {}
    for key, attr, name in (("title", "property", "og:title"), ("description", "name", "description")):
        value = _meta(page, attr, name)
        if value is None:
            log(f"note: Play {key} not found on the page (layout changed?); not written")
        else:
            out[key] = strip_store_suffix(value) if key == "title" else value
    labels = PLAY_LABELS.get(lang)
    if labels is None:
        log(f"note: no known Play label strings for lang {lang!r}; labels not checked")
        return out
    for key, text in labels.items():
        if re.search(r">\s*" + re.escape(text) + r"\s*<", page):
            out[key] = True
    return out


def main(argv=None, fetch_fn=fetch):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--app-store-id")
    ap.add_argument("--bundle")
    ap.add_argument("--play")
    ap.add_argument("--country", default="us", help="App Store storefront, e.g. it, us")
    ap.add_argument("--lang", default="en", help="copy language, e.g. it, en")
    a = ap.parse_args(argv)
    if not (a.app_store_id or a.bundle or a.play):
        ap.error("give --app-store-id, --bundle or --play")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # a failed run must not leave an earlier listing behind for the next step to use
    (out / "metadata.json").unlink(missing_ok=True)
    for old in (out / "screens").glob("[0-9][0-9].png"):
        old.unlink()
    meta = {"country": a.country, "lang": a.lang}

    if a.app_store_id or a.bundle:
        url = lookup_url(a.app_store_id, a.bundle, a.country, a.lang)
        try:
            doc = json.loads(fetch_fn(url))
        except (urllib.error.URLError, ValueError) as e:
            log(f"error: App Store lookup failed ({e}); ask the user for screenshots or build from the website")
            return 2
        app = parse_lookup(doc)
        if app is None:
            log(f"error: App Store lookup returned no app for {a.app_store_id or a.bundle} in {a.country}")
            return 2
        if not app["screenshots"]:
            log("error: the App Store listing has no iPhone screenshots; ask the user for screenshots")
            return 2
        shots = out / "screens"
        shots.mkdir(exist_ok=True)
        saved = []
        for i, s in enumerate(app["screenshots"], 1):
            try:
                saved.append(str(download_screenshot(s, shots / f"{i:02d}.png", fetch_fn)))
            except (urllib.error.URLError, OSError, ValueError) as e:
                log(f"error: screenshot download failed ({s}: {e}); ask the user for screenshots or re-run")
                return 2
        app["saved_screenshots"] = saved
        meta["app_store"] = app

    if a.play:
        q = urllib.parse.urlencode({"id": a.play, "hl": a.lang, "gl": a.country.upper()})
        url = f"https://play.google.com/store/apps/details?{q}"
        try:
            meta["google_play"] = {"package": a.play, **parse_play(fetch_fn(url).decode("utf-8", "replace"), a.lang)}
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"note: Play page fetch failed ({e}); no Play facts written")

    (out / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
