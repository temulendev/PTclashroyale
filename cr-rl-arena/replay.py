"""Record matches as replays and watch them in the browser viewer (gym/viewer).

    from replay import Recorder, serve
    rec = Recorder()                       # starts a fresh matches/ folder
    rec.play(bot0, bot1, seed, "evil", "random")
    serve()                                # opens http://localhost:8000

Every match becomes its own self-contained folder under matches/:
    matches/003_evil_vs_random_seed3_loss/
        index.html      the replay, with its data inside -- double-click to watch, no server needed
        open.command    Mac launcher      open.bat  Windows      open.sh  Linux
        match.json      the raw replay data
        README.txt

From the shell:
    python replay.py            watch everything in matches/ (local viewer with a match picker)
    python replay.py zip        pack matches/ into matches.zip, ready to send to someone
"""
import functools
import http.server
import json
import os
import shutil
import zipfile
import threading
import urllib.parse
import webbrowser

import cr_sim

VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym", "viewer")
MATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matches")
FPS_DIVISOR = 2          # keep every 2nd tick -> 10 frames per second of game time


def _real_pos(seat, x, y):
    """An action's (x, y) in that seat's own frame -> the board the viewer draws (as the server records it)."""
    x, y = float(x), float(y)
    return (round(x, 1), round(cr_sim.HEIGHT - y if seat == 1 else y, 1))


def play_recorded(bot0, bot1, seed, deck0="default", deck1="default", name0="p0", name1="p1"):
    """Play one match and return (result for seat 0, trace dict for the viewer)."""
    b = cr_sim.Battle()
    b.reset(seed, deck0, deck1)
    v = (b.view(0), b.view(1))
    cards = b.deployable_cards() + ["princess_tower", "king_tower"]
    card_idx = {n: i for i, n in enumerate(cards)}

    frames, events, seen = [], [], [set(), set()]
    pending = [None, None]              # (tick, card, x, y) sent last tick, waiting to hear if it landed
    while v[0].result() is None:
        obs = (v[0].observe(), v[1].observe())
        for p in (0, 1):
            seen[p].update(obs[p]["hand"])
            if pending[p] and obs[p]["last_action"] == "ok":
                events.append([pending[p][0], p, *pending[p][1:]])
            pending[p] = None
        acts = (bot0(obs[0]), bot1(obs[1]))
        for p in (0, 1):
            a = acts[p]
            if a is None:
                continue
            if a[0] == cr_sim.ABILITY_SLOT:
                pending[p] = (obs[p]["tick"], "ability", *_real_pos(p, a[1], a[2]))
            elif 0 <= a[0] < 4:
                pending[p] = (obs[p]["tick"], obs[p]["hand"][a[0]], *_real_pos(p, a[1], a[2]))
        b.step(acts[0], acts[1])

        t = b.tick
        if t % FPS_DIVISOR == 0 or v[0].result() is not None:
            ents = []
            for (owner, card, x, y, hp, mhp, flying, tower, deploying, eid, hw, hh) in b.spectator_entities():
                flags = (1 if flying else 0) | (2 if tower else 0) | (4 if deploying else 0)
                ents.append([owner, card_idx.get(card, 0), round(x, 2), round(y, 2),
                             round(hp / mhp, 3) if mhp else 0.0, flags, eid, round(hw, 2)])
            frames.append({"t": t, "crowns": list(b.crowns()),
                           "elixir": [round(b.elixir(0), 2), round(b.elixir(1), 2)], "ents": ents})

    # a final action can still be confirmed by the last observation
    for p in (0, 1):
        if pending[p] and v[p].last_action() == "ok":
            events.append([pending[p][0], p, *pending[p][1:]])
    events.sort(key=lambda e: e[0])

    deck = lambda d, p: sorted(seen[p]) if d == "default" else list(d)
    trace = {
        "meta": {
            "seed": seed, "w": cr_sim.WIDTH, "h": cr_sim.HEIGHT,
            "river_y": cr_sim.RIVER_Y, "river_half": cr_sim.RIVER_HALF,
            "bridges": cr_sim.BRIDGES, "bridge_half": cr_sim.BRIDGE_HALF, "level": 11,
            "tps": cr_sim.TICKS_PER_SECOND, "fps": cr_sim.TICKS_PER_SECOND // FPS_DIVISOR,
            "cards": cards, "outcome": b.outcome(), "end_tick": b.tick, "crowns": list(b.crowns()),
            "p0": name0, "p1": name1, "deck0": deck(deck0, 0), "deck1": deck(deck1, 1),
        },
        "frames": frames,
        "events": events,
    }
    return v[0].result(), trace


LAUNCHERS = {
    "open.command": ('#!/bin/bash\ncd "$(dirname "$0")"\nopen index.html\n', 0o755),
    "open.sh": ('#!/bin/sh\ncd "$(dirname "$0")"\n(xdg-open index.html || sensible-browser index.html) 2>/dev/null\n', 0o755),
    "open.bat": ('@echo off\r\nstart "" "%~dp0index.html"\r\n', 0o644),
}
README = """{title}
{result}

To watch: double-click index.html (any browser, no install, no internet needed
except for the nicer fonts).  open.command (Mac), open.bat (Windows) and
open.sh (Linux) do the same thing.  The first time on a Mac you may have to
right-click open.command -> Open.

Controls: Space play/pause, left/right arrows skip 5 s, 1x-8x speed, hover a unit.
match.json is the raw replay data (you can also drop it onto the viewer).
"""


def _page(trace):
    """The viewer page with this match's replay baked in, so it opens straight from disk."""
    with open(os.path.join(VIEWER_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    data = json.dumps(trace, separators=(",", ":")).replace("</", "<\\/")
    marker = '<script>\n"use strict";'
    assert html.count(marker) == 1, "viewer layout changed; cannot embed the replay"
    return html.replace(marker, "<script>window.EMBEDDED_TRACE=" + data + ";</script>\n" + marker)


class Recorder:
    """Saves each match it plays as its own folder under matches/ (see the module docstring)."""

    def __init__(self, clear=True):
        os.makedirs(MATCH_DIR, exist_ok=True)
        if clear:                      # only remove what this recorder made
            for n in os.listdir(MATCH_DIR):
                path = os.path.join(MATCH_DIR, n)
                if os.path.isdir(path) and os.path.exists(os.path.join(path, "match.json")):
                    shutil.rmtree(path)
                elif n in ("index.json", "matches.zip"):
                    os.remove(path)
        self.index = []

    def play(self, bot0, bot1, seed, name0, name1, deck0="default", deck1="default"):
        result, trace = play_recorded(bot0, bot1, seed, deck0, deck1, name0, name1)
        m = trace["meta"]
        safe = lambda t: "".join(c if c.isalnum() or c in "-_" else "-" for c in str(t))
        folder = f"{len(self.index):03d}_{safe(name0)}_vs_{safe(name1)}_seed{seed}_{result}"
        d = os.path.join(MATCH_DIR, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "match.json"), "w") as f:
            json.dump(trace, f, separators=(",", ":"))
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(_page(trace))
        for name, (text, mode) in LAUNCHERS.items():
            with open(os.path.join(d, name), "w", newline="") as f:
                f.write(text)
            os.chmod(os.path.join(d, name), mode)
        with open(os.path.join(d, "README.txt"), "w") as f:
            f.write(README.format(title=f"{name0} vs {name1} (seed {seed})",
                                  result=f"Result for {name0}: {result}, crowns {m['crowns'][0]}-{m['crowns'][1]}"))
        self.index.append({"file": f"{folder}/match.json", "p0": name0, "p1": name1, "seed": seed,
                           "result": result, "crowns": m["crowns"], "seconds": m["end_tick"] // m["tps"]})
        with open(os.path.join(MATCH_DIR, "index.json"), "w") as f:
            json.dump(self.index, f)
        return result


def make_zip(out=None):
    """Pack matches/ into one zip (launchers keep their executable bit). Returns its path."""
    out = out or os.path.join(MATCH_DIR, "matches.zip")
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(MATCH_DIR):
            for n in sorted(files):
                path = os.path.join(root, n)
                if path == out or n == "index.json" and root == MATCH_DIR:
                    continue
                info = zipfile.ZipInfo.from_file(path, os.path.join("matches", os.path.relpath(path, MATCH_DIR)))
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as f:
                    z.writestr(info, f.read())
    return out


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the viewer, and the recorded matches under /replays/."""

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/replays/"):
            rel = os.path.normpath(urllib.parse.unquote(clean[len("/replays/"):]))
            if rel.startswith("..") or os.path.isabs(rel):
                return os.path.join(MATCH_DIR, "index.json")
            return os.path.join(MATCH_DIR, rel)
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def serve(port=8000, open_browser=True):
    """Serve the viewer and block until Ctrl+C."""
    handler = functools.partial(_Handler, directory=VIEWER_DIR)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://localhost:{port}/"
    print(f"\nReplay viewer: {url}   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["zip"]:
        z = make_zip()
        print(f"wrote {z} ({os.path.getsize(z) // 1024 // 1024} MiB)")
    else:
        serve()
