#!/usr/bin/env python3
"""Build <project>/index.html from <project>/src.html.tmpl.

Tokens (the `{{ }}` delimiter never appears in CSS, so @font-face/@media/@keyframes are safe):
  {{D bar}} / {{D bar beat}}   time of that beat (see common.py for the addressing)
  {{E bar}} / {{E bar beat}}   the "and" after that beat
  {{LEN a b}}                  D(b) - D(a)
  {{TO_END bar}}               duration - D(bar)
  {{calc <expr>}}              arithmetic: numbers, + - * /, parentheses, D(), E(), DURATION
  {{BEATS}}                    JSON array of every beat time
  {{DOWNBEAT_INDEX}}           index in BEATS of the first downbeat
  {{BEATS_PER_BAR}}            from project.json
  {{DURATION}}                 from project.json
  {{STORES}}                   JSON array of the project's stores (project.json)

SFX: cues.json -> <audio> tags in place of `<!--SFX-->`, plus cues.realized.json, the list of
cues actually mixed (finish.py checks sync against that list only). A cue whose file is
missing is skipped with a warning. Cue fields: id, sfx (key in the "sfx" map), at (a calc
expression), offset (s, default 0), volume (default 0.5), align ("attack" default: the
sound's audible attack lands on `at`, skipping any leading silence in the file; "start": the
file starts at `at`; "end": the sound ends at `at`, e.g. a riser tail into the drop), sync
(default true, false for align "end": finish.py checks only cues with a sharp attack).

Usage: build.py <project_dir>
"""
import ast
import html
import json
import operator
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Grid, attack_seconds, die, load_project, media_duration, read_json  # noqa: E402

TOKEN = re.compile(r"\{\{\s*([A-Za-z_]+)\s*(.*?)\s*\}\}", re.S)
SFX_FIRST_TRACK = 21
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class CalcError(ValueError):
    pass


def calc(expr, grid, duration):
    """Evaluate arithmetic over D()/E()/DURATION without eval()."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise CalcError(f"bad expression {expr!r}: {e.msg}") from None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Name) and node.id == "DURATION":
            return duration
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("D", "E")
                and not node.keywords and 1 <= len(node.args) <= 2):
            args = [ev(a) for a in node.args]
            if any(a != int(a) for a in args):
                raise CalcError(f"{node.func.id}() takes whole numbers in {expr!r}")
            return getattr(grid, node.func.id)(*[int(a) for a in args])
        raise CalcError(f"not allowed in calc: {ast.dump(node)[:60]} in {expr!r}")

    try:
        return float(ev(tree))
    except (ValueError, ArithmeticError) as e:  # ArithmeticError: 1/0, overflow
        raise CalcError(f"{e} in {expr!r}") from None


def _ints(name, args, n_min, n_max):
    parts = args.split()
    if not n_min <= len(parts) <= n_max or not all(re.fullmatch(r"-?\d+", p) for p in parts):
        raise CalcError(f"{{{{{name} {args}}}}} needs {n_min}-{n_max} whole-number arguments")
    return [int(p) for p in parts]


def substitute(src, grid, project):
    duration = project["duration"]

    def sub(m):
        name, args = m.group(1), m.group(2)
        if name in ("D", "E"):
            return f"{getattr(grid, name)(*_ints(name, args, 1, 2)):.3f}"
        if name == "LEN":
            a, b = _ints(name, args, 2, 2)
            return f"{grid.D(b) - grid.D(a):.3f}"
        if name == "TO_END":
            (a,) = _ints(name, args, 1, 1)
            return f"{duration - grid.D(a):.3f}"
        if name == "calc":
            return f"{calc(args, grid, duration):.3f}"
        if name == "BEFORE_END":
            margin, _, expr = args.partition(" ")
            t = calc(expr, grid, duration)
            if t > duration - float(margin):
                die(f"{expr} is at {t:.2f}s; the template needs it at least {float(margin):g}s before the "
                    f"{duration:g}s end so the text after it can be read. The storyboard needs fewer bars at "
                    f"this tempo/duration: re-map the scenes (references/storyboard.md)")
            return ""
        if args:
            raise CalcError(f"{{{{{name}}}}} takes no arguments")
        if name == "BEATS":
            return json.dumps([round(b, 3) for b in grid.beats])
        if name == "DOWNBEAT_INDEX":
            return str(grid.first)
        if name == "BEATS_PER_BAR":
            return str(grid.bpb)
        if name == "DURATION":
            return f"{duration:g}"
        if name == "STORES":
            return json.dumps(project["stores"])
        raise CalcError(f"unknown token {{{{{name}}}}}")

    try:
        out = TOKEN.sub(sub, src)
    except ValueError as e:
        die(str(e))
    left = re.search(r"\{\{.*?\}\}", out, re.S)
    if left:
        die(f"leftover token after build: {left.group(0)[:60]!r}")
    return out


def sfx_tags(project_dir, cues_doc, grid, duration, durations=None):
    """Return (html_lines, realized) for the cues whose sound file exists."""
    audio_dir = Path(project_dir) / "assets" / "audio"
    files, cues = cues_doc.get("sfx", {}), cues_doc.get("cues", [])
    if not isinstance(files, dict) or not isinstance(cues, list):
        die('cues.json: "sfx" must be an object and "cues" an array')
    lines, realized, track_end, leads, seen = [], [], {}, {}, set()
    durations = {} if durations is None else durations
    for cue in cues:
        if not isinstance(cue, dict) or any(k not in cue for k in ("id", "sfx", "at")):
            die(f"cues.json: every cue needs id, sfx and at, got {str(cue)[:80]}")
        cid, key = cue["id"], cue["sfx"]
        if cid in seen:
            die(f"cues.json: cue id {cid!r} is used twice")
        seen.add(cid)
        try:
            at, offset, vol = str(cue["at"]), float(cue.get("offset", 0)), float(cue.get("volume", 0.5))
        except (TypeError, ValueError):
            die(f"cue {cid!r}: offset and volume must be numbers")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(cid)):
            die(f"cue id {cid!r} must use only letters, digits, - and _")
        if key not in files:
            die(f"cue {cid!r} uses sfx {key!r}, which is not in the cues.json sfx map")
        path = audio_dir / files[key]
        if not path.is_file():
            print(f"warning: skipping cue {cid!r}: {path} not found", file=sys.stderr)
            continue
        try:
            t = calc(at, grid, duration) + offset
        except CalcError as e:
            die(f"cue {cid!r}: {e}")
        if path not in durations:
            durations[path] = media_duration(path)
            leads[path] = attack_seconds(path)
        align = cue.get("align", "attack")
        if align not in ("attack", "start", "end"):
            die(f"cue {cid!r}: align must be attack, start or end")
        if align == "attack":
            t -= leads[path]  # the audible attack, not the file's leading silence, lands on `at`
        elif align == "end":
            t -= durations[path]
        if not 0 <= t < duration:
            print(f"warning: skipping cue {cid!r}: time {t:.3f} is outside 0-{duration:g}", file=sys.stderr)
            continue
        d = min(durations[path], duration - t)
        track = SFX_FIRST_TRACK
        while track_end.get(track, -1.0) > t:
            track += 1
        track_end[track] = t + d
        rel = f"assets/audio/{files[key]}"
        lines.append(f'      <audio id="sfx-{cid}" src="{html.escape(rel, quote=True)}" data-start="{t:.3f}" data-duration="{d:.3f}" '
                     f'data-track-index="{track}" data-volume="{vol:g}"></audio>')
        sync = bool(cue.get("sync", align != "end"))
        realized.append({"id": cid, "file": rel, "time": round(t, 4), "volume": vol, "track": track,
                         "align": align, "sync": sync})
    return lines, realized


MIN_SCENE_TAIL = 2.0  # seconds a scene (the end card above all) must have before the video ends


def check_scenes(html_out, duration):
    """Every scene must start inside the video, at least MIN_SCENE_TAIL before its end: a scene
    past the end is silently never shown, and one that starts 0.1 s before it cannot be read."""
    bad = []
    for tag in re.findall(r"<section\b[^>]*>", html_out):
        start = re.search(r'\bdata-start="([^"]*)"', tag)
        if not start:
            continue
        name = re.search(r'\bid="([^"]*)"', tag)
        try:
            t = float(start.group(1))
        except ValueError:
            t = float("nan")
        if not 0 <= t <= duration - MIN_SCENE_TAIL:
            bad.append(f"{name.group(1) if name else tag[:40]} at {start.group(1)}s")
    if bad:
        die(f"scenes outside the {duration:g}s video or starting less than {MIN_SCENE_TAIL:g}s before its "
            f"end: {', '.join(bad)}. The storyboard needs fewer bars at "
            f"this tempo/duration: re-map the scenes (references/storyboard.md)")


# Injected by build.py as the LAST script of the page. The label is not part of the template: this
# script creates it from CONFIG.aiLabel, with an id drawn at build time (no Math.random in the page:
# HyperFrames needs deterministic scripts) that no template rule or tween can know, and
# every visual property inline !important (which no stylesheet rule overrides), as the last child
# of the composition root. It then checks the label's box and every ancestor, and throws
# (hyperframes check: page_error; render: nothing) when the label would not be seen.
AI_LABEL_GUARD = r"""<script data-ai-label-guard>
(() => {
  const fail = (why) => { throw new Error(`the AI-generated label ${why}: it must stay on screen`); };
  const text = typeof CONFIG === "object" && CONFIG !== null ? CONFIG.aiLabel : undefined;
  if (typeof text !== "string" || !text.trim()) fail("(CONFIG.aiLabel) is missing or empty");
  const root = document.querySelector("[data-composition-id]");
  if (!root) fail("has no composition root to sit in");
  const el = document.createElement("div");
  el.id = "__AI_LABEL_ID__";
  el.textContent = text;
  // "all: initial" first, so no template rule reaches the label itself (text-indent, text fill,
  // text-shadow, a font that draws nothing ...); then the look, which comes after and wins
  const look = {
    all: "initial", display: "block", position: "absolute", right: "44px", bottom: "40px", "z-index": "2147483647",
    margin: "0", padding: "10px 22px", "border-radius": "999px", background: "rgba(0, 0, 0, 0.62)",
    border: "1px solid rgba(255, 255, 255, 0.35)", color: "#ffffff", "font-family": "sans-serif",
    "font-size": "24px", "font-weight": "700", "letter-spacing": "0.04em", "line-height": "1.25",
    "white-space": "nowrap", visibility: "visible", opacity: "1", transform: "none", filter: "none",
    "clip-path": "none", "pointer-events": "none",
  };
  for (const [k, v] of Object.entries(look)) el.style.setProperty(k, v, "important");
  root.appendChild(el);
  const own = getComputedStyle(el);
  const alpha = (c) => { const m = c.match(/rgba?\(([^)]*)\)/); const v = m ? m[1].split(/[\s,\/]+/) : [];
    return m ? (v.length > 3 ? parseFloat(v[3]) : 1) : 0; };
  if (alpha(own.color) < 0.5 || alpha(own.webkitTextFillColor) < 0.5 || own.textIndent !== "0px" ||
      own.fontSize !== "24px") fail("text is restyled out of sight");
  // the label's own inline visibility: visible wins over any hidden ancestor (the runtime hides
  // [data-start] elements until its first seek), so ancestors can only hide it by display,
  // opacity, filter or clip-path: check each one up to <html>
  const dim = (filter) => [...filter.matchAll(/(opacity|brightness)\(\s*([\d.]+)(%?)\s*\)/g)]
    .reduce((f, m) => f * (parseFloat(m[2]) / (m[3] ? 100 : 1)), 1);
  let opacity = 1;
  for (let n = el; n; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.display === "none") fail("sits in an element with display: none");
    if (cs.clipPath !== "none") fail("is clipped");
    opacity *= parseFloat(cs.opacity) * dim(cs.filter);
  }
  if (opacity < 0.5) fail("is faded out (opacity or filter of the label and its ancestors)");
  const box = el.getBoundingClientRect(), frame = root.getBoundingClientRect();
  if (box.width < 1 || box.height < 1 || box.left < frame.left || box.top < frame.top ||
      box.right > frame.right || box.bottom > frame.bottom) fail("is not fully inside the frame");
})();
</script>
"""


def check_ai_label(html_out):
    """Static half of the AI-generated label (EU AI Act): CONFIG.aiLabel must be a non-empty
    string. The runtime half, AI_LABEL_GUARD, creates the label and checks it can be seen."""
    m = re.search(r'"aiLabel"\s*:\s*"((?:[^"\\]|\\.)*)"', html_out)
    if not m or not m.group(1).strip():
        die("CONFIG.aiLabel is missing or empty: the AI-generated label must stay on screen (SKILL.md rule 7)")


def add_ai_label_guard(html_out):
    end = html_out.rfind("</body>")
    if end < 0:
        die("the page has no </body>: build.py puts the AI-generated label check just before it")
    guard = AI_LABEL_GUARD.replace("__AI_LABEL_ID__", "ai-label-" + secrets.token_hex(6))
    return html_out[:end] + guard + html_out[end:]


def build(project_dir):
    project_dir = Path(project_dir)
    project = load_project(project_dir)
    tmpl = project_dir / "src.html.tmpl"
    beats = project_dir / "beats.json"
    for p in (tmpl, beats):
        if not p.is_file():
            die(f"{p} not found")
    # a build that fails must not leave the previous build behind for a render to pick up
    for old in ("index.html", "cues.realized.json"):
        (project_dir / old).unlink(missing_ok=True)
    grid = Grid.load(beats, project["beats_per_bar"])
    out = substitute(tmpl.read_text(), grid, project)
    cues_path = project_dir / "cues.json"
    cues_doc = read_json(cues_path) if cues_path.is_file() else {}
    lines, realized = sfx_tags(project_dir, cues_doc, grid, project["duration"])
    if "<!--SFX-->" in out:
        out = out.replace("<!--SFX-->", "\n".join(lines).lstrip() if lines else "")
    elif lines:
        die("src.html.tmpl has no <!--SFX--> marker for the SFX tags")
    check_scenes(out, project["duration"])
    check_ai_label(out)
    out = add_ai_label_guard(out)
    (project_dir / "index.html").write_text(out)
    (project_dir / "cues.realized.json").write_text(json.dumps(realized, indent=1) + "\n")
    print(f"built {project_dir / 'index.html'}: {len(realized)} SFX cues mixed; downbeats "
          f"{[round(b, 2) for b in grid.beats[grid.first::grid.bpb]]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        die(__doc__.strip().splitlines()[-1])
    build(sys.argv[1])
