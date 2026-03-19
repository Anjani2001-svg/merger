#!/usr/bin/env python3
"""
SLC Video Merger – Streamlit Edition
All text is rendered by Pillow (no FFmpeg drawtext = no escaping bugs).
FFmpeg only does: overlay PNG on video, normalise, transitions, concatenate.

Watermark removal is resolution-aware:
  • 1920×1080 source → tight coordinates measured from that native resolution
  • 1280×720  source → tight coordinates scaled 1.5× after normalise()
  • Other resolutions → falls back to the 1920×1080 set

Logo overlay uses scale=-1:LOGO_H so the natural aspect ratio is always
preserved — no stretching or squashing regardless of the PNG dimensions.
The logo is anchored to the bottom-right corner (W-w-pad : H-h-pad).
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import streamlit as st

# ────────────────────────────── CONFIG ──────────────────────────────────
st.set_page_config(page_title="SLC Video Merger", page_icon="🎬", layout="wide")

BASE_DIR  = Path(__file__).parent
INTRO_TPL = BASE_DIR / "assets" / "intro_template.mp4"
SLC_LOGO  = BASE_DIR / "assets" / "slc_logo.png"

# ── Per-resolution watermark cover boxes (in 1920×1080 space) ───────────
# Only the white drawboxes are resolution-specific.
# The logo overlay is resolution-independent (see LOGO_* below).

WM_COORDS = {
    # 1920×1080 native source — measured directly from video frames
    (1920, 1080): dict(
        top_x=810,  top_y=148, top_w=280, top_h=55,
    ),
    # 1280×720 source — all values scaled 1.5× by normalise()
    (1280, 720): dict(
        top_x=806,  top_y=68,  top_w=285, top_h=45,
    ),
}

WM_FALLBACK = WM_COORDS[(1920, 1080)]

# ── Logo overlay (resolution-independent) ───────────────────────────────
# Scaled to LOGO_H height with WIDTH CALCULATED AUTOMATICALLY by FFmpeg
# using scale=-1:LOGO_H — this preserves the natural aspect ratio of the
# PNG so the logo never looks fat or stretched.
# Anchored to bottom-right: overlay=x=W-w-LOGO_PAD:y=H-h-LOGO_PAD
LOGO_H   = 52    # pixels tall in 1920×1080 output — adjust to taste
LOGO_PAD = 20    # pixels from right and bottom edges

# ── Top-centre watermark (title slide only) ─────────────────────────────
WM_TOP_DURATION = 20   # seconds

# ── End-card centre cover (same for all resolutions) ────────────────────
WM_EC_X = 448
WM_EC_Y = 310
WM_EC_W = 1024
WM_EC_H = 420


def _font(name):
    candidates = [
        str(BASE_DIR / "fonts" / name),
        f"/usr/share/fonts/truetype/google-fonts/{name}",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


BOLD   = _font("Poppins-Bold.ttf")
MEDIUM = _font("Poppins-Medium.ttf")
TEAL   = (96, 204, 190)
WHITE  = (255, 255, 255)


# ──────────────────── PILLOW: RENDER TEXT AS PNG ───────────────────────
def _ft(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def render_intro_overlay(course, unit_num, unit_title, W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = W - 200

    csz = 52
    cfn = _ft(BOLD, csz)
    while csz > 28:
        bb = draw.textbbox((0, 0), course, font=cfn)
        if bb[2] - bb[0] <= pad:
            break
        csz -= 2
        cfn  = _ft(BOLD, csz)
    c_asc, c_desc = cfn.getmetrics()
    c_h = c_asc + c_desc

    ufn  = _ft(BOLD, 28)
    utxt = unit_num.upper()
    bb   = draw.textbbox((0, 0), utxt, font=ufn)
    badge_tw = bb[2] - bb[0]
    badge_w  = badge_tw + 70
    badge_h  = 56

    has_title = bool(unit_title and unit_title.strip())
    title_h   = 0
    if has_title:
        tsz = 30
        tfn = _ft(MEDIUM, tsz)
        while tsz > 20:
            bb = draw.textbbox((0, 0), unit_title, font=tfn)
            if bb[2] - bb[0] <= pad:
                break
            tsz -= 2
            tfn  = _ft(MEDIUM, tsz)
        t_asc, t_desc = tfn.getmetrics()
        title_h = t_asc + t_desc

    gap1    = 45
    gap2    = 25
    block_h = c_h + gap1 + badge_h
    if has_title:
        block_h += gap2 + title_h

    center_y = (H // 2) - 60
    start_y  = center_y - block_h // 2

    draw.text((W // 2, start_y + c_h // 2), course,
              fill=WHITE, font=cfn, anchor="mm")

    badge_x = (W - badge_w) // 2
    badge_y = start_y + c_h + gap1
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=14, fill=TEAL + (230,))
    draw.text((badge_x + badge_w // 2, badge_y + badge_h // 2),
              utxt, fill=WHITE, font=ufn, anchor="mm")

    if has_title:
        title_y = badge_y + badge_h + gap2
        draw.text((W // 2, title_y + title_h // 2), unit_title,
                  fill=WHITE, font=tfn, anchor="mm")

    return img


def render_end_overlay(W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fn   = _ft(BOLD, 42)
    bb   = draw.textbbox((0, 0), "END", font=fn)
    tw   = bb[2] - bb[0]
    bw, bh = tw + 90, 72
    bx, by = (W - bw) // 2, (H - bh) // 2 - 20

    draw.rounded_rectangle(
        [bx, by, bx + bw, by + bh],
        radius=16, fill=TEAL + (230,))
    draw.text((bx + bw // 2, by + bh // 2), "END",
              fill=WHITE, font=fn, anchor="mm")
    return img


# ────────────────────── FFMPEG HELPERS ─────────────────────────────────
def _ff(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err   = r.stderr.strip().split("\n")
        short = "\n".join(err[-6:]) if len(err) > 6 else r.stderr
        raise RuntimeError(short)
    return r


def _probe_resolution(path):
    """Return (width, height) of the first video stream."""
    r = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        str(path),
    ], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return (1920, 1080)
    parts = r.stdout.strip().split(",")
    try:
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return (1920, 1080)


def make_intro(course, unit_num, unit_title, tmp):
    png = str(tmp / "intro_overlay.png")
    out = str(tmp / "intro.mp4")
    render_intro_overlay(course, unit_num, unit_title).save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,300*pow(1-t/0.8\\,2)\\,0)"
    _ff([
        "ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
        "-filter_complex",
        f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p", out,
    ], timeout=60)
    return Path(out)


def make_outro(tmp):
    png = str(tmp / "end_overlay.png")
    out = str(tmp / "outro.mp4")
    render_end_overlay().save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,250*pow(1-t/0.8\\,2)\\,0)"
    _ff([
        "ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
        "-filter_complex",
        f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p", out,
    ], timeout=60)
    return Path(out)


def _probe_duration(path):
    r = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Could not read duration for {path}")
    return float(r.stdout.strip())


def _has_audio(path):
    r = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0",
        str(path),
    ], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _detect_end_card_start(path):
    """Scan the last 20 s for the first near-pure-white frame (end card)."""
    total     = _probe_duration(path)
    scan_from = max(0.0, total - 20.0)
    fallback  = max(0.0, total - 9.0)
    step      = 0.5

    t = scan_from
    while t < total - 1.0:
        fd, tmp_frame = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", tmp_frame],
                capture_output=True, timeout=8,
            )
            img = Image.open(tmp_frame)
            a   = np.array(img)
            bright_frac = (a.mean(axis=2) > 230).sum() / (a.shape[0] * a.shape[1])
            if bright_frac > 0.95:
                return t
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_frame)
            except OSError:
                pass
        t += step

    return fallback


def normalise(inp, out):
    has_audio = _has_audio(inp)
    cmd = ["ffmpeg", "-y", "-i", str(inp)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += [
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p",
    ]
    if not has_audio:
        cmd += ["-shortest"]
    cmd += [str(out)]
    _ff(cmd)
    return Path(out)


def remove_notebooklm_watermark(inp, out, src_resolution, progress_cb=None):
    """
    Cover all NotebookLM branding in one FFmpeg pass.

    Zone 1 — Top-centre (title slide, first WM_TOP_DURATION seconds only):
        Tight white box sized exactly to the badge for each source resolution.

    Zone 2 — Bottom-right badge (all content slides, every frame):
        Tight white box + SLC logo.
        Logo uses scale=-1:LOGO_H so the natural aspect ratio is preserved.
        Anchored to bottom-right corner via overlay=x=W-w-pad:y=H-h-pad.

    Zone 3 — End-card full-screen (dynamically detected start time):
        White box covers the centred notebooklm.google.com icon + URL.
    """
    inp_str = str(inp)
    out_str = str(out)

    coords = WM_COORDS.get(src_resolution, WM_FALLBACK)
    tx  = coords["top_x"]; ty  = coords["top_y"]
    tw  = coords["top_w"]; th  = coords["top_h"]

    if progress_cb:
        progress_cb("Detecting end-card start time…")

    ecs       = _detect_end_card_start(inp_str)
    enable_ec = f"gte(t\\,{ecs:.2f})"

    WM_TOP = (
        f"drawbox=x={tx}:y={ty}:w={tw}:h={th}"
        f":color=white@1:t=fill:enable='lte(t\\,{WM_TOP_DURATION})'"
    )

    # ── WM_BR: sized to wrap the logo exactly ─────────────────────────
    # Logo is anchored at y=H-LOGO_H-LOGO_PAD, x=W-logo_w-LOGO_PAD.
    # SLC logo natural ratio ≈ 3.5:1, so estimated width = LOGO_H * 3.5.
    # White box adds BOX_INNER_PAD on all sides so logo sits inside it.
    BOX_INNER_PAD = 6
    est_logo_w = int(LOGO_H * 3.5)            # estimated logo width
    box_w      = est_logo_w + BOX_INNER_PAD * 2
    box_h      = LOGO_H     + BOX_INNER_PAD * 2
    box_x      = 1920 - LOGO_PAD - box_w      # right-aligned with logo
    box_y      = 1080 - LOGO_PAD - box_h      # bottom-aligned with logo

    WM_BR = (
        f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
        f":color=white@1:t=fill"
    )
    WM_EC = (
        f"drawbox=x={WM_EC_X}:y={WM_EC_Y}:w={WM_EC_W}:h={WM_EC_H}"
        f":color=white@1:t=fill:enable='{enable_ec}'"
    )

    use_logo = SLC_LOGO.exists() and SLC_LOGO.stat().st_size > 500

    if use_logo:
        # scale=-1:LOGO_H → width auto-calculated to preserve aspect ratio
        # overlay=x=W-w-pad:y=H-h-pad → anchored to bottom-right corner
        filter_complex = (
            f"[0:v]{WM_TOP},{WM_BR},{WM_EC}[cov];"
            f"[1:v]scale=-1:{LOGO_H}[logo];"
            f"[cov][logo]overlay="
            f"x=W-w-{LOGO_PAD}:y=H-h-{LOGO_PAD}"
            f"[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", inp_str, "-i", str(SLC_LOGO),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p",
            out_str,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", inp_str,
            "-vf", f"{WM_TOP},{WM_BR},{WM_EC}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p",
            out_str,
        ]

    _ff(cmd, timeout=600)
    return Path(out)


def add_notebooklm_transition(intro, main, out, duration=1.0, direction="left"):
    transition_map = {
        "left": "wipeleft", "right": "wiperight",
        "up": "wipeup", "down": "wipedown",
    }
    wipe    = transition_map.get(direction, "wipeleft")
    intro_d = _probe_duration(intro)
    half    = max(0.25, min(duration / 2, intro_d - 0.05))
    if half <= 0:
        raise RuntimeError("Intro is too short to apply the transition.")

    color_columns = (
        "color=c=0x7B2CBF:s=1920x1080:r=30,"
        "drawbox=x=0:y=0:w=576:h=1080:color=0x7B2CBF:t=fill,"
        "drawbox=x=576:y=0:w=461:h=1080:color=0x4285F4:t=fill,"
        "drawbox=x=1037:y=0:w=346:h=1080:color=0x7EDFC3:t=fill,"
        "drawbox=x=1383:y=0:w=537:h=1080:color=0xB7E4C7:t=fill"
    )
    _ff([
        "ffmpeg", "-y",
        "-i", str(intro), "-i", str(main),
        "-f", "lavfi", "-t", f"{duration}", "-i", color_columns,
        "-f", "lavfi", "-t", f"{duration}", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p,settb=AVTB[v0];"
        "[1:v]fps=30,format=yuv420p,settb=AVTB[v1];"
        "[2:v]fps=30,format=yuv420p,settb=AVTB[vc];"
        f"[v0][vc]xfade=transition={wipe}:duration={half}:offset={max(intro_d - half, 0):.3f}[vx];"
        f"[vx][v1]xfade=transition={wipe}:duration={half}:offset={intro_d:.3f}[vout];"
        f"[0:a][3:a]acrossfade=d={half}:c1=tri:c2=tri[ax];"
        f"[ax][1:a]acrossfade=d={half}:c1=tri:c2=tri[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p",
        str(out),
    ], timeout=180)
    return Path(out)


def concat(parts, out, tmp):
    lst = tmp / "list.txt"
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{Path(p).resolve()}'\n")
    try:
        _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c", "copy", str(out)])
    except RuntimeError:
        _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(lst),
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
             str(out)])
    return Path(out)


def preview_frame(course, unit_num, unit_title):
    if not INTRO_TPL.exists():
        raise FileNotFoundError(
            f"Intro template not found at: {INTRO_TPL}\n"
            "Make sure assets/intro_template.mp4 is in your repo."
        )
    if INTRO_TPL.stat().st_size < 1000:
        raise ValueError(
            f"Intro template is too small ({INTRO_TPL.stat().st_size} bytes)."
        )
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(INTRO_TPL),
             "-ss", "3", "-vframes", "1", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg frame extract failed:\n{result.stderr[-300:]}")
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 100:
            raise RuntimeError("FFmpeg produced an empty frame.")
        bg = Image.open(tmp_path).convert("RGBA")
        bg.load()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    ovr  = render_intro_overlay(course, unit_num, unit_title)
    comp = Image.alpha_composite(bg, ovr).convert("RGB")
    buf  = BytesIO()
    comp.save(buf, "JPEG", quality=90)
    buf.seek(0)
    return buf


def _check_template():
    if not INTRO_TPL.exists():
        st.error(
            f"❌ **Intro template not found!**\n\n"
            f"Expected: `{INTRO_TPL}`\n\n"
            "Make sure `assets/intro_template.mp4` is committed to your repo."
        )
        st.stop()
    size = INTRO_TPL.stat().st_size
    if size < 10000:
        st.error(
            f"❌ **Intro template appears corrupt!**\n\n"
            f"File size: {size} bytes (expected ~950 KB)"
        )
        st.stop()


_check_template()


# ──────────────────────── CUSTOM CSS ──────────────────────────────────
st.markdown("""
<style>
.stApp{background:linear-gradient(135deg,#0a2a3c 0%,#0d3b54 30%,#0f4c6e 60%,#1a3a5c 100%)}
header[data-testid="stHeader"]{background:rgba(10,42,60,.85);backdrop-filter:blur(10px)}
.stButton>button[kind="primary"],.stDownloadButton>button{background:#60ccbe!important;color:#0a2a3c!important;border:none!important;border-radius:12px!important;font-weight:600!important;padding:.6rem 2rem!important}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button:hover{background:#4dbcad!important;box-shadow:0 4px 20px rgba(96,204,190,.3)!important}
.stTextInput>div>div>input{background:rgba(255,255,255,.08)!important;border:1px solid rgba(255,255,255,.15)!important;border-radius:10px!important;color:#fff!important}
.stTextInput>div>div>input:focus{border-color:#60ccbe!important;box-shadow:0 0 0 3px rgba(96,204,190,.15)!important}
section[data-testid="stFileUploader"]{border:2px dashed rgba(96,204,190,.4)!important;border-radius:14px!important;background:rgba(96,204,190,.03)!important}
.fb{display:inline-block;background:rgba(96,204,190,.12);border:1px solid rgba(96,204,190,.3);padding:6px 18px;border-radius:8px;font-size:14px;color:rgba(255,255,255,.85)}
.fa{display:inline-block;color:#60ccbe;font-size:18px;margin:0 6px}
.sn{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#60ccbe;color:#0a2a3c;font-weight:700;font-size:13px;margin-right:10px}
.st{color:#60ccbe;font-size:15px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px}
.ok{text-align:center;padding:24px;background:rgba(96,204,190,.08);border:1px solid rgba(96,204,190,.25);border-radius:16px;margin:16px 0}
.ok h3{color:#60ccbe;margin-bottom:4px}
hr{border-color:rgba(96,204,190,.15)!important}
video{border-radius:12px;border:1px solid rgba(96,204,190,.2)}
</style>
""", unsafe_allow_html=True)


# ──────────────────────── LAYOUT ──────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
  <h1 style="margin:0;font-size:28px">🎬 SLC Video Merger</h1>
  <span style="background:#60ccbe;color:#0a2a3c;font-size:11px;font-weight:700;
        padding:3px 12px;border-radius:20px;text-transform:uppercase">Fast</span>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="text-align:center;margin:8px 0 24px">
  <span class="fb">🎬 Custom Intro</span><span class="fa">→</span>
  <span class="fb">🟪🟦🟩⬜ 4-Colour Transition</span><span class="fa">→</span>
  <span class="fb">📹 NotebookLM Video</span><span class="fa">→</span>
  <span class="fb">🔚 Outro</span>
</div>
""", unsafe_allow_html=True)

# ── 1  INTRO ──────────────────────────────────────────────────────────
st.markdown(
    '<div><span class="sn">1</span><span class="st">Intro Customisation</span></div>',
    unsafe_allow_html=True,
)
course_name = st.text_input(
    "Course Name",
    placeholder="e.g. Level 3 Diploma in Sports Development (RQF)",
)
c1, c2 = st.columns(2)
with c1:
    unit_number = st.text_input(
        "Unit / Chapter Number",
        placeholder="e.g. UNIT 03 | CHAPTER 06",
    )
if st.button("👁 Preview Intro", type="secondary"):
    if course_name and unit_number:
        with st.spinner("Rendering…"):
            st.image(
                preview_frame(course_name, unit_number, ""),
                caption="Intro Preview",
                use_container_width=True,
            )
    else:
        st.warning("Enter course name and unit number first.")

st.markdown("---")

# ── 2  UPLOAD NOTEBOOKLM VIDEO ────────────────────────────────────────
st.markdown(
    '<div><span class="sn">2</span><span class="st">Upload NotebookLM Video</span></div>',
    unsafe_allow_html=True,
)
vid = st.file_uploader(
    "Upload your NotebookLM video",
    type=["mp4", "mov", "webm", "avi", "mkv"],
    help="MP4 / MOV / WebM — up to 500 MB",
)
if vid:
    st.success(f"📁 **{vid.name}** — {vid.size / 1048576:.1f} MB")

st.markdown("---")

# ── 2b  SLC LOGO UPLOAD ───────────────────────────────────────────────
st.markdown(
    '<div><span class="sn">✦</span>'
    '<span class="st">SLC Logo (replaces NotebookLM badge)</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p style="font-size:13px;color:rgba(255,255,255,.5);margin-bottom:10px">'
    'Upload the SLC logo PNG. Appears bottom-right on every slide at the correct '
    'size with the natural proportions preserved.</p>',
    unsafe_allow_html=True,
)
logo_upload = st.file_uploader(
    "SLC Logo PNG", type=["png"], help="Transparent PNG preferred.",
)
if logo_upload is not None:
    SLC_LOGO.parent.mkdir(parents=True, exist_ok=True)
    SLC_LOGO.write_bytes(logo_upload.getvalue())
    st.success("✅ Logo saved.")
elif SLC_LOGO.exists():
    st.info("ℹ️ Using existing logo at `assets/slc_logo.png`.")
else:
    st.warning("⚠️ No logo uploaded — watermark zones will be covered with white only.")

st.markdown("---")

# ── 3  MERGE ──────────────────────────────────────────────────────────
st.markdown(
    '<div><span class="sn">3</span><span class="st">Generate Final Video</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p style="font-size:13px;color:rgba(255,255,255,.5);margin-bottom:16px">'
    'Merges custom intro + 4-colour transition + NotebookLM video '
    '(all watermarks replaced) + standard outro.</p>',
    unsafe_allow_html=True,
)

if st.button("🎬 Merge & Download", type="primary", use_container_width=True):
    if not course_name:
        st.error("Enter a course name.")
        st.stop()
    if not unit_number:
        st.error("Enter a unit number.")
        st.stop()
    if not vid:
        st.error("Upload a video.")
        st.stop()

    t0 = time.time()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bar = st.progress(0, "Starting…")
        msg = st.empty()

        try:
            raw = tmp / "raw.mp4"
            raw.write_bytes(vid.getvalue())

            # Detect source resolution BEFORE normalising
            src_res = _probe_resolution(str(raw))

            msg.info("⏳ **Step 1 / 4** — Building intro, outro and normalising video…")
            bar.progress(10, "Processing in parallel…")

            results = {}
            errors  = {}

            def _job(name, fn, *args):
                try:
                    results[name] = fn(*args)
                except Exception as e:
                    errors[name] = e

            with ThreadPoolExecutor(max_workers=3) as pool:
                pool.submit(_job, "intro", make_intro, course_name, unit_number, "", tmp)
                pool.submit(_job, "outro", make_outro, tmp)
                pool.submit(_job, "norm",  normalise,  raw, tmp / "norm.mp4")

            if errors:
                raise RuntimeError(
                    "; ".join(f"{k}: {v}" for k, v in errors.items())
                )

            msg.info(
                f"⏳ **Step 2 / 4** — Replacing NotebookLM branding "
                f"({src_res[0]}×{src_res[1]} source)…"
            )
            bar.progress(40, "Replacing watermarks…")

            norm_clean = remove_notebooklm_watermark(
                results["norm"],
                tmp / "norm_clean.mp4",
                src_resolution=src_res,
                progress_cb=lambda s: msg.info(f"⏳ **Step 2 / 4** — {s}"),
            )

            msg.info("⏳ **Step 3 / 4** — Adding 4-colour transition…")
            bar.progress(65, "Creating transition…")

            main_with_transition = add_notebooklm_transition(
                results["intro"], norm_clean, tmp / "intro_and_main.mp4",
            )

            msg.info("⏳ **Step 4 / 4** — Merging final segments…")
            bar.progress(85, "Merging…")

            final = concat(
                [main_with_transition, results["outro"]],
                tmp / "final.mp4", tmp,
            )

            bar.progress(100, "Done!")
            secs = time.time() - t0
            data = final.read_bytes()
            mb   = len(data) / 1048576

            msg.empty()
            bar.empty()

            st.markdown(f"""
            <div class="ok">
                <div style="font-size:48px;margin-bottom:8px">✅</div>
                <h3>Video Ready!</h3>
                <p style="color:rgba(255,255,255,.5);font-size:13px">
                    Processed in {secs:.1f}s &nbsp;•&nbsp; {mb:.1f} MB
                </p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(
                '<div style="margin:16px 0"><span class="sn">▶</span>'
                '<span class="st">Preview</span></div>',
                unsafe_allow_html=True,
            )
            st.video(data, format="video/mp4")

            safec    = course_name[:30].replace(" ", "_")
            safeu    = unit_number.replace(" ", "_").replace("|", "")
            filename = f"SLC_Video_{safec}_{safeu}.mp4"

            st.download_button(
                "⬇ Download Final Video", data, filename,
                "video/mp4", use_container_width=True,
            )

        except Exception as e:
            bar.empty()
            msg.empty()
            st.error(f"**Processing failed:**\n\n```\n{e}\n```")
