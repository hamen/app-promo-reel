"""read_check.py run for real: its pass in HyperFrames 0.8.78's headless browser (about 10 s a run). It
proves what the pass calls readable, on a page with one caption per case, and that the stock template
reports every caption with its word count.

Opt-in: bin/ci runs with no network and no browser, so these run only with APR_BROWSER_TESTS=1
(README, Development). The rule and the parsing are tested without a browser in test_read_check.py."""
import json
import os
import re
import shutil

import numpy as np
import pytest
import soundfile as sf

import read_check as rc
from common import load_project
from conftest import TEMPLATE, run_script, write_project
from test_template import build

pytestmark = pytest.mark.skipif(os.environ.get("APR_BROWSER_TESTS") != "1", reason="browser tests: set APR_BROWSER_TESTS=1")
FPS = 30
GSAP = re.search(r'<script src="([^"]*gsap[^"]*)"></script>', (TEMPLATE / "src.html.tmpl").read_text()).group(1)

# A scene of 6 s, one from 4 s to 6 s, and one of 6 s that fades out as a whole at 3 s. Each caption is one case; the timeline sets states between frame times (0.49 is
# before frame 15, 0.5 s), so a frame never lands on a change.
CASES = f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><script src="{GSAP}"></script>
<style>
  body {{ margin: 0; }}
  #root {{ position: relative; width: 1080px; height: 1920px; overflow: hidden; background: #123; }}
  .scene {{ position: absolute; inset: 0; }}
  .t {{ position: absolute; left: 100px; font: 64px sans-serif; color: #fff; white-space: nowrap; }}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="6" data-width="1080" data-height="1920">
<section id="s1" class="clip scene" data-start="0" data-duration="6" data-track-index="1">
  <div class="t" id="long" data-read style="top: 100px; opacity: 0">Held for three seconds</div>
  <div class="t" id="short" data-read style="top: 250px; opacity: 0">Half second</div>
  <div class="t" id="faded" data-read style="top: 400px; opacity: 0.5">Faded words</div>
  <div class="t" id="blurred" data-read style="top: 550px; filter: blur(10px)">Blurred words</div>
  <div class="t" id="clipped" data-read style="top: 700px; clip-path: inset(0 100% 0 0)">Clipped words</div>
  <div class="t" id="reveal" data-read style="top: 850px">Revealed words</div>
  <div class="t" id="hidden" data-read style="top: 1000px; visibility: hidden">Hidden words</div>
  <div style="position: absolute; top: 1150px; left: 100px; width: 300px; height: 90px; overflow: hidden">
    <div class="t" id="cut" data-read style="left: 400px">Cut words</div></div>
  <div id="wide" data-read style="position: absolute; top: 1300px; left: 0; width: 1080px; text-align: center;
    font: 64px sans-serif; color: #fff">Punched line</div>
  <div class="t" id="staged" data-read style="top: 1450px"><span>One</span> <span id="w2" style="opacity: 0">two</span></div>
  <div class="t" id="glued" data-read style="top: 1600px"><span>Glued</span><span>words</span></div>
  <div class="t" id="away" data-read style="top: 1750px; left: 1200px">Away words</div>
  <div class="t" id="share" data-read style="top: 1820px; left: 40px; width: 1000px; clip-path: inset(0 70% 0 0)">Share words</div>
</section>
<section id="s2" class="clip scene" data-start="4" data-duration="2" data-track-index="2">
  <div class="t" id="later" data-read style="top: 1750px">Later words</div>
</section>
<section id="s3" class="clip scene" data-start="0" data-duration="6" data-track-index="3">
  <div class="t" id="fading" data-read style="top: 1680px; left: 600px">Fading scene</div>
</section></div>
<script>
  const tl = gsap.timeline({{ paused: true }});
  tl.set("#long", {{ opacity: 1 }}, 0.49).set("#long", {{ opacity: 0 }}, 3.49);
  tl.set("#short", {{ opacity: 1 }}, 0.49).set("#short", {{ opacity: 0 }}, 0.99);
  tl.fromTo("#reveal", {{ clipPath: "inset(0 100% 0 0)" }}, {{ clipPath: "inset(0 0% 0 0)", duration: 0.4, ease: "none" }}, 0.99);
  tl.fromTo("#wide", {{ scale: 1.05 }}, {{ scale: 1, duration: 0.45, ease: "power3.out", immediateRender: false }}, 1.99);
  tl.set("#w2", {{ opacity: 1 }}, 1.99);
  tl.to("#s3", {{ opacity: 0, duration: 0.02 }}, 2.99);
  window.__timelines = {{ main: tl }};
</script>
</body></html>
"""


def need_npx():
    if shutil.which("npx") is None:  # asked for and cannot run: a failure, never a quiet skip
        pytest.fail("APR_BROWSER_TESTS=1 asks for the browser tests, but npx is not installed")


def measured(p):
    need_npx()
    lines = rc.measure(p, load_project(p))
    return {x["caption"]: x for x in lines if "i" in x}, next(x for x in lines if "done" in x)


@pytest.fixture
def cases(tmp_path):
    p = write_project(tmp_path, duration=6)
    (p / "index.html").write_text(CASES)
    return p


def test_a_short_hold_is_warned_and_a_long_one_is_not(cases):
    need_npx()
    r = run_script("read_check.py", cases)
    assert r.returncode == 0, r.stderr
    warned = [x for x in r.stdout.splitlines() if x.startswith("warning:")]
    assert not any("#long" in x for x in warned)
    (short,) = [x for x in warned if "#short" in x]
    m = re.search(r"readable for ([\d.]+) s from ([\d.]+) s; it needs 0.80 s", short)
    assert m and abs(float(m.group(1)) - 0.5) <= 2 / FPS and abs(float(m.group(2)) - 0.5) <= 2 / FPS, short


def test_what_counts_as_readable(cases):
    caps, done = measured(cases)
    run = {name: rc.longest_run(c["runs"]) for name, c in caps.items()}
    assert run["#long"] == (90, 15)
    assert run["#short"] == (15, 15)
    for name in ("#faded", "#blurred", "#clipped", "#hidden", "#cut", "#away", "#share"):  # #share: 70% of 1000 px
        assert run[name] == (0, None), name
    assert run["#reveal"][1] in range(40, 44), run["#reveal"]  # the reveal ends at 1.39 s, frame 42
    assert run["#reveal"][0] == 180 - run["#reveal"][1]
    assert run["#wide"] == (180, 0)  # its box is 5% wider than the frame at 2 s; its words are not
    assert run["#staged"] == (120, 60)  # readable only when its second word is in
    assert run["#later"] == (60, 120)  # only inside its scene's time
    assert run["#fading"] == (90, 0)  # until its scene fades out
    assert caps["#glued"]["words"] == 2 and caps["#staged"]["words"] == 2
    assert [name for name, _ in done["captions"]] == ["#long", "#short", "#faded", "#blurred", "#clipped", "#reveal",
                                                     "#hidden", "#cut", "#wide", "#staged", "#glued", "#away", "#share",
                                                     "#later", "#fading"]


def test_a_fade_of_the_whole_reel_ends_every_caption(tmp_path):
    p = write_project(tmp_path, duration=6)
    (p / "index.html").write_text(CASES.replace("  window.__timelines", '  tl.to("#root", { opacity: 0, duration: 0.02 }, 2.99);\n'
                                                "  window.__timelines", 1))
    caps, _ = measured(p)
    run = {name: rc.longest_run(c["runs"]) for name, c in caps.items()}
    assert run["#wide"] == (90, 0) and run["#long"] == (75, 15)
    assert run["#later"] == (0, None)  # its scene starts at 4 s, after the fade


WORDS = {"#hook-words": 5, "#cap-a": 6, "#cap-b": 2, "#feat-title": 3, "#fl-0": 3, "#fl-1": 3, "#fl-2": 3, "#ben-0": 2,
         "#ben-1": 2, "#ben-2": 2, "#ben-line": 3, "#val-a": 1, "#val-b": 1, "#val-sub": 4, "#wordmark": 2,
         "#tagline": 5, "#cta": 1}


@pytest.mark.parametrize("fmt", ["9:16", "4:5"])
def test_the_stock_template_reports_every_caption(tmp_path, fmt):
    need_npx()
    p, _ = build(tmp_path, fmt=fmt)
    # a silent bed: the lint step fails a page whose <audio> file is missing
    sf.write(p / "assets" / "audio" / "bgm.wav", np.zeros((48000 * 30, 2), np.float32), 48000)
    caps, done = measured(p)
    assert dict(done["captions"]) == WORDS
    assert {name: c["words"] for name, c in caps.items()} == WORDS
    assert all(c["runs"] for c in caps.values()), json.dumps(caps)[:2000]
    r = run_script("read_check.py", p)
    assert r.returncode == 0 and r.stdout.splitlines()[-1].startswith("read_check: 17 captions, "), (r.stdout, r.stderr)
