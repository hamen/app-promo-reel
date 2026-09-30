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


@pytest.mark.parametrize("edit", [
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiLabel": ""'),
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiLabel": "   "'),
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiText": "AI-generated"'),
    # characters that draw nothing: escaped or literal zero-width, BOM, word joiner, escaped space
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiLabel": "\\u200b"'),
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiLabel": "\u200b\u2060\ufeff"'),
    lambda s: s.replace('"aiLabel": "AI-generated"', '"aiLabel": "\\u0020"'),
])
def test_ai_label_cannot_be_removed(tmp_path, edit):
    def change(p):
        t = p / "src.html.tmpl"
        new = edit(t.read_text())
        assert new != t.read_text()
        t.write_text(new)
    _, err = build(tmp_path, edit=change, expect=2)
    assert "AI-generated label" in err


def test_build_puts_the_label_guard_last_in_the_page(tmp_path):
    _, html = build(tmp_path)
    guard = html[html.index("<script data-ai-label-guard>"):]
    assert guard.index("</script>") < guard.index("</body>") and "<script" not in guard[8:guard.index("</body>")]
    for check in ('[...text.replace(/[\\p{Z}\\p{C}\\p{M}\\u115F\\u1160\\u3164\\uFFA0\\u2800]/gu, "")].length', 'el.id = "ai-label-',
                  'el.style.setProperty(k, v, "important")', '"z-index": "2147483647"', 'visibility: "visible"',
                  "root.appendChild(el)", 'cs.display === "none"', 'cs.clipPath !== "none"',
                  "opacity *= parseFloat(cs.opacity)", 'cs.maskImage !== "none"', 'cs.filter !== "none" || cs.mixBlendMode !== "normal"', "opacity < 0.5", "box.right > frame.right",
                  # template CSS must not reach the label or its words (text-indent, text fill, ::first-line ...)
                  'all: "initial", display: "block"', 'attachShadow({ mode: "closed" })',
                  ":host::before, :host::after { content: none !important",
                  "alpha(own.webkitTextFillColor) < 0.5", "ink.width < Math.max(12, 6 * visible)"):
        assert check in guard, check


def test_the_template_does_not_own_the_label(tmp_path):
    # a template element or CSS rule for the label could hide it: the page script makes it
    _, html = build(tmp_path)
    body = html[:html.index("<script data-ai-label-guard>")]
    assert 'id="ai-label' not in body and "#ai-label" not in body


def test_template_cannot_disable_the_guard(tmp_path):
    # whatever the template does to its own scripts, the guard is added by build.py after them
    def change(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("</body>", "<script>/* no guard here */</script>\n</body>"))
    _, html = build(tmp_path, edit=change)
    assert html.rindex("<script data-ai-label-guard>") > html.rindex("/* no guard here */")


def test_page_without_body_end_fails_the_build(tmp_path):
    def change(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("</body>", ""))
    _, err = build(tmp_path, edit=change, expect=2)
    assert "</body>" in err


def test_label_id_changes_with_every_build(tmp_path):
    import re as _re
    ids = set()
    for i in range(2):
        _, html = build(tmp_path / str(i))
        assert "Math.random" not in html and "__AI_LABEL_ID__" not in html
        ids.add(_re.search(r'el\.id = "(ai-label-[0-9a-f]{12})"', html).group(1))
    assert len(ids) == 2


def test_hook_is_static_from_frame_zero(tmp_path):
    """Average watch time can be ~1 s and frame 0 is the cover: no word-by-word hook build."""
    _, html = build(tmp_path)
    # the four hook words exist, inside #hook-words, which is not inside the #hero card (hero starts at opacity 0)
    hook = html.split('id="hook-words"', 1)[1].split('id="hero"', 1)[0]
    for i in range(4):
        assert f'id="w-{i}"' in hook
    # no CSS rule hides the words
    css = html.split("<style", 1)[1].split("</style>", 1)[0]
    kin = re.findall(r"\.kin[^{]*\{([^}]*)\}", css)
    assert kin and not any(re.search(r"opacity\s*:\s*0\s*;|visibility\s*:\s*hidden|display\s*:\s*none", b) for b in kin)
    s1 = html.split("// ===== S1 hook", 1)[1].split("// =====", 1)[0]
    # no tween starts the hook words hidden or builds them one by one
    assert not re.search(r'(fromTo|from|set)\(\s*"#(hook-words|w-\d)"', s1)
    assert '"#w-0"' not in s1
    # both downbeats keep punch, shake and flash
    for beat in ("D(0, 0)", "D(1, 0)"):
        assert f'punch("#hook-words", {beat}' in s1
        assert f'shake("#s1-cam", {beat}' in s1
        assert f"flash({beat}" in s1
