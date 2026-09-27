import io
import json
import urllib.error
from pathlib import Path

import store_assets as sa
from conftest import FIXTURES


def test_full_size_url_png_and_jpg():
    assert sa.full_size_url("https://x/thumb/a/1.png/392x696bb.png") == "https://x/thumb/a/1.png/1290x2796bb.png"
    assert sa.full_size_url("https://x/thumb/a/1.jpg/300x600bb.jpg") == "https://x/thumb/a/1.jpg/1290x2796bb.png"


def test_full_size_url_without_size_segment_is_unchanged():
    u = "https://x/thumb/a/2.jpg/300x0w.jpg"
    assert sa.full_size_url(u) == u


def test_parse_lookup_drops_ratings():
    app = sa.parse_lookup(json.loads((FIXTURES / "lookup.json").read_text()))
    assert app["name"] == "Example App" and len(app["screenshots"]) == 2
    assert "rating" not in json.dumps(app).lower()
    assert sa.parse_lookup({"resultCount": 0, "results": []}) is None


def test_download_falls_back_to_original_on_404(tmp_path):
    calls = []

    def fake(url):
        calls.append(url)
        if "1290x2796" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO())
        return b"img"

    out = sa.download_screenshot("https://x/a/1.jpg/392x696bb.jpg", tmp_path / "01.png", fake)
    assert calls == ["https://x/a/1.jpg/1290x2796bb.png", "https://x/a/1.jpg/392x696bb.jpg"]
    assert out.read_bytes() == b"img" and out.suffix == ".jpg"


def test_parse_play_exact_labels():
    got = sa.parse_play((FIXTURES / "play-en.html").read_text(), "en")
    assert got["contains_ads"] and got["in_app_purchases"] and got["description"] == "Does one thing & well."
    assert got["title"] == "Example App"  # og:title "Example App - Apps on Google Play"
    noads = sa.parse_play((FIXTURES / "play-noads.html").read_text(), "en")
    assert "contains_ads" not in noads and noads["in_app_purchases"]
    assert sa.strip_store_suffix("Example App - Apps on Google Play") == "Example App"
    assert sa.strip_store_suffix("Dispensa - Lista spesa - App su Google Play") == "Dispensa - Lista spesa"
    assert sa.strip_store_suffix("Example App") == "Example App"
    changed = sa.parse_play((FIXTURES / "play-changed.html").read_text(), "en")
    assert changed == {}  # no label, no title, no description: nothing guessed, nothing null
    assert "contains_ads" not in sa.parse_play((FIXTURES / "play-en.html").read_text(), "xx")


def fake_fetch(lookup_fixture, play_fixture="play-en.html"):
    def f(url):
        if "itunes.apple.com" in url:
            return (FIXTURES / lookup_fixture).read_bytes()
        if "play.google.com" in url:
            return (FIXTURES / play_fixture).read_bytes()
        return b"png"
    return f


def test_zero_screenshots_exits_2(tmp_path):
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1"], fake_fetch("lookup-noshots.json")) == 2


def test_no_result_exits_2(tmp_path):
    def f(url):
        return b'{"resultCount": 0, "results": []}'
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1"], f) == 2


def test_play_only_needs_no_screenshots(tmp_path):
    assert sa.main(["--out", str(tmp_path), "--play", "com.example", "--lang", "en"], fake_fetch("lookup.json")) == 0
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["google_play"]["contains_ads"] and "app_store" not in meta


def test_country_and_lang_are_separate(tmp_path):
    urls = []

    def f(url):
        urls.append(url)
        return fake_fetch("lookup.json")(url)
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1", "--country", "de", "--lang", "en"], f) == 0
    assert "country=de" in urls[0] and "lang=en" in urls[0]
    assert len(list(Path(tmp_path, "screens").iterdir())) == 2


def test_screenshot_download_error_exits_2(tmp_path):
    def f(url):
        if "itunes.apple.com" in url:
            return (FIXTURES / "lookup.json").read_bytes()
        raise urllib.error.URLError("network down")
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1"], f) == 2


def test_play_package_is_url_encoded(tmp_path):
    urls = []

    def f(url):
        urls.append(url)
        return (FIXTURES / "play-en.html").read_bytes()
    sa.main(["--out", str(tmp_path), "--play", "com.x&hl=zz"], f)
    assert "id=com.x%26hl%3Dzz" in urls[0] and urls[0].count("hl=") == 1


def test_a_failed_run_leaves_no_old_listing(tmp_path):
    (tmp_path / "metadata.json").write_text('{"old": true}')
    (tmp_path / "screens").mkdir()
    (tmp_path / "screens" / "07.png").write_bytes(b"old")

    def down(url):
        raise urllib.error.URLError("network down")
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1"], down) == 2
    assert not (tmp_path / "metadata.json").exists() and not (tmp_path / "screens" / "07.png").exists()


def test_old_jpg_screens_are_cleared_and_a_partial_set_is_removed(tmp_path):
    screens = tmp_path / "screens"
    screens.mkdir()
    (screens / "03.jpg").write_bytes(b"old fallback")
    calls = []

    def f(url):
        if "itunes.apple.com" in url:
            return (FIXTURES / "lookup.json").read_bytes()
        calls.append(url)
        if len(calls) > 1:  # the first screenshot downloads, the second fails
            raise urllib.error.URLError("network down")
        return b"png bytes"
    assert sa.main(["--out", str(tmp_path), "--app-store-id", "1"], f) == 2
    assert list(screens.iterdir()) == []
