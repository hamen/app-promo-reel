"""Template smoke: scaffold -> build with a fixture grid, no browser."""
import json
import re

import numpy as np
import pytest

from conftest import run_script, steady_grid


def build(tmp_path, stores="app_store,google_play", edit=None, grid=None, expect=0):
    out = tmp_path / "out"
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", out, "--force", "--stores", stores)
    assert r.returncode == 0, r.stderr
    p = out / "demo-a"
    (p / "beats.json").write_text(json.dumps(grid or steady_grid(first=0.7, iv=0.5, n=64, phase=1)))
    if edit:
        edit(p)
    r = run_script("build.py", p)
    assert r.returncode == expect, r.stderr
    return (p, (p / "index.html").read_text()) if expect == 0 else (p, r.stderr)


def config_of(html):
    m = re.search(r"/\*CONFIG\*/(.*?)/\*END CONFIG\*/", html, re.S)
    assert m, "CONFIG block missing"
    return json.loads(m.group(1))


def resolve(cfg, path):
    for k in path.split("."):
        cfg = cfg[int(k)] if isinstance(cfg, list) else cfg[k]
    return cfg


def test_template_builds_clean(tmp_path):
    p, html = build(tmp_path)
    assert "{{" not in html and "}}" not in html
    assert "@font-face" in html
    root = re.search(r'id="root"[^>]*data-duration="([\d.]+)"', html)
    assert float(root.group(1)) == json.loads((p / "project.json").read_text())["duration"]
    bgm = re.search(r'id="bgm"[^>]*data-duration="([\d.]+)"', html)
    assert float(bgm.group(1)) == 30
    assert json.loads((p / "cues.realized.json").read_text()) == []  # no SFX_DIR


def test_every_binding_resolves_in_config(tmp_path):
    _, html = build(tmp_path)
    cfg = config_of(html)
    paths = re.findall(r'data-cfg="([^"]+)"', html)
    assert len(paths) > 40
    for path in paths:
        assert isinstance(resolve(cfg, path), str), path


def test_app_text_lives_only_in_config(tmp_path):
    def rename(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace('"name": "App Name"', '"name": "Zebra Notes"'))
    _, html = build(tmp_path, edit=rename)
    cfg = config_of(html)
    assert cfg["end"]["name"] == "Zebra Notes"
    body = re.sub(r"/\*CONFIG\*/.*?/\*END CONFIG\*/", "", html, flags=re.S)
    for s in ["Zebra Notes", "App Name", "Your hook", "Benefit one", "example.com"]:
        assert s not in body, s
    assert re.search(r'id="wordmark" data-cfg="end.name"', html)


@pytest.mark.parametrize("stores", ["google_play", "app_store", "app_store,google_play"])
def test_stores_come_from_project(tmp_path, stores):
    _, html = build(tmp_path, stores=stores)
    assert config_of(html)["stores"] == stores.split(",")


def test_slow_tempo_still_builds_with_end_card_inside_the_video(tmp_path):
    # 110 bpm, first downbeat at 1.0 s: bar 14 starts at 31.5 s, after the 30 s video
    grid = steady_grid(first=1.0 - 4 * 0.5455, iv=0.5455, n=70, phase=4)
    p, html = build(tmp_path, grid=grid)
    starts = [float(x) for x in re.findall(r'<section[^>]*data-start="([\d.]+)"', html)]
    assert max(starts) < 30
    assert "const END = (t) => Math.min(t, DURATION - 0.6);" in html
    assert re.search(r"END\(D\(14, 0\) - 0\.1\)\)", html)


def test_scene_past_the_end_fails_the_build(tmp_path):
    grid = steady_grid(first=0.5, iv=0.75, n=60, phase=0)  # 80 bpm: bar 12 starts at 36.5 s
    _, err = build(tmp_path, grid=grid, expect=2)
    assert "scenes outside the 30s video" in err and "s6" in err


def grid_98bpm(s6_start):
    """A 98 bpm grid from beat_grid's own extend(), with scene s6 (D(12) - 0.3) at `s6_start`."""
    import beat_grid as bg
    iv = 60 / 98
    first_downbeat = s6_start + 0.3 - 12 * 4 * iv
    beats = bg.extend(np.arange(first_downbeat, 20, iv), 30.0, beats_past_end=4 * 4)
    phase = int(np.argmin(np.abs(beats - first_downbeat)))
    return {"beats": [round(float(b), 4) for b in beats], "downbeat_phase": phase}, beats, phase


def test_slowest_buildable_tempo_grid_covers_the_end_card(tmp_path):
    # s6 at 28.0 s leaves the end card 2 s; it addresses up to D(14) (~33.2 s), after the video
    grid, beats, phase = grid_98bpm(28.0)
    p, html = build(tmp_path, grid=grid)
    assert max(float(x) for x in re.findall(r'<section[^>]*data-start="([\d.]+)"', html)) <= 28.0 + 1e-3
    assert len(beats) > phase + 14 * 4 + 1  # D(14) and the beat after it exist


def test_end_card_without_time_to_read_fails_the_build(tmp_path):
    grid, _, _ = grid_98bpm(29.95)  # the end card would be on screen for 0.05 s
    _, err = build(tmp_path, grid=grid, expect=2)
    assert "less than 2s before its end" in err and "s6" in err and "re-map" in err
