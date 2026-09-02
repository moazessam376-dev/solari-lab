"""Turn a VHS frame dump into a cinematic recording.

VHS records a fixed terminal. This script reads the PNG frame dump (`Output
some/dir/` in the tape), tracks the content and the caret on every frame, and
renders a camera with three moves per command:

  typing      tight on the prompt, panning right with the caret
  generating  tight on the newest lines, panning down as output grows
  done        easing out to the whole result and holding so it can be read

Idle waits are compressed, every `clear` is a cut through black, and each
command's result is held on screen for at least `--hold` seconds.

    python vhs/cinematic.py ../.frames_lab docs/solab.gif --mp4 docs/solab.mp4

Needs Pillow, numpy and ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

OUT_W, OUT_H = 1180, 540
ASPECT = OUT_W / OUT_H
GIF_W = 800
GIF_FPS = 10
CHANGE_PX = 1200


def load_pairs(frames_dir: Path) -> list[tuple[Path, Path | None]]:
    text = sorted(frames_dir.glob("frame-text-*.png"))
    cursor = {p.name.replace("frame-cursor-", ""): p for p in frames_dir.glob("frame-cursor-*.png")}
    return [(t, cursor.get(t.name.replace("frame-text-", ""))) for t in text]


def load(text: Path, cursor: Path | None) -> tuple[np.ndarray, tuple[int, int] | None]:
    """RGB frame with the cursor composited, plus the caret centre if visible."""
    im = Image.open(text).convert("RGBA")
    caret = None
    if cursor is not None:
        c = Image.open(cursor).convert("RGBA")
        if c.size == im.size:
            a = np.asarray(c.getchannel("A"))
            ys, xs = np.where(a > 0)
            if len(xs):
                caret = (int(xs.mean()), int(ys.mean()))
            im = Image.alpha_composite(im, c)
    return np.asarray(im.convert("RGB")), caret


def content_bbox(rgb: np.ndarray, bg: np.ndarray, thresh: int = 28) -> tuple[int, int, int, int] | None:
    diff = np.abs(rgb.astype(np.int16) - bg[None, None, :].astype(np.int16)).max(axis=2)
    mask = diff > thresh
    row_fill = mask.mean(axis=1)
    rows = np.where(row_fill > 0)[0]
    if len(rows) == 0:
        return None
    text_rows = row_fill < 0.6  # full-width rules count for height, not width
    cols = np.where((mask & text_rows[:, None]).any(axis=0))[0]
    if len(cols) == 0:
        cols = np.where(mask.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def render(frames_dir: Path, gif: Path, mp4: Path | None, fps: int, hold: float, idle_hold: float) -> None:
    pairs = load_pairs(frames_dir)
    if not pairs:
        sys.exit(f"no frame-text-*.png in {frames_dir}")
    pairs = pairs[:: max(1, round(60 / fps))]
    first, _ = load(*pairs[0])
    H, W = first.shape[:2]
    bg = np.median(first.reshape(-1, 3), axis=0).astype(np.uint8)
    pad_x, pad_y = int(W * 0.025), int(H * 0.04)
    line_h = H / 34
    tight_h = line_h * 7
    type_h = line_h * 5  # typing window: tighter, so the pan with the caret is visible
    out_dir = Path(tempfile.mkdtemp(prefix="cinematic-"))
    n_out = 0
    cam: np.ndarray | None = None
    prev: np.ndarray | None = None
    idle = 0
    since_change = 0
    mode = "typing"
    fade = 0
    last_bottom = 0
    last_frame: Image.Image | None = None
    dwell = 0
    hold_frames = int(hold * fps)

    def emit(frame: Image.Image) -> None:
        nonlocal n_out
        frame.save(out_dir / f"{n_out:05d}.png")
        n_out += 1

    for text, cursor in pairs:
        rgb, caret = load(text, cursor)
        changed = W * H if prev is None else int((np.abs(rgb.astype(np.int16) - prev.astype(np.int16)).max(axis=2) > 28).sum())
        prev = rgb
        bbox = content_bbox(rgb, bg)
        bottom = bbox[3] if bbox else 0
        top_c = bbox[1] if bbox else 0

        cleared = bbox is not None and last_bottom > H * 0.25 and bottom < last_bottom * 0.35
        if cleared:
            if last_frame is not None:
                for _ in range(max(0, hold_frames - dwell)):
                    emit(last_frame)
            fade = 6
            mode = "typing"
            dwell = 0
            cam = None
            last_bottom = 0
        last_bottom = max(last_bottom, bottom)

        if changed > CHANGE_PX:
            since_change = 0
            if mode == "typing" and bbox is not None and (bottom - top_c) > line_h * 2.5:
                mode = "generating"
            elif mode == "done" and changed > CHANGE_PX * 3:
                mode = "generating"
        else:
            since_change += 1
            if mode == "generating" and since_change > fps * 0.6:
                mode = "done"

        if changed <= CHANGE_PX:
            idle += 1
            if idle > idle_hold * fps and idle % 6 != 0 and not (mode == "done" and dwell < hold_frames):
                continue
        else:
            idle = 0

        if bbox is None:
            tw = tight_h * ASPECT
            target = np.array([tw / 2, tight_h / 2, tw, tight_h])
        else:
            x0, y0, x1, y1 = bbox
            if mode == "typing":
                th = type_h
                tw = th * ASPECT
                if caret:
                    cx_caret, cy_line = caret
                    left_t = cx_caret - tw * 0.55  # the caret leads; the frame slides with every character
                else:
                    cx_caret, cy_line = x1, y1
                    left_t = x0 - pad_x  # caret gone (Enter): settle on the start of the line
                left_t = max(0.0, min(left_t, W - tw))
                target = np.array([left_t + tw / 2, cy_line, tw, th])
            elif mode == "generating":
                th = tight_h * 1.15
                tw = max(th * ASPECT, (x1 - x0) + 2 * pad_x)
                th = tw / ASPECT
                tx = max(tw / 2, min(W - tw / 2, max(0, x0 - pad_x) + tw / 2))
                target = np.array([tx, y1 - th * 0.30, tw, th])
            else:
                cw = (x1 - x0) + 2 * pad_x
                ch = (y1 - y0) + 2 * pad_y
                th = max(tight_h, ch)
                tw = max(th * ASPECT, cw)
                th = tw / ASPECT
                if th > H:
                    th, tw = H, H * ASPECT
                tx = max(tw / 2, min(W - tw / 2, max(0, x0 - pad_x) + tw / 2))
                target = np.array([tx, (y0 + y1) / 2, tw, th])

        if cam is None:
            cam = target.copy()
        k = {"typing": 0.22, "generating": 0.12, "done": 0.05}[mode]
        cam += (target - cam) * k
        cx, cy, cw_, ch_ = cam
        cw_i, ch_i = int(min(cw_, W)), int(min(ch_, H))
        left = int(max(0, min(W - cw_i, cx - cw_i / 2)))
        if bbox is not None and mode != "typing":
            left = min(left, max(0, bbox[0] - pad_x // 2))
        top = int(cy - ch_i / 2)
        canvas = np.empty((ch_i, cw_i, 3), dtype=np.uint8)
        canvas[:] = bg
        sy0, sy1 = max(0, top), min(H, top + ch_i)
        if sy1 > sy0:
            canvas[sy0 - top : sy0 - top + (sy1 - sy0)] = rgb[sy0:sy1, left : left + cw_i]
        frame = Image.fromarray(canvas).resize((OUT_W, OUT_H), Image.LANCZOS)
        if fade > 0:
            frame = Image.blend(frame, Image.new("RGB", frame.size, tuple(int(v) for v in bg)), min(1.0, fade / 4))
            fade -= 1
        emit(frame)
        last_frame = frame
        dwell = dwell + 1 if mode == "done" else 0

    if last_frame is not None:
        for _ in range(max(hold_frames, hold_frames - dwell)):
            emit(last_frame)
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
    ap.add_argument("--hold", type=float, default=2.5, help="seconds each finished result stays on screen")
    ap.add_argument("--idle-hold", type=float, default=1.0)
    a = ap.parse_args()
    render(a.frames_dir, a.gif, a.mp4, a.fps, a.hold, a.idle_hold)
