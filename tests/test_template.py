"""Template smoke: scaffold -> build with a fixture grid, no browser."""
import json
import re

import numpy as np
import pytest

from conftest import TEMPLATE, run_script, steady_grid


def build(tmp_path, stores="app_store,google_play", edit=None, grid=None, expect=0, fmt="9:16"):
    out = tmp_path / "out"
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", out, "--force", "--stores", stores,
                   "--format", fmt)
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
    # the four hook words exist, inside #hook-words, and #hook-words is NOT a descendant of #hero
    # (#hero starts at opacity 0, so a nested hook would be invisible at frame 0)
    from html.parser import HTMLParser

    class Tree(HTMLParser):
        VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

        def __init__(self):
            super().__init__()
            self.stack, self.in_hook, self.hook_in_hero = [], set(), False

        def handle_starttag(self, tag, attrs):
            if tag in self.VOID:
                return
            a = dict(attrs)
            if a.get("id") == "hook-words":
                self.hook_in_hero = any(i == "hero" for _, i in self.stack)
            if any(i == "hook-words" for _, i in self.stack) and a.get("id"):
                self.in_hook.add(a["id"])
            self.stack.append((tag, a.get("id")))

        def handle_endtag(self, tag):
            while self.stack and self.stack.pop()[0] != tag:
                pass

    tree = Tree()
    tree.feed(html)
    assert {f"w-{i}" for i in range(4)} <= tree.in_hook
    assert not tree.hook_in_hero
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


@pytest.mark.parametrize("fmt, w, h, scale", [("9:16", 1080, 1920, "1"), ("4:5", 1080, 1350, "0.703125")])
def test_the_page_takes_its_size_from_the_format(tmp_path, fmt, w, h, scale):
    _, html = build(tmp_path, fmt=fmt)
    assert f'<meta name="viewport" content="width={w}, height={h}" />' in html
    assert re.search(rf"html,\s*body \{{\s*width: {w}px;\s*height: {h}px;", html)
    assert re.search(rf'id="root"[^>]*data-width="{w}" data-height="{h}" data-format="{fmt}"', html)
    assert f"const FRAME_SCALE = {scale};" in html


def test_the_template_fixes_no_frame_height():
    # the 9:16 height lives in common.py and reaches the page only through the size tokens
    assert "1920" not in (TEMPLATE / "src.html.tmpl").read_text()


def test_the_4x5_layer_keeps_the_tap_point_on_the_phone(tmp_path):
    # the tap point sits outside the phone's wrapper, so it is mapped by hand: it must follow the
    # wrapper's transform, or the ring lands off the button
    _, html = build(tmp_path, fmt="4:5")
    css = html.split("<style", 1)[1].split("</style>", 1)[0]
    fit = re.search(r'#root\[data-format="4:5"\] \.phone-fit \{([^}]*)\}', css).group(1)
    dy, k = map(float, re.search(r"translateY\((-?[\d.]+)px\) scale\(([\d.]+)\)", fit).groups())
    ox, oy = map(float, re.search(r"transform-origin: ([\d.]+)px ([\d.]+)px", fit).group(1, 2))
    x9, y9 = (float(re.search(rf"--tap-{a}: ([\d.]+)px", css).group(1)) for a in "xy")
    y45 = float(re.search(r'#root\[data-format="4:5"\] \{[^}]*--tap-y: ([\d.]+)px', css).group(1))
    assert "--tap-x" not in css.split('data-format="4:5"', 1)[1]  # x is on the transform's axis
    assert x9 == ox and abs(oy + (y9 - oy) * k + dy - y45) <= 0.5
    # a transformed wrapper breaks the perspective of .scene: it must carry its own
    assert re.search(r"perspective: \d+px", fit)
    # in 9:16 the wrapper has no box, so the 9:16 page renders as before it existed
    assert re.search(r"\n      \.phone-fit \{\s*display: contents;\s*\}", css)


# --- the motion language in the shipped templates ---------------------------------------------

@pytest.mark.parametrize("fmt", ["9:16", "4:5", "16:9"])
def test_the_shipped_templates_pass_the_seekability_check(tmp_path, fmt):
    build(tmp_path, fmt=fmt)


@pytest.mark.parametrize("fmt, has_motion", [("9:16", True), ("4:5", True), ("16:9", False)])
def test_new_project_copies_motion_js_for_the_formats_that_use_it(tmp_path, fmt, has_motion):
    p, html = build(tmp_path, fmt=fmt)
    assert (p / "motion.js").is_file() == has_motion
    assert ("const MOTION" in html) == has_motion


def test_the_9x16_template_uses_the_motion_classes_and_no_back_ease(tmp_path):
    src = (TEMPLATE / "src.html.tmpl").read_text()
    bad = [ln.strip() for ln in src.splitlines() if "back." in ln and "motion-exception:" not in ln]
    assert bad == []
    assert src.count("{{MOTION}}") == 1
    assert len(re.findall(r"ease: MOTION\.(?:icon|panel|headline|micro)\.ease", src)) == 8


SITE_CLASS = {"const pop = ": "icon", 'tl.fromTo("#hero"': "panel", 'tl.fromTo("#phone"': "panel",
              'tl.fromTo("#cap-a"': "headline", 'tl.fromTo("#cap-b"': "headline",
              'tl.fromTo("#val-sub"': "headline", 'tl.fromTo("#tagline"': "headline",
              'tl.fromTo("#cta"': "icon"}


@pytest.mark.parametrize("site, cls", sorted(SITE_CLASS.items()))
def test_each_converted_entrance_uses_its_own_motion_class(site, cls):
    lines = [ln for ln in (TEMPLATE / "src.html.tmpl").read_text().splitlines() if site in ln]
    assert len(lines) == 1
    assert re.findall(r"ease: (MOTION\.\w+\.ease)", lines[0]) == [f"MOTION.{cls}.ease"]


def test_a_random_value_added_to_the_template_fails_the_build(tmp_path):
    def edit(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("const tl = gsap.timeline", "const jitter = Math.random();\n      const tl = gsap.timeline", 1))
    _, err = build(tmp_path, edit=edit, expect=2)
    assert "Math.random" in err and "const jitter = Math.random();" in err


def test_a_project_without_motion_js_fails_when_the_template_has_the_token(tmp_path):
    _, err = build(tmp_path, edit=lambda p: (p / "motion.js").unlink(), expect=2)
    assert "no motion.js" in err
