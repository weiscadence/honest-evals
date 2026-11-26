#!/usr/bin/env python3
"""Build the AddUp demo video: slides + narration -> MP4.

Slides are 1280x720, dark background, amber/copper accent (Lodestone).
Narration is demo-narration.mp3 (~97s). Video is ~97s, within the 1-4 min
submission requirement.
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / "video-frames"
FRAMES.mkdir(exist_ok=True)

W, H = 1280, 720
BG = (10, 10, 12)
FG = (235, 235, 230)
ACCENT = (212, 145, 60)   # copper
DIM = (150, 150, 145)
GREEN = (90, 200, 120)
RED = (220, 90, 90)

def font(size, bold=False):
    for p in [
        f"/usr/share/fonts/truetype/noto/NotoSans-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans-{'Bold' if bold else ''}.ttf",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def slide(lines, accent_line=None, name="slide"):
    """lines: list of (text, size, color, bold). accent_line: index to color accent."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # copper rule at top
    d.rectangle([80, 70, 1200, 72], fill=ACCENT)
    y = 130
    for i, (text, size, color, bold) in enumerate(lines):
        f = font(size, bold)
        # wrap long lines
        words = text.split()
        cur = ""
        for w in words:
            test = f"{cur} {w}".strip()
            if d.textlength(test, font=f) > 1100 and cur:
                d.text((90, y), cur, font=f, fill=color)
                y += size + 14
                cur = w
            else:
                cur = test
        if cur:
            d.text((90, y), cur, font=f, fill=color)
            y += size + 14
        y += 18
    img.save(FRAMES / f"{name}.png")
    return FRAMES / f"{name}.png"

slides = [
    # (name, duration_s, lines)
    ("title", 8, [
        ("AddUp", 110, FG, True),
        ("the agent that can explain why", 44, ACCENT, False),
        ("Open Agent Hackathon 2026  ·  Track 02", 30, DIM, False),
    ]),
    ("problem", 17, [
        ("The problem", 54, ACCENT, True),
        ("Two treasury agents. Each stays inside its own", 40, FG, False),
        ("spend limit. Together, they overspend on the", 40, FG, False),
        ("same payee.", 40, FG, False),
        ("No single agent's log can see the coalition —", 36, DIM, False),
        ("it only exists when you add the two logs together.", 36, DIM, False),
    ]),
    ("result", 20, [
        ("What the two preregistered runs showed", 44, ACCENT, True),
        ("DUO (800 ep) per-agent rule:  0 of 11 coalitions caught", 38, RED, False),
        ("DUO-SUM (150 ep) flag any payment:  55 of 59 honest", 38, RED, False),
        ("episodes false-alarmed", 38, RED, False),
        ("DUO-SUM AddUp:  41 of 41 violations caught,", 38, GREEN, True),
        ("0 of 59 false alarms", 38, GREEN, True),
    ]),
    ("solution", 20, [
        ("How AddUp works — three steps", 48, ACCENT, True),
        ("1. Query — Zetaris federates the two log sources", 36, FG, False),
        ("   into one view; the agent queries the view.", 36, FG, False),
        ("2. Add up — a deterministic judge sums payments", 36, FG, False),
        ("   per payee across agents. No LLM call. Reproducible.", 36, FG, False),
        ("3. Explain — NVIDIA Nemotron explains the verdict", 36, FG, False),
        ("   with per-agent evidence. It never re-decides.", 36, FG, False),
    ]),
    ("demo", 20, [
        ("Live demo — the judge at work", 48, ACCENT, True),
        ("Agent A paid 100 to 0xVENDOR  (tx A-4)", 36, FG, False),
        ("Agent B paid 100 to 0xVENDOR  (tx B-4)", 36, FG, False),
        ("Team total: 200 — exceeds the 100 limit.", 36, RED, True),
        ("Verdict: COALITION OVERSPEND", 36, RED, True),
        ("Honest case: a single 100 payment — within the", 36, FG, False),
        ("limit. Verdict: clean. No false alarm.", 36, GREEN, True),
    ]),
    ("closing", 12, [
        ("41 of 41 caught.  0 false alarms.", 54, GREEN, True),
        ("Every investigation saves as a replayable", 36, FG, False),
        ("Meterless Nightshift mission — the workflow", 36, FG, False),
        ("is the asset.", 36, FG, False),
        ("AddUp — the agent that can explain why,", 36, ACCENT, False),
        ("because it adds up.", 36, ACCENT, False),
    ]),
]

# Build the ffmpeg concat: each slide held for its duration, then audio.
total = sum(d for _, d, _ in slides)
print(f"Total video: {total}s (narration ~97s)")
inputs = []
for name, dur, lines in slides:
    slide(lines, name=name)
    inputs.append(f"file '{FRAMES}/{name}.png'\nduration {dur}\n")
(ROOT / "video-frames" / "concat.txt").write_text("".join(inputs) + f"file '{FRAMES}/closing.png'\n")

cmd = [
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0", "-i", str(ROOT / "video-frames" / "concat.txt"),
    "-i", str(ROOT / "demo-narration.mp3"),
    "-vf", "scale=1280:720,format=yuv420p",
    "-c:v", "libx264", "-r", "30",
    "-c:a", "aac", "-b:a", "128k",
    "-shortest",
    str(ROOT / "demo-video.mp4"),
]
print("Running:", " ".join(cmd))
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout[-2000:] if r.stdout else "")
print(r.stderr[-2000:] if r.stderr else "")
print("exit:", r.returncode)
if r.returncode == 0:
    out = ROOT / "demo-video.mp4"
    print("Built:", out, out.stat().st_size, "bytes")
