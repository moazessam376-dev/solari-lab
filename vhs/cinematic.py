"""Turn a VHS frame dump into a cinematic recording.

VHS records a fixed terminal; most of the frame is empty while a command types
and the interesting part moves as output grows. This script reads the PNG frame
dump (`Output some/dir/` in the tape), finds the content on every frame, and
renders a smoothed camera that stays tight on the command while it types, eases
out as output appears, pans down to follow it, compresses idle waits, and cuts
through black on every `clear`.

    python vhs/cinematic.py ../.frames_lab docs/solab.gif --mp4 docs/solab.mp4

Needs Pillow, numpy and ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

OUT_W, OUT_H = 1180, 540  # wide frame: terminal lines are wide, so the camera can get tight
ASPECT = OUT_W / OUT_H
GIF_W = 800
GIF_FPS = 10


def load_pairs(frames_dir: Path) -> list[tuple[Path, Path | None]]:
    text = sorted(frames_dir.glob("frame-text-*.png"))
    cursor = {p.name.replace("frame-cursor-", ""): p for p in frames_dir.glob("frame-cursor-*.png")}
    return [(t, cursor.get(t.name.replace("frame-text-", ""))) for t in text]


def composite(text: Path, cursor: Path | None) -> np.ndarray:
    im = Image.open(text).convert("RGBA")
    if cursor is not None:
        c = Image.open(cursor).convert("RGBA")
        if c.size == im.size:
            im = Image.alpha_composite(im, c)
    return np.asarray(im.convert("RGB"))


def content_bbox(rgb: np.ndarray, bg: np.ndarray, thresh: int = 28) -> tuple[int, int, int, int] | None:
    """Bounding box of everything that is not background. Full-width rule lines
    count for height but not for width, so a heavy rule does not pin the zoom."""
    diff = np.abs(rgb.astype(np.int16) - bg[None, None, :].astype(np.int16)).max(axis=2)
    mask = diff > thresh
    row_fill = mask.mean(axis=1)
    rows = np.where(row_fill > 0)[0]
    if len(rows) == 0:
        return None
    text_rows = row_fill < 0.6  # rows that are not a rule
    cols = np.where((mask & text_rows[:, None]).any(axis=0))[0]
    if len(cols) == 0:
        cols = np.where(mask.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def render(frames_dir: Path, gif: Path, mp4: Path | None, fps: int, speed: float, idle_hold: float) -> None:
    pairs = load_pairs(frames_dir)
    if not pairs:
        sys.exit(f"no frame-text-*.png in {frames_dir}")
    src_fps = 60
    step = max(1, round(src_fps / fps))
    pairs = pairs[::step]
    first = composite(*pairs[0])
    H, W = first.shape[:2]
    bg = np.median(first.reshape(-1, 3), axis=0).astype(np.uint8)
    pad_x, pad_y = int(W * 0.03), int(H * 0.05)
    min_h = H * 0.22  # tightest zoom
    cam = np.array([W / 2, H / 2, W, H], dtype=float)  # cx, cy, w, h
    prev: np.ndarray | None = None
    idle_frames = 0
    out_dir = Path(tempfile.mkdtemp(prefix="cinematic-"))
    n_out = 0
    fade = 0
    bbox_prev = None
    for text, cursor in pairs:
        rgb = composite(text, cursor)
        # idle compression: drop frames when almost nothing changes for a while
        if prev is not None:
            changed = int((np.abs(rgb.astype(np.int16) - prev.astype(np.int16)).max(axis=2) > 28).sum())
            if changed < 1200:
                idle_frames += 1
                if idle_frames > idle_hold * fps and idle_frames % 6 != 0:
                    prev = rgb
                    continue
            else:
                idle_frames = 0
        prev = rgb
        bbox = content_bbox(rgb, bg)
        cleared = bbox_prev is not None and bbox is not None and (bbox[3] - bbox[1]) < (bbox_prev[3] - bbox_prev[1]) * 0.35 and bbox_prev[3] - bbox_prev[1] > H * 0.3
        if cleared:
            fade = 6  # cut through black
        bbox_prev = bbox or bbox_prev
        if bbox is None:
            tw = H * 0.22 * ASPECT
            tx, ty, tw, th = tw / 2, H * 0.11, tw, H * 0.22
        else:
            x0, y0, x1, y1 = bbox
            cw = (x1 - x0) + 2 * pad_x
            ch = (y1 - y0) + 2 * pad_y
            th = max(min_h, ch)
            tw = max(th * ASPECT, cw)
            th = tw / ASPECT
            if th > H:
                th, tw = H, H * ASPECT
            tx = max(tw / 2, min(W - tw / 2, max(0, x0 - pad_x) + tw / 2))  # left-anchored
            ty = (y0 + y1) / 2  # may sit above the frame: the crop is letterboxed with background
        target = np.array([tx, ty, tw, th])
        k = np.array([0.10, 0.10, 0.06, 0.06]) * speed
        cam += (target - cam) * k
        cx, cy, cw_, ch_ = cam
        cw_ = min(cw_, W)
        ch_ = min(ch_, H)
        left = int(max(0, min(W - cw_, cx - cw_ / 2)))
        if bbox is not None:
            left = min(left, max(0, bbox[0] - pad_x // 2))  # never clip the first character while easing
        top = int(min(H - ch_, cy - ch_ / 2))  # negative = letterbox above
        cw_i, ch_i = int(cw_), int(ch_)
        canvas = np.empty((ch_i, cw_i, 3), dtype=np.uint8)
        canvas[:] = bg
        sy0, sy1 = max(0, top), min(H, top + ch_i)
        dy0 = sy0 - top
        canvas[dy0 : dy0 + (sy1 - sy0)] = rgb[sy0:sy1, left : left + cw_i]
        frame = Image.fromarray(canvas).resize((OUT_W, OUT_H), Image.LANCZOS)
        if fade > 0:
            dark = Image.new("RGB", frame.size, tuple(int(v) for v in bg))
            frame = Image.blend(frame, dark, min(1.0, fade / 4))
            fade -= 1
        frame.save(out_dir / f"{n_out:05d}.png")
        n_out += 1
    if n_out == 0:
        sys.exit("nothing rendered")
    # hold the last frame for a beat
    last = out_dir / f"{n_out - 1:05d}.png"
    for _ in range(fps * 2):
        shutil.copy(last, out_dir / f"{n_out:05d}.png")
        n_out += 1
    seq = str(out_dir / "%05d.png")
    if mp4:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", seq, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(mp4)], check=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", seq, "-vf",
         f"fps={GIF_FPS},scale={GIF_W}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
         "-loop", "0", str(gif)],
        check=True,
    )
    shutil.rmtree(out_dir, ignore_errors=True)
    print(f"rendered {n_out} frames at {fps} fps -> {gif}" + (f", {mp4}" if mp4 else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir", type=Path)
    ap.add_argument("gif", type=Path)
    ap.add_argument("--mp4", type=Path)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--speed", type=float, default=1.0, help="camera easing multiplier")
    ap.add_argument("--idle-hold", type=float, default=1.2, help="seconds of idle to keep before compressing")
    a = ap.parse_args()
    if os.environ.get("NO_COLOR"):
        pass
    render(a.frames_dir, a.gif, a.mp4, a.fps, a.speed, a.idle_hold)
