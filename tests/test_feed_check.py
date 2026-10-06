"""The check command build.py prints, run for real: HyperFrames 0.8.78 in a headless browser (about
15 s a run). It proves the bottom band of the feed safe box and the AI label's safe-box guard work on
a rendered page, not only that the command is spelled right.

Opt-in: bin/ci runs with no network and no browser, so these run only with APR_BROWSER_TESTS=1
(README, Development). The guard's bounds are tested without a browser in test_build.py."""
import json
import os
import shlex
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from conftest import run_script
from test_template import build

pytestmark = [
    pytest.mark.skipif(os.environ.get("APR_BROWSER_TESTS") != "1", reason="browser tests: set APR_BROWSER_TESTS=1"),
    pytest.mark.skipif(shutil.which("npx") is None, reason="needs npx (HyperFrames)"),
]


def check(tmp_path, fmt, edit=None):
    p, _ = build(tmp_path, fmt=fmt, edit=edit)
    # a silent bed: the lint step fails a page whose <audio> file is missing
    sf.write(p / "assets" / "audio" / "bgm.wav", np.zeros((48000 * 30, 2), np.float32), 48000)
    last = run_script("build.py", p).stdout.rstrip("\n").split("\n")[-1]
    assert last.startswith("check: ")
    cmd = shlex.split(last[len("check: "):])
    r = subprocess.run(cmd + ["--json"], capture_output=True, text=True, timeout=300)
    findings = []

    def walk(x):
        if isinstance(x, dict):
            if "code" in x and "severity" in x:
                findings.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    try:
        walk(json.loads(r.stdout))
    except json.JSONDecodeError:
        pass
    return cmd, r, findings


def errors(findings):
    return [(f["code"], f.get("selector")) for f in findings if f["severity"] == "error"]


@pytest.mark.parametrize("fmt", ["9:16", "4:5"])
def test_the_shipped_template_passes_its_own_check(tmp_path, fmt):
    cmd, r, findings = check(tmp_path, fmt)
    assert "--caption-zone" in cmd
    assert r.returncode == 0 and errors(findings) == [], (r.stdout[-2000:], r.stderr[-2000:])


def test_a_caption_moved_into_the_bottom_band_fails_the_check(tmp_path):
    def low_caption(p):
        t = p / "src.html.tmpl"
        s = t.read_text()
        assert s.count("top: 280px;\n        left: 64px;") == 1
        t.write_text(s.replace("top: 280px;\n        left: 64px;", "top: 1560px;\n        left: 64px;"))
    _, r, findings = check(tmp_path, "9:16", low_caption)
    assert r.returncode != 0
    assert ("caption_zone_collision", "#cap-a") in errors(findings)


def test_a_label_too_long_for_the_safe_box_fails_the_check(tmp_path):
    # 81 characters: past x 960 with any sans-serif font (the exact edges are tested in test_build.py)
    def long_label(p):
        t = p / "src.html.tmpl"
        s = t.read_text()
        assert s.count('"aiLabel": "AI-generated"') == 1
        t.write_text(s.replace('"aiLabel": "AI-generated"',
                               '"aiLabel": "AI-generated video, made with an AI tool. Read the notes under the video for more"'))
    _, r, _ = check(tmp_path, "9:16", long_label)
    assert r.returncode != 0
    assert "AI-generated label is not fully inside the feed safe box" in r.stdout + r.stderr
