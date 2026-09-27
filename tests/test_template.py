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


def grid_from_beat_grid(bpm, first_downbeat):
    """A grid built with beat_grid's own extend(), as beat_grid.py writes it."""
    import beat_grid as bg
    iv = 60 / bpm
    beats = bg.extend(np.arange(first_downbeat, 20, iv), 30.0, beats_past_end=4 * 4)
    phase = int(np.argmin(np.abs(beats - first_downbeat)))
    return {"beats": [round(float(b), 4) for b in beats], "downbeat_phase": phase}, beats, phase


def test_slowest_buildable_tempo_gives_the_end_card_time_to_read(tmp_path):
    # 116 bpm, first downbeat 0.3 s: the badges and URL enter on D(13, 3) = 28.75 s (1.25 s left)
    grid, beats, phase = grid_from_beat_grid(116, 0.3)
    _, html = build(tmp_path, grid=grid)
    assert "END(" not in html and "{{" not in html  # no hidden clamp, the gate token is gone
    assert re.search(r'tl\.fromTo\("#url".*\}, D\(13, 3\)\);', html)
    assert len(beats) > phase + 14 * 4 + 1  # the icon punch on D(14) is on the grid


@pytest.mark.parametrize("bpm,first", [(110, 1.0), (98, 0.3), (80, 0.5)])
def test_slow_tempo_fails_the_build_with_the_re_map_message(tmp_path, bpm, first):
    grid, _, _ = grid_from_beat_grid(bpm, first)
    _, err = build(tmp_path, grid=grid, expect=2)
    assert "D(13, 3)" in err and "1.1s before" in err and "re-map" in err
