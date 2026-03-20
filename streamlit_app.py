#!/usr/bin/env python3
"""
SLC Video Merger – Streamlit Edition
All text is rendered by Pillow (no FFmpeg drawtext = no escaping bugs).
FFmpeg only does: overlay PNG on video, normalise, transitions, concatenate.

Watermark removal:
  Zone 2 — Bottom-right badge (all content slides, always on)
            Rounded white box + SLC logo centred inside
  Zone 3 — End-card full-screen (dynamically detected)
            Rounded white box
"""

import os, subprocess, tempfile, time
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import streamlit as st

st.set_page_config(page_title="SLC Video Merger", page_icon="🎬", layout="wide")

BASE_DIR  = Path(__file__).parent
INTRO_TPL = BASE_DIR / "assets" / "intro_template.mp4"
SLC_LOGO  = BASE_DIR / "assets" / "slc_logo.png"

# Badge fallback (used only if auto-detection finds nothing)
# Fixed white box that covers the NotebookLM badge (measured from reference video).
# Background is near-white so the box is invisible — only the SLC logo shows.
# Box is generous to cover badge regardless of minor template differences.
# White box covers the NotebookLM badge — measured from reference video (1920x1080).
# Background is near-white so the box is invisible; only the SLC logo shows.
WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H = 1630, 953, 256, 127

# SLC logo anchored to bottom-right corner (measured from reference video).
# scale=-1:LOGO_H lets FFmpeg auto-calculate width to preserve aspect ratio.
LOGO_H             = 56   # pixels tall  (= logo height in reference)
LOGO_RIGHT_MARGIN  = 114  # pixels from right edge
LOGO_BOTTOM_MARGIN = 53   # pixels from bottom edge

# Rounded-corner radius for white boxes
BOX_RADIUS = 10

# End-card centre cover (same for all resolutions)
WM_EC_X, WM_EC_Y = 448, 310
WM_EC_W, WM_EC_H = 1024, 420
EC_RADIUS = 14

TEAL, WHITE = (96, 204, 190), (255, 255, 255)


def _font(name):
    for c in [str(BASE_DIR / "fonts" / name),
              f"/usr/share/fonts/truetype/google-fonts/{name}",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(c):
            return c
    return None

BOLD, MEDIUM = _font("Poppins-Bold.ttf"), _font("Poppins-Medium.ttf")


def _ft(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _make_box_png(boxes, path, W=1920, H=1080):
    """Render one or more rounded white rectangles onto a transparent PNG."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for (x, y, w, h, r) in boxes:
        draw.rounded_rectangle([x, y, x+w, y+h], radius=r,
                                fill=(255, 255, 255, 255))
    img.save(str(path), "PNG")
    return path


# ──────────────────── PILLOW: RENDER TEXT AS PNG ─────────────────────────
def render_intro_overlay(course, unit_num, unit_title, W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = W - 200
    csz  = 52;  cfn = _ft(BOLD, csz)
    while csz > 28:
        bb = draw.textbbox((0, 0), course, font=cfn)
        if bb[2] - bb[0] <= pad: break
        csz -= 2;  cfn = _ft(BOLD, csz)
    c_asc, c_desc = cfn.getmetrics();  c_h = c_asc + c_desc
    ufn  = _ft(BOLD, 28);  utxt = unit_num.upper()
    bb   = draw.textbbox((0, 0), utxt, font=ufn)
    badge_w = bb[2] - bb[0] + 70;  badge_h = 56
    has_title = bool(unit_title and unit_title.strip());  title_h = 0
    if has_title:
        tsz = 30;  tfn = _ft(MEDIUM, tsz)
        while tsz > 20:
            bb = draw.textbbox((0, 0), unit_title, font=tfn)
            if bb[2] - bb[0] <= pad: break
            tsz -= 2;  tfn = _ft(MEDIUM, tsz)
        t_asc, t_desc = tfn.getmetrics();  title_h = t_asc + t_desc
    gap1 = 45;  gap2 = 25
    block_h = c_h + gap1 + badge_h + (gap2 + title_h if has_title else 0)
    start_y = (H // 2 - 60) - block_h // 2
    draw.text((W // 2, start_y + c_h // 2), course,
              fill=WHITE, font=cfn, anchor="mm")
    bx = (W - badge_w) // 2;  by = start_y + c_h + gap1
    draw.rounded_rectangle([bx, by, bx+badge_w, by+badge_h],
                            radius=14, fill=TEAL + (230,))
    draw.text((bx + badge_w // 2, by + badge_h // 2),
              utxt, fill=WHITE, font=ufn, anchor="mm")
    if has_title:
        ty2 = by + badge_h + gap2
        draw.text((W // 2, ty2 + title_h // 2),
                  unit_title, fill=WHITE, font=tfn, anchor="mm")
    return img


def render_end_overlay(W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fn   = _ft(BOLD, 42)
    bb   = draw.textbbox((0, 0), "END", font=fn)
    bw, bh = bb[2] - bb[0] + 90, 72
    bx, by = (W - bw) // 2, (H - bh) // 2 - 20
    draw.rounded_rectangle([bx, by, bx+bw, by+bh],
                            radius=16, fill=TEAL + (230,))
    draw.text((bx + bw // 2, by + bh // 2),
              "END", fill=WHITE, font=fn, anchor="mm")
    return img


# ─────────────────────── FFMPEG HELPERS ──────────────────────────────────
def _ff(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.strip().split("\n")
        raise RuntimeError("\n".join(err[-6:]) if len(err) > 6 else r.stderr)
    return r


def _probe_resolution(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",");  return (int(w), int(h))
    except Exception:
        return (1920, 1080)


def _probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Cannot read duration: {path}")
    return float(r.stdout.strip())


def _has_audio(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _detect_end_card_start(path):
    total = _probe_duration(path);  t = max(0.0, total - 20.0)
    while t < total - 1.0:
        fd, tf = tempfile.mkstemp(suffix=".jpg");  os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", tf],
                capture_output=True, timeout=8)
            a = np.array(Image.open(tf))
            if (a.mean(axis=2) > 230).sum() / (a.shape[0] * a.shape[1]) > 0.95:
                return t
        except Exception:
            pass
        finally:
            try: os.unlink(tf)
            except OSError: pass
        t += 0.5
    return max(0.0, total - 9.0)


def make_intro(course, unit_num, unit_title, tmp):
    png = str(tmp / "intro_overlay.png");  out = str(tmp / "intro.mp4")
    render_intro_overlay(course, unit_num, unit_title).save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,300*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
         "-filter_complex",
         f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
         "-map", "[out]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-r", "30", "-pix_fmt", "yuv420p", out], timeout=60)
    return Path(out)


def make_outro(tmp):
    png = str(tmp / "end_overlay.png");  out = str(tmp / "outro.mp4")
    render_end_overlay().save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,250*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
         "-filter_complex",
         f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
         "-map", "[out]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-r", "30", "-pix_fmt", "yuv420p", out], timeout=60)
    return Path(out)


def normalise(inp, out):
    ha = _has_audio(inp);  cmd = ["ffmpeg", "-y", "-i", str(inp)]
    if not ha:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += [
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p",
    ]
    if not ha:
        cmd += ["-shortest"]
    cmd += [str(out)];  _ff(cmd);  return Path(out)




def remove_notebooklm_watermark(inp, out, src_resolution, tmp, progress_cb=None):  # src_resolution kept for API compat
    """
    Replace NotebookLM branding using rounded-corner PNG overlays.

    Zone 2 — Bottom-right badge (always on):
        Rounded white box sized to badge + SLC logo centred inside.

    Zone 3 — End-card full-screen (dynamically detected start):
        Rounded white box covers centred icon + notebooklm.google.com URL.
    """
    inp_str, out_str = str(inp), str(out)
    # Fixed badge cover box — measured from reference video
    brx, bry, brw, brh = WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H

    if progress_cb:
        progress_cb("Detecting end-card start time…")
    ecs       = _detect_end_card_start(inp_str)
    enable_ec = f"gte(t\\,{ecs:.2f})"

    # Pre-render rounded white box PNGs
    br_png = tmp / "wm_br.png"
    ec_png = tmp / "wm_ec.png"
    _make_box_png([(brx, bry, brw, brh, BOX_RADIUS)], br_png)
    _make_box_png([(WM_EC_X, WM_EC_Y, WM_EC_W, WM_EC_H, EC_RADIUS)], ec_png)

    use_logo = SLC_LOGO.exists() and SLC_LOGO.stat().st_size > 500

    if use_logo:
        # inputs: 0=video  1=br_png  2=ec_png  3=logo
        # PNG inputs without -loop: FFmpeg reads them as single frames.
        # -shortest stops encoding when the shortest input (video) ends.
        fc = (
            "[1:v]format=rgba[br];"
            "[0:v][br]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[ec];"
            f"[v1][ec]overlay=x=0:y=0:enable='{enable_ec}'[v2];"
            f"[3:v]scale=-1:{LOGO_H}[logo];"
            f"[v2][logo]overlay=x='W-w-113':y='H-h-53'[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", inp_str,
            "-i", str(br_png),
            "-i", str(ec_png),
            "-i", str(SLC_LOGO),
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p", "-shortest", out_str,
        ]
    else:
        # inputs: 0=video  1=br_png  2=ec_png
        fc = (
            "[1:v]format=rgba[br];"
            "[0:v][br]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[ec];"
            f"[v1][ec]overlay=x=0:y=0:enable='{enable_ec}'[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", inp_str,
            "-i", str(br_png),
            "-i", str(ec_png),
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p", "-shortest", out_str,
        ]

    # Scale timeout with video length: 25s processing per minute of video, min 900s
    duration   = _probe_duration(inp_str)
    wm_timeout = max(900, int(duration * 25))
    _ff(cmd, timeout=wm_timeout)
    return Path(out)


def add_notebooklm_transition(intro, main, out, duration=1.0, direction="left"):
    tm = {"left": "wipeleft", "right": "wiperight",
          "up": "wipeup", "down": "wipedown"}
    wipe    = tm.get(direction, "wipeleft")
    intro_d = _probe_duration(intro)
    half    = max(0.25, min(duration / 2, intro_d - 0.05))
    cc = (
        "color=c=0x7B2CBF:s=1920x1080:r=30,"
        "drawbox=x=0:y=0:w=576:h=1080:color=0x7B2CBF:t=fill,"
        "drawbox=x=576:y=0:w=461:h=1080:color=0x4285F4:t=fill,"
        "drawbox=x=1037:y=0:w=346:h=1080:color=0x7EDFC3:t=fill,"
        "drawbox=x=1383:y=0:w=537:h=1080:color=0xB7E4C7:t=fill"
    )
    _ff([
        "ffmpeg", "-y",
        "-i", str(intro), "-i", str(main),
        "-f", "lavfi", "-t", f"{duration}", "-i", cc,
        "-f", "lavfi", "-t", f"{duration}", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p,settb=AVTB[v0];"
        "[1:v]fps=30,format=yuv420p,settb=AVTB[v1];"
        "[2:v]fps=30,format=yuv420p,settb=AVTB[vc];"
        f"[v0][vc]xfade=transition={wipe}:duration={half}:offset={max(intro_d-half,0):.3f}[vx];"
        f"[vx][v1]xfade=transition={wipe}:duration={half}:offset={intro_d:.3f}[vout];"
        f"[0:a][3:a]acrossfade=d={half}:c1=tri:c2=tri[ax];"
        f"[ax][1:a]acrossfade=d={half}:c1=tri:c2=tri[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p", str(out),
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
             "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", str(out)])
    return Path(out)


def preview_frame(course, unit_num, unit_title):
    if not INTRO_TPL.exists():
        raise FileNotFoundError(f"Missing: {INTRO_TPL}")
    fd, tp = tempfile.mkstemp(suffix=".png");  os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(INTRO_TPL), "-ss", "3", "-vframes", "1", tp],
            capture_output=True, timeout=10)
        bg = Image.open(tp).convert("RGBA");  bg.load()
    finally:
        try: os.unlink(tp)
        except OSError: pass
    comp = Image.alpha_composite(
        bg, render_intro_overlay(course, unit_num, unit_title)
    ).convert("RGB")
    buf = BytesIO();  comp.save(buf, "JPEG", quality=90);  buf.seek(0)
    return buf


def _check_template():
    if not INTRO_TPL.exists():
        st.error(f"❌ Intro template not found: `{INTRO_TPL}`");  st.stop()
    if INTRO_TPL.stat().st_size < 10000:
        st.error("❌ Intro template appears corrupt.");  st.stop()

_check_template()


# ───────────────────────── CSS ────────────────────────────────────────────
st.markdown("""<style>
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
</style>""", unsafe_allow_html=True)

# ───────────────────────── HEADER ────────────────────────────────────────
st.markdown("""<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
  <h1 style="margin:0;font-size:28px">🎬 SLC Video Merger</h1>
  <span style="background:#60ccbe;color:#0a2a3c;font-size:11px;font-weight:700;
        padding:3px 12px;border-radius:20px;text-transform:uppercase">Fast</span>
</div>""", unsafe_allow_html=True)
st.markdown("""<div style="text-align:center;margin:8px 0 24px">
  <span class="fb">🎬 Custom Intro</span><span class="fa">→</span>
  <span class="fb">🟪🟦🟩⬜ Transition</span><span class="fa">→</span>
  <span class="fb">📹 NotebookLM Video</span><span class="fa">→</span>
  <span class="fb">🔚 Outro</span>
</div>""", unsafe_allow_html=True)

# ── 1  INTRO ──────────────────────────────────────────────────────────────
st.markdown('<div><span class="sn">1</span><span class="st">Intro Customisation</span></div>',
            unsafe_allow_html=True)
course_name = st.text_input("Course Name",
    placeholder="e.g. Level 3 Diploma in Sports Development (RQF)")
c1, _ = st.columns(2)
with c1:
    unit_number = st.text_input("Unit / Chapter Number",
        placeholder="e.g. UNIT 03 | CHAPTER 06")
if st.button("👁 Preview Intro", type="secondary"):
    if course_name and unit_number:
        with st.spinner("Rendering…"):
            st.image(preview_frame(course_name, unit_number, ""),
                     caption="Intro Preview", use_container_width=True)
    else:
        st.warning("Enter course name and unit number first.")
st.markdown("---")

# ── 2  VIDEO UPLOAD ───────────────────────────────────────────────────────
st.markdown('<div><span class="sn">2</span><span class="st">Upload NotebookLM Video</span></div>',
            unsafe_allow_html=True)
vid = st.file_uploader("Upload your NotebookLM video",
    type=["mp4", "mov", "webm", "avi", "mkv"], help="Up to 500 MB")
if vid:
    st.success(f"📁 **{vid.name}** — {vid.size / 1048576:.1f} MB")
st.markdown("---")

# ── 2b  SLC LOGO ──────────────────────────────────────────────────────────
st.markdown('<div><span class="sn">✦</span>'
            '<span class="st">SLC Logo (replaces NotebookLM badge)</span></div>',
            unsafe_allow_html=True)
logo_upload = st.file_uploader("SLC Logo PNG", type=["png"],
                                help="Transparent PNG preferred")
if logo_upload:
    SLC_LOGO.parent.mkdir(parents=True, exist_ok=True)
    SLC_LOGO.write_bytes(logo_upload.getvalue())
    st.success("✅ Logo saved.")
elif SLC_LOGO.exists():
    st.info("ℹ️ Using existing logo at `assets/slc_logo.png`.")
else:
    st.warning("⚠️ No logo — badge area will be covered with white only.")
st.markdown("---")

# ── 3  MERGE ──────────────────────────────────────────────────────────────
st.markdown('<div><span class="sn">3</span><span class="st">Generate Final Video</span></div>',
            unsafe_allow_html=True)
st.markdown('<p style="font-size:13px;color:rgba(255,255,255,.5);margin-bottom:16px">'
            'Merges intro + transition + NotebookLM video (watermarks replaced) + outro.</p>',
            unsafe_allow_html=True)

if st.button("🎬 Merge & Download", type="primary", use_container_width=True):
    if not course_name: st.error("Enter a course name.");   st.stop()
    if not unit_number: st.error("Enter a unit number.");   st.stop()
    if not vid:         st.error("Upload a video.");        st.stop()

    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bar = st.progress(0, "Starting…")
        msg = st.empty()
        try:
            raw = tmp / "raw.mp4"
            raw.write_bytes(vid.getvalue())
            src_res = _probe_resolution(str(raw))

            msg.info("⏳ **Step 1 / 4** — Building intro, outro and normalising…")
            bar.progress(10)
            results, errors = {}, {}

            def _job(name, fn, *args):
                try:    results[name] = fn(*args)
                except Exception as e: errors[name] = e

            with ThreadPoolExecutor(max_workers=3) as pool:
                pool.submit(_job, "intro", make_intro, course_name, unit_number, "", tmp)
                pool.submit(_job, "outro", make_outro, tmp)
                pool.submit(_job, "norm",  normalise,  raw, tmp / "norm.mp4")

            if errors:
                raise RuntimeError("; ".join(f"{k}: {v}" for k, v in errors.items()))

            msg.info(f"⏳ **Step 2 / 4** — Replacing watermarks ({src_res[0]}×{src_res[1]})…")
            bar.progress(40)
            norm_clean = remove_notebooklm_watermark(
                results["norm"], tmp / "norm_clean.mp4", src_res, tmp,
                progress_cb=lambda s: msg.info(f"⏳ **Step 2 / 4** — {s}"),
            )

            msg.info("⏳ **Step 3 / 4** — Adding 4-colour transition…")
            bar.progress(65)
            with_trans = add_notebooklm_transition(
                results["intro"], norm_clean, tmp / "intro_and_main.mp4")

            msg.info("⏳ **Step 4 / 4** — Merging final segments…")
            bar.progress(85)
            final = concat([with_trans, results["outro"]], tmp / "final.mp4", tmp)

            bar.progress(100)
            secs = time.time() - t0
            data = final.read_bytes()
            mb   = len(data) / 1048576
            msg.empty();  bar.empty()

            st.markdown(f"""<div class="ok">
                <div style="font-size:48px;margin-bottom:8px">✅</div>
                <h3>Video Ready!</h3>
                <p style="color:rgba(255,255,255,.5);font-size:13px">
                    {secs:.1f}s &nbsp;•&nbsp; {mb:.1f} MB</p>
            </div>""", unsafe_allow_html=True)

            st.markdown('<div style="margin:16px 0"><span class="sn">▶</span>'
                        '<span class="st">Preview</span></div>', unsafe_allow_html=True)
            st.video(data, format="video/mp4")

            safec    = course_name[:30].replace(" ", "_")
            safeu    = unit_number.replace(" ", "_").replace("|", "")
            filename = f"SLC_Video_{safec}_{safeu}.mp4"

            st.download_button("⬇ Download Final Video", data, filename,
                               "video/mp4", use_container_width=True)

        except Exception as e:
            bar.empty();  msg.empty()
            st.error(f"**Processing failed:**\n\n```\n{e}\n```")
