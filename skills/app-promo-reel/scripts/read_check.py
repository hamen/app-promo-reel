#!/usr/bin/env python3
"""Reading time: is each caption of a built reel on screen long enough to read?

Run it after build.py and the check command (9:16 and 4:5). It prints one warning per caption that is
readable for less time than it needs, then a summary, and exits 0. A warning never fails: the critique
decides (references/storyboard.md, "Reading time"). It exits 2 when it cannot measure.

1. Captions: the elements with the `data-read` attribute. Their words are counted per text node with
   the browser's word breaker (Intl.Segmenter, the page's language), so a language without spaces
   counts words too.
2. Rule: a caption needs max(MIN_READ, PER_WORD x words) seconds. Its time is its longest readable run,
   in frames. It is short when that run has fewer frames than the need.
3. Readable, at a frame: inside its scene's time; it and every element inside it that holds a word of
   its own are shown (no display: none, visibility visible, opacity 0.9 or more along the way up to the
   scene, no blur over 2 px), not cut by a clip-path or an overflow box, and the box of its text is
   inside its scene's box.
4. How: the measuring pass seeks the timeline frame by frame, and a page that seeks its timeline at
   load renders differently (measured: 765 of 900 frames changed). So the pass never goes into the
   project's index.html. read_check copies index.html, adds the pass, puts the copy in a temporary
   folder next to symlinks to the other project files, and runs `hyperframes check` on that folder. The
   pass reports through console warnings that carry a token drawn for the run; other findings of that
   check are ignored (the build's own check command reports them). The folder is removed at the end,
   also on an error or Ctrl-C. The project is never changed.

Usage: read_check.py <project_dir>
"""
import argparse
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import HYPERFRAMES  # noqa: E402
from common import die, is_silent, load_project  # noqa: E402

MIN_READ = 0.8   # seconds: the shortest time any text the viewer must read stays readable
PER_WORD = 0.3   # seconds per word for a longer line (references/storyboard.md, "Reading time")
CHECK_TIMEOUT = 300
LEFT_OUT = ("index.html", "renders", "snapshots", "reviews")

# The measuring pass, added to the COPY of index.html only. No clock and no random value: hyperframes
# lint rejects them, as build.py does. __TOKEN__, __FPS__ and __DURATION__ are filled in by read_check.
PASS = r"""<script data-read-check>
(() => {
  const TOKEN = "__TOKEN__", FPS = __FPS__, DURATION = __DURATION__, PX = 2, BLUR_PX = 2;
  const say = (o) => console.warn(TOKEN + " " + JSON.stringify(o));
  try {
    const tl = (window.__timelines || {}).main;
    if (!tl || typeof tl.seek !== "function") {
      say({ done: false, error: "the page has no window.__timelines.main" });
      return;
    }
    const root = document.querySelector("[data-composition-id]");
    const scenes = [...document.querySelectorAll("section[data-start]")];
    // the runtime hides the root and the scenes until its first seek: shown here, the visibility of a
    // caption is its own (this copy is thrown away)
    for (const n of [root, ...scenes]) if (n) n.style.setProperty("visibility", "visible", "important");
    const seg = new Intl.Segmenter(document.documentElement.lang || undefined, { granularity: "word" });
    const wordsIn = (s) => { let k = 0; for (const x of seg.segment(s)) if (x.isWordLike) k++; return k; };
    const textNodes = (el) => {
      const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), out = [];
      for (let n = w.nextNode(); n; n = w.nextNode()) out.push(n);
      return out;
    };
    const caps = [...document.querySelectorAll("[data-read]")].map((el, i) => {
      const nodes = textNodes(el);
      const scene = el.closest("section[data-start]");
      const start = scene ? parseFloat(scene.getAttribute("data-start")) : 0;
      const length = scene && scene.hasAttribute("data-duration") ? parseFloat(scene.getAttribute("data-duration")) : DURATION;
      return {
        el, scene, i, start, end: start + length,
        name: el.id ? "#" + el.id : `${el.tagName.toLowerCase()}[data-read] number ${i + 1}`,
        words: nodes.reduce((k, n) => k + wordsIn(n.data), 0),
        text: nodes.map((n) => n.data.replace(/\s+/g, " ").trim()).filter(Boolean).join(" "),
        holders: [...new Set(nodes.filter((n) => wordsIn(n.data) > 0).map((n) => n.parentElement))],
        runs: [], from: -1,
      };
    });
    const inside = (a, b) => a.left >= b.left - PX && a.right <= b.right + PX && a.top >= b.top - PX && a.bottom <= b.bottom + PX;
    const textBox = (el) => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect(); };
    const worstBlur = (filter) => {
      let worst = 0;
      for (const m of filter.matchAll(/blur\(\s*([\d.]+)px\s*\)/g)) worst = Math.max(worst, parseFloat(m[1]));
      return worst;
    };
    // the box an inset() clip-path leaves, from the element's border box; null for any other shape
    const insetBox = (clip, el, box) => {
      const m = /^inset\((.*)\)$/.exec(clip.trim());
      if (!m) return null;
      const p = m[1].split(/\s+round\s+/)[0].trim().split(/\s+/);
      const [t, r, b, l] = [p[0], p[1] ?? p[0], p[2] ?? p[0], p[3] ?? p[1] ?? p[0]];
      const sx = el.offsetWidth ? box.width / el.offsetWidth : 1, sy = el.offsetHeight ? box.height / el.offsetHeight : 1;
      const x = (v) => (v.endsWith("%") ? (parseFloat(v) / 100) * box.width : parseFloat(v) * sx);
      const y = (v) => (v.endsWith("%") ? (parseFloat(v) / 100) * box.height : parseFloat(v) * sy);
      return { left: box.left + x(l), right: box.right - x(r), top: box.top + y(t), bottom: box.bottom - y(b) };
    };
    const paddingBox = (el, cs, box) => {
      const sx = el.offsetWidth ? box.width / el.offsetWidth : 1, sy = el.offsetHeight ? box.height / el.offsetHeight : 1;
      return { left: box.left + parseFloat(cs.borderLeftWidth) * sx, right: box.right - parseFloat(cs.borderRightWidth) * sx,
               top: box.top + parseFloat(cs.borderTopWidth) * sy, bottom: box.bottom - parseFloat(cs.borderBottomWidth) * sy };
    };
    const holderShown = (holder, scene) => {
      if (getComputedStyle(holder).visibility !== "visible") return false;
      const own = textBox(holder);
      let opacity = 1;
      for (let n = holder; n && n !== scene && n !== root; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.display === "none") return false;
        opacity *= parseFloat(cs.opacity);
        if (worstBlur(cs.filter) > BLUR_PX) return false;
        const box = n.getBoundingClientRect();
        if (cs.clipPath && cs.clipPath !== "none") {
          const kept = insetBox(cs.clipPath, n, box);
          if (!kept || !inside(own, kept)) return false;
        }
        if (cs.overflowX !== "visible" || cs.overflowY !== "visible") {
          if (!inside(own, paddingBox(n, cs, box))) return false;
        }
      }
      return opacity >= 0.9;
    };
    const readable = (c, t) => {
      if (t < c.start || t >= c.end) return false;
      if (!c.holders.every((h) => holderShown(h, c.scene))) return false;
      const own = textBox(c.el);
      if (!own.width || !own.height) return false;
      return inside(own, (c.scene || root).getBoundingClientRect());
    };
    const timed = caps.filter((c) => c.words > 0);
    let f = 0;
    for (; f / FPS < DURATION - 1e-9; f++) {
      tl.seek(f / FPS);
      for (const c of timed) {
        if (readable(c, f / FPS)) { if (c.from < 0) c.from = f; }
        else if (c.from >= 0) { c.runs.push([c.from, f]); c.from = -1; }
      }
    }
    for (const c of timed) if (c.from >= 0) c.runs.push([c.from, f]);
    tl.seek(0);
    for (const c of timed) say({ i: c.i, caption: c.name, text: c.text, words: c.words, runs: c.runs });
    say({ done: true, captions: caps.map((c) => [c.name, c.words]) });
  } catch (e) {
    say({ done: false, error: String(e && e.stack || e) });
  }
})();
</script>
"""


def need(words):
    """Seconds a caption of `words` words must stay readable."""
    return max(MIN_READ, PER_WORD * words)


def need_frames(words, fps):
    return math.ceil(need(words) * fps - 1e-9)


def longest_run(runs):
    """(frames, first frame) of the longest of `runs`, half-open [first, end) frame ranges; the earlier
    one on a tie. (0, None) when there is none."""
    best = (0, None)
    for a, b in runs:
        if b - a > best[0]:
            best = (b - a, a)
    return best


def with_pass(html, token, fps, duration):
    """The page with the measuring pass just before its last </body>; None when it has none."""
    end = html.rfind("</body>")
    if end < 0:
        return None
    script = (PASS.replace("__TOKEN__", token).replace("__FPS__", repr(float(fps)))
              .replace("__DURATION__", repr(float(duration))))
    return html[:end] + script + html[end:]


def make_folder(project_dir, page, tmp):
    """Fill `tmp` with a symlink to each top entry of the project but LEFT_OUT, and `page` as index.html."""
    for entry in sorted(Path(project_dir).iterdir()):
        if entry.name not in LEFT_OUT:
            os.symlink(entry.resolve(), Path(tmp) / entry.name)
    (Path(tmp) / "index.html").write_text(page, encoding="utf-8")


def findings(doc):
    """Every object with a `code` and a `severity` in the check's JSON (the walk of test_feed_check.py)."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            if "code" in x and "severity" in x:
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc)
    return found


def pass_lines(doc, token):
    """The JSON bodies of the pass's warnings: messages that start with the run's token."""
    out = []
    for f in findings(doc):
        msg = f.get("message")
        if isinstance(msg, str) and msg.startswith(token + " "):
            try:
                out.append(json.loads(msg[len(token) + 1:]))
            except ValueError:
                die(f"a reading-time line of the check does not parse: {msg[:200]}")
    return out


def run_check(folder):
    npx = shutil.which("npx")
    if npx is None:
        die("npx is not installed: read_check runs `hyperframes check` (Node.js)")
    cmd = [npx, "--yes", HYPERFRAMES, "check", str(folder), "--json", "--no-contrast"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        die(f"hyperframes check did not finish in {CHECK_TIMEOUT} s")
    try:
        return json.loads(r.stdout)
    except ValueError:
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        die("hyperframes check gave no JSON (exit {}):\n  {}".format(r.returncode, "\n  ".join(tail)))


def report(lines, fps):
    """The output lines for the pass's results. Dies when the pass did not finish or a caption has no line."""
    done = [x for x in lines if isinstance(x, dict) and "done" in x]
    if not done:
        die("the reading-time pass did not report (no done line in the check's output)")
    if done[-1]["done"] is not True:
        die(f"the reading-time pass failed: {done[-1].get('error', 'no reason given')}")
    listed = done[-1].get("captions", [])
    if not listed:
        return ["warning: reading time: no text is marked data-read; nothing was timed"]
    by_index = {x["i"]: x for x in lines if isinstance(x, dict) and "i" in x}
    out, short = [], []
    for i, (name, words) in enumerate(listed):
        if not words:
            out.append(f"read_check: {name} has no words, not timed")
            continue
        if i not in by_index:
            die(f"the reading-time pass gave no result for {name}")
        c = by_index[i]
        frames, first = longest_run(c["runs"])
        if frames < need_frames(words, fps):
            when = f" from {first / fps:.1f} s" if first is not None else " (never)"
            short.append(((first if first is not None else math.inf), i,
                          f'warning: reading time: {name} "{c["text"]}" ({words} word{"s" if words != 1 else ""}) '
                          f"is readable for {frames / fps:.1f} s{when}; it needs {need(words):.1f} s"))
    out += [line for *_, line in sorted(short)]
    timed = sum(1 for _, words in listed if words)
    out.append(f"read_check: {timed} caption{'s' if timed != 1 else ''}, {len(short)} short")
    return out


def measure(project_dir, project):
    """The pass's lines for the built page of the project, measured in a throw-away folder."""
    index = Path(project_dir) / "index.html"
    if not index.is_file():
        die(f"{index} not found: run build.py first")
    token = secrets.token_hex(8)
    page = with_pass(index.read_text(encoding="utf-8"), token, project["fps"], project["duration"])
    if page is None:
        die(f"{index} has no </body>: the reading-time pass goes just before it")
    folder = tempfile.mkdtemp(prefix="reel-read-")
    try:
        make_folder(project_dir, page, folder)
        doc = run_check(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return pass_lines(doc, token)


def read_check(project_dir):
    project = load_project(project_dir)
    if is_silent(project):
        print(f"read_check: {project['format']} is a silent loop, not checked")
        return 0
    for line in report(measure(project_dir, project), project["fps"]):
        print(line)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    a = ap.parse_args(argv)
    sys.exit(read_check(a.project_dir))


if __name__ == "__main__":
    main()
