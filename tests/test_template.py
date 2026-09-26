"""Template smoke: scaffold -> build with a fixture grid, no browser."""
import json
import re

import pytest

from conftest import run_script, steady_grid


def build(tmp_path, stores="app_store,google_play", edit=None):
    out = tmp_path / "out"
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", out, "--force", "--stores", stores)
    assert r.returncode == 0, r.stderr
    p = out / "demo-a"
    (p / "beats.json").write_text(json.dumps(steady_grid(first=0.7, iv=0.5, n=64, phase=1)))
    if edit:
        edit(p)
    r = run_script("build.py", p)
    assert r.returncode == 0, r.stderr
    return p, (p / "index.html").read_text()


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
