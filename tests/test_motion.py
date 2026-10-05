"""The motion language (template/motion.js): the spring eases and the MOTION table."""
import json
import shutil
import subprocess

import pytest

from conftest import TEMPLATE

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

OVERSHOOTS = [0, 0.06, 0.07, 0.13, 0.20, 0.35]
MAX_PEAKS = {0.06: 1, 0.07: 1, 0.13: 1, 0.20: 2, 0.35: 3}

PROG = """
const fs = require("fs");
const { spring, MOTION } = new Function(fs.readFileSync(process.argv[1], "utf8") + "; return { spring, MOTION };")();
const N = 20000;
const report = {};
for (const os of %s) {
  const f = spring(os), g = spring(os);
  const xs = Array.from({ length: N + 1 }, (_, i) => f(i / N));
  const coarse = Array.from({ length: 1001 }, (_, i) => f(i / 1000));
  const peaks = [];
  for (let i = 1; i < N; i++) if (xs[i] > xs[i - 1] && xs[i] >= xs[i + 1]) peaks.push([i / N, xs[i]]);
  report[os] = {
    f0: f(0), f1: f(1),
    finite: coarse.every(Number.isFinite),
    min: Math.min(...coarse), max: Math.max(...coarse),
    peaks,
    settle: Math.max(...xs.filter((_, i) => i / N >= 0.9).map((v) => Math.abs(v - 1))),
    same: xs.every((v, i) => v === g(i / N)),
  };
}
const throws = [-0.01, 0.36, NaN, undefined].map((v) => { try { spring(v); return false; } catch (e) { return true; } });
const shape = {};
for (const [k, v] of Object.entries(MOTION))
  shape[k] = Object.fromEntries(Object.entries(v).map(([a, b]) => [a, typeof b === "function" ? "function" : b]));
console.log(JSON.stringify({ report, throws, shape }));
""" % json.dumps(OVERSHOOTS)


@pytest.fixture(scope="module")
def result():
    r = subprocess.run(["node", "-e", PROG, "--", str(TEMPLATE / "motion.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("os", OVERSHOOTS)
def test_a_spring_starts_at_0_and_lands_exactly_on_1(result, os):
    m = result["report"][str(os)]
    assert m["f0"] == 0 and m["f1"] == 1 and m["finite"]


@pytest.mark.parametrize("os", OVERSHOOTS)
def test_a_spring_never_goes_below_0(result, os):
    assert result["report"][str(os)]["min"] >= 0


def test_a_spring_with_no_overshoot_never_goes_above_1(result):
    assert result["report"]["0"]["max"] <= 1


@pytest.mark.parametrize("os", [o for o in OVERSHOOTS if o])
def test_the_first_peak_is_the_overshoot_asked_for_and_comes_at_a_visible_time(result, os):
    p, v = result["report"][str(os)]["peaks"][0]
    assert abs(v - (1 + os)) < 0.01
    assert 0.15 < p < 0.6


@pytest.mark.parametrize("os", [o for o in OVERSHOOTS if o])
def test_a_spring_does_not_ring(result, os):
    visible = [p for p in result["report"][str(os)]["peaks"] if p[1] > 1.005]
    assert len(visible) <= MAX_PEAKS[os]


@pytest.mark.parametrize("os", OVERSHOOTS)
def test_a_spring_is_settled_for_the_last_tenth_and_is_deterministic(result, os):
    m = result["report"][str(os)]
    assert m["settle"] < 0.01 and m["same"]


def test_an_overshoot_outside_0_to_0_35_throws(result):
    assert result["throws"] == [True, True, True, True]


@pytest.mark.parametrize("cls", ["micro", "panel", "headline", "icon"])
def test_a_motion_class_has_a_spring_ease_and_a_duration(result, cls):
    c = result["shape"][cls]
    assert c["ease"] == "function" and 0 < c["dur"] < 1


def test_the_camera_class_is_two_named_eases_and_never_a_spring(result):
    c = result["shape"]["camera"]
    assert c == {"drift": "sine.inOut", "move": "power2.inOut"}
