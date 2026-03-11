#!/usr/bin/env python3
"""
SLC Video Merger – Streamlit Edition
All text is rendered by Pillow (no FFmpeg drawtext = no escaping bugs).
FFmpeg only does: overlay PNG on video, normalise, concatenate.
"""

import os, subprocess, time, tempfile, base64
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont
import streamlit as st
import canva_api

# ────────────────────────────── CONFIG ──────────────────────────────────
st.set_page_config(page_title="SLC Video Merger", page_icon="🎬", layout="wide")

BASE_DIR   = Path(__file__).parent
INTRO_TPL  = BASE_DIR / "assets" / "intro_template.mp4"

# Fonts – check bundled first, then system
def _font(name):
    candidates = [
        str(BASE_DIR / "fonts" / name),                              # bundled
        f"/usr/share/fonts/truetype/google-fonts/{name}",            # linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     # fallback
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
    try:    return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except: return ImageFont.load_default()

def render_intro_overlay(course, unit_num, unit_title, W=1920, H=1080):
    """Return a 1920x1080 RGBA PNG with all text centered on screen."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = W - 200  # max text width

    # ── 1. Measure everything first ──

    # Course name font (auto-shrink to fit)
    csz = 52
    cfn = _ft(BOLD, csz)
    while csz > 28:
        bb = draw.textbbox((0, 0), course, font=cfn)
        if bb[2] - bb[0] <= pad: break
        csz -= 2; cfn = _ft(BOLD, csz)
    c_asc, c_desc = cfn.getmetrics()
    c_h = c_asc + c_desc                  # full visual line height

    # Unit number badge
    ufn  = _ft(BOLD, 28)
    utxt = unit_num.upper()
    bb   = draw.textbbox((0, 0), utxt, font=ufn)
    badge_tw = bb[2] - bb[0]
    badge_w  = badge_tw + 70
    badge_h  = 56

    # Unit title (optional)
    has_title = bool(unit_title and unit_title.strip())
    title_h = 0
    if has_title:
        tsz = 30; tfn = _ft(MEDIUM, tsz)
        while tsz > 20:
            bb = draw.textbbox((0, 0), unit_title, font=tfn)
            if bb[2] - bb[0] <= pad: break
            tsz -= 2; tfn = _ft(MEDIUM, tsz)
        t_asc, t_desc = tfn.getmetrics()
        title_h = t_asc + t_desc

    # ── 2. Calculate total block height & center vertically ──
    gap1 = 45                              # course → badge
    gap2 = 25                              # badge → title
    block_h = c_h + gap1 + badge_h
    if has_title:
        block_h += gap2 + title_h

    # True vertical center of 1080p frame, shifted slightly up
    # so the text + logo together feel balanced
    center_y = (H // 2) - 60              # 480px — true visual middle
    start_y  = center_y - block_h // 2

    # ── 3. Draw everything ──

    # Course name — horizontally + vertically centered
    draw.text((W // 2, start_y + c_h // 2),
              course, fill=WHITE, font=cfn, anchor="mm")

    # Badge — centered below course name
    badge_x = (W - badge_w) // 2
    badge_y = start_y + c_h + gap1
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=14, fill=TEAL + (230,))
    draw.text((badge_x + badge_w // 2, badge_y + badge_h // 2),
              utxt, fill=WHITE, font=ufn, anchor="mm")

    # Unit title — centered below badge
    if has_title:
        title_y = badge_y + badge_h + gap2
        draw.text((W // 2, title_y + title_h // 2),
                  unit_title, fill=WHITE, font=tfn, anchor="mm")

    return img

def render_end_overlay(W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fn   = _ft(BOLD, 42)
    bb   = draw.textbbox((0, 0), "END", font=fn)
    tw   = bb[2] - bb[0]
    bw, bh = tw + 90, 72               # fixed height
    bx, by = (W - bw) // 2, (H - bh) // 2 - 20
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16,
                           fill=TEAL + (230,))
    draw.text((bx + bw // 2, by + bh // 2),
              "END", fill=WHITE, font=fn, anchor="mm")
    return img


# ────────────────────── FFMPEG HELPERS ─────────────────────────────────
def _ff(cmd, timeout=600):
    """Run an ffmpeg command; raise on failure."""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        # grab the last meaningful lines
        err = r.stderr.strip().split("\n")
        short = "\n".join(err[-6:]) if len(err) > 6 else r.stderr
        raise RuntimeError(short)
    return r

def make_intro(course, unit_num, unit_title, tmp):
    """Overlay text PNG onto intro template with rise animation."""
    png = str(tmp / "intro_overlay.png")
    out = str(tmp / "intro.mp4")

    render_intro_overlay(course, unit_num, unit_title).save(png, "PNG")

    # Rise animation:  y = 300*(1-t/0.8)^2  for t<0.8, then y=0
    # \\, escapes commas inside FFmpeg if() expressions
    y = "if(lt(t\\,0.8)\\,300*pow(1-t/0.8\\,2)\\,0)"

    _ff([
        "ffmpeg", "-y",
        "-i", str(INTRO_TPL),
        "-loop", "1", "-i", png,
        "-filter_complex",
        "[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='" + y + "':shortest=1[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p",
        out,
    ], timeout=60)
    return Path(out)

def make_outro(tmp):
    """Overlay END badge onto intro template with rise animation."""
    png = str(tmp / "end_overlay.png")
    out = str(tmp / "outro.mp4")

    render_end_overlay().save(png, "PNG")

    y = "if(lt(t\\,0.8)\\,250*pow(1-t/0.8\\,2)\\,0)"

    _ff([
        "ffmpeg", "-y",
        "-i", str(INTRO_TPL),
        "-loop", "1", "-i", png,
        "-filter_complex",
        "[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='" + y + "':shortest=1[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p",
        out,
    ], timeout=60)
    return Path(out)

def normalise(inp, out):
    """Scale/pad any video to 1920x1080 @ 30fps, h264+aac."""
    _ff([
        "ffmpeg", "-y", "-i", str(inp),
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p",
        str(out),
    ])
    return Path(out)

def concat(parts, out, tmp):
    """Concatenate videos via demuxer (fast copy, fallback re-encode)."""
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
    """Quick JPEG preview: overlay text on a still from the template."""
    # Check template exists and is valid
    if not INTRO_TPL.exists():
        raise FileNotFoundError(
            f"Intro template not found at: {INTRO_TPL}\n"
            f"Make sure assets/intro_template.mp4 is in your repo.")
    if INTRO_TPL.stat().st_size < 1000:
        raise ValueError(
            f"Intro template is too small ({INTRO_TPL.stat().st_size} bytes) — "
            f"file may be corrupted or is a Git LFS pointer. "
            f"Re-upload the actual .mp4 file to GitHub.")

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(INTRO_TPL),
             "-ss", "3", "-vframes", "1", tmp_path],
            capture_output=True, text=True, timeout=10)

        # Check FFmpeg succeeded and file has content
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg frame extract failed:\n{result.stderr[-300:]}")
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 100:
            raise RuntimeError(
                f"FFmpeg produced empty frame. Template may be corrupt.\n"
                f"Template path: {INTRO_TPL}\n"
                f"Template size: {INTRO_TPL.stat().st_size} bytes\n"
                f"FFmpeg stderr: {result.stderr[-300:]}")

        bg = Image.open(tmp_path).convert("RGBA")
        bg.load()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except OSError: pass

    ovr = render_intro_overlay(course, unit_num, unit_title)
    comp = Image.alpha_composite(bg, ovr).convert("RGB")
    buf = BytesIO()
    comp.save(buf, "JPEG", quality=90)
    buf.seek(0)
    return buf


# ── Startup check ──
def _check_template():
    """Verify intro template on startup and show warnings."""
    if not INTRO_TPL.exists():
        st.error(
            f"❌ **Intro template not found!**\n\n"
            f"Expected: `{INTRO_TPL}`\n\n"
            f"Make sure `assets/intro_template.mp4` is committed to your GitHub repo.\n\n"
            f"**Common issue:** If the file was uploaded via GitHub web UI, "
            f"it might have failed silently for large files.")
        st.stop()
    size = INTRO_TPL.stat().st_size
    if size < 10000:  # Less than 10KB means it's probably a Git LFS pointer
        st.error(
            f"❌ **Intro template appears corrupt!**\n\n"
            f"File size: {size} bytes (expected ~950KB)\n\n"
            f"This usually means:\n"
            f"- The file is a **Git LFS pointer** (text file instead of actual video)\n"
            f"- The upload to GitHub **failed silently**\n\n"
            f"**Fix:** Delete `assets/intro_template.mp4` from GitHub, then re-upload "
            f"using `git push` from command line, or drag-drop the actual MP4 file.")
        st.stop()

_check_template()


# ──────────────────── CANVA OAUTH CALLBACK ─────────────────────────────
# Handle redirect from Canva after user authorizes
qp = st.query_params
if "code" in qp and canva_api.is_configured():
    with st.spinner("Connecting to Canva..."):
        if canva_api.handle_callback(qp):
            st.success("✅ Connected to Canva!")
        # Clear URL params after handling
        st.query_params.clear()
        st.rerun()


# ──────────────────── SIDEBAR: CANVA CONNECTION ────────────────────────
with st.sidebar:
    st.markdown("### 🎨 Canva Integration")

    if not canva_api.is_configured():
        st.markdown("""
        <div style="background:rgba(255,165,0,.08);border:1px solid rgba(255,165,0,.25);
                    border-radius:10px;padding:14px;font-size:12px;color:rgba(255,255,255,.6)">
            <b style="color:#ffa500">Setup Required</b><br><br>
            To enable direct upload to Canva:<br><br>
            <b>1.</b> Go to <a href="https://www.canva.com/developers" target="_blank"
               style="color:#60ccbe">Canva Developer Portal</a><br>
            <b>2.</b> Create an integration<br>
            <b>3.</b> Set scopes: <code>asset:write</code>, <code>asset:read</code><br>
            <b>4.</b> Set redirect URL to your app URL<br>
            <b>5.</b> Add to <code>.streamlit/secrets.toml</code>:<br><br>
            <code style="font-size:11px">CANVA_CLIENT_ID = "your_id"<br>
            CANVA_CLIENT_SECRET = "your_secret"<br>
            CANVA_REDIRECT_URI = "your_app_url"</code>
        </div>""", unsafe_allow_html=True)

    elif canva_api.is_connected():
        st.markdown(
            '<div style="background:rgba(96,204,190,.1);border:1px solid rgba(96,204,190,.3);'
            'border-radius:10px;padding:12px;text-align:center">'
            '<span style="color:#60ccbe;font-weight:600">✅ Connected to Canva</span></div>',
            unsafe_allow_html=True)
        if st.button("Disconnect from Canva", use_container_width=True):
            canva_api.disconnect()
            st.rerun()

    else:
        st.markdown(
            '<p style="font-size:12px;color:rgba(255,255,255,.5)">'
            'Connect your Canva account to upload videos directly.</p>',
            unsafe_allow_html=True)
        auth_url = canva_api.start_auth_flow()
        st.link_button("🔗 Connect to Canva", auth_url, use_container_width=True)

    st.markdown("---")


# ──────────────────────── CUSTOM CSS ──────────────────────────────────
st.markdown("""<style>
.stApp{background:linear-gradient(135deg,#0a2a3c 0%,#0d3b54 30%,#0f4c6e 60%,#1a3a5c 100%)}
header[data-testid="stHeader"]{background:rgba(10,42,60,.85);backdrop-filter:blur(10px)}
section[data-testid="stSidebar"]{background:rgba(10,42,60,.95);border-right:1px solid rgba(96,204,190,.2)}
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
.stLinkButton>a{background:rgba(255,255,255,.1)!important;color:#fff!important;border:1px solid rgba(96,204,190,.4)!important;border-radius:12px!important;font-weight:600!important;padding:.6rem 2rem!important;text-decoration:none!important}
.stLinkButton>a:hover{background:rgba(96,204,190,.15)!important;border-color:#60ccbe!important}
video{border-radius:12px;border:1px solid rgba(96,204,190,.2)}
</style>""", unsafe_allow_html=True)


# ──────────────────────── LAYOUT ──────────────────────────────────────
st.markdown("""<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
<h1 style="margin:0;font-size:28px">🎬 SLC Video Merger</h1>
<span style="background:#60ccbe;color:#0a2a3c;font-size:11px;font-weight:700;
padding:3px 12px;border-radius:20px;text-transform:uppercase">Fast</span>
</div>""", unsafe_allow_html=True)

st.markdown("""<div style="text-align:center;margin:8px 0 24px">
<span class="fb">🎬 Custom Intro</span><span class="fa">→</span>
<span class="fb">📹 NotebookLM Video</span><span class="fa">→</span>
<span class="fb">🔚 Outro</span></div>""", unsafe_allow_html=True)

# ── 1  INTRO ──
st.markdown('<div><span class="sn">1</span><span class="st">Intro Customisation</span></div>', unsafe_allow_html=True)
course_name = st.text_input("Course Name",
    placeholder="e.g. Level 3 Diploma in Sports Development (RQF)")
c1, c2 = st.columns(2)
with c1:
    unit_number = st.text_input("Unit / Chapter Number",
        placeholder="e.g. UNIT 03 | CHAPTER 06")
with c2:
    unit_title = st.text_input("Unit Title (optional)",
        placeholder="e.g. Sports Coaching Principles")

if st.button("👁  Preview Intro", type="secondary"):
    if course_name and unit_number:
        with st.spinner("Rendering…"):
            st.image(preview_frame(course_name, unit_number, unit_title or ""),
                     caption="Intro Preview", use_container_width=True)
    else:
        st.warning("Enter course name + unit number first.")

st.markdown("---")

# ── 2  UPLOAD ──
st.markdown('<div><span class="sn">2</span><span class="st">Upload NotebookLM Video</span></div>', unsafe_allow_html=True)
vid = st.file_uploader("Upload your NotebookLM video",
    type=["mp4","mov","webm","avi","mkv"],
    help="MP4 / MOV / WebM — up to 500 MB")
if vid:
    st.success(f"📁 **{vid.name}** — {vid.size / 1048576:.1f} MB")

st.markdown("---")

# ── 3  MERGE ──
st.markdown('<div><span class="sn">3</span><span class="st">Generate Final Video</span></div>', unsafe_allow_html=True)
st.markdown('<p style="font-size:13px;color:rgba(255,255,255,.5);margin-bottom:16px">'
            'Merges custom intro + uploaded video + standard outro.</p>',
            unsafe_allow_html=True)

if st.button("🎬  Merge & Download", type="primary", use_container_width=True):
    # validate
    if not course_name: st.error("Enter a course name."); st.stop()
    if not unit_number:  st.error("Enter a unit number.");  st.stop()
    if not vid:          st.error("Upload a video.");        st.stop()

    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bar = st.progress(0, "Starting…")
        msg = st.empty()

        try:
            # Save upload to disk first (needed for FFmpeg)
            raw = tmp / "raw.mp4"
            raw.write_bytes(vid.getvalue())

            # ── Run intro + outro + normalise IN PARALLEL ──
            msg.info("⏳ **Step 1 / 2** — Building intro, outro & normalising video (parallel)…")
            bar.progress(15, "Processing 3 jobs in parallel…")

            results = {}
            errors  = {}
            def _job(name, fn, *args):
                try:    results[name] = fn(*args)
                except Exception as e: errors[name] = e

            with ThreadPoolExecutor(max_workers=3) as pool:
                pool.submit(_job, "intro", make_intro,
                            course_name, unit_number, unit_title or "", tmp)
                pool.submit(_job, "outro", make_outro, tmp)
                pool.submit(_job, "norm",  normalise, raw, tmp / "norm.mp4")

            if errors:
                raise RuntimeError(
                    "; ".join(f"{k}: {v}" for k, v in errors.items()))

            bar.progress(75, "Merging…")

            # ── Concat (fast copy) ──
            msg.info("⏳ **Step 2 / 2** — Merging segments…")
            final = concat(
                [results["intro"], results["norm"], results["outro"]],
                tmp / "final.mp4", tmp)
            bar.progress(100, "Done!")

            secs = time.time() - t0
            data = final.read_bytes()
            mb   = len(data) / 1048576

            msg.empty(); bar.empty()

            st.markdown(f"""<div class="ok">
            <div style="font-size:48px;margin-bottom:8px">✅</div>
            <h3>Video Ready!</h3>
            <p style="color:rgba(255,255,255,.5);font-size:13px">
            Processed in {secs:.1f}s &nbsp;•&nbsp; {mb:.1f} MB</p>
            </div>""", unsafe_allow_html=True)

            # ── Full-screen video preview ──
            st.markdown('<div style="margin:16px 0"><span class="sn">▶</span>'
                        '<span class="st">Preview</span></div>',
                        unsafe_allow_html=True)
            st.video(data, format="video/mp4")

            # ── Download + Canva buttons ──
            safec = course_name[:30].replace(" ", "_")
            safeu = unit_number.replace(" ", "_").replace("|", "")
            filename = f"SLC_Video_{safec}_{safeu}.mp4"

            # Store video in session state for Canva upload
            st.session_state["final_video"] = data
            st.session_state["final_filename"] = filename

            bcol1, bcol2 = st.columns(2)
            with bcol1:
                st.download_button("⬇  Download Final Video", data,
                    filename, "video/mp4", use_container_width=True)
            with bcol2:
                if canva_api.is_connected():
                    # Real Canva upload
                    if st.button("🎨  Upload to Canva", use_container_width=True,
                                 type="primary"):
                        with st.spinner("Uploading to Canva..."):
                            ok, msg_text = canva_api.upload_video(data, filename)
                        if ok:
                            st.success(f"✅ {msg_text}")
                            st.markdown(
                                '<p style="font-size:12px;color:rgba(255,255,255,.5);text-align:center">'
                                'Open Canva → Uploads to find your video.</p>',
                                unsafe_allow_html=True)
                        else:
                            st.error(msg_text)
                else:
                    # Fallback: link to Canva video creator
                    canva_url = "https://www.canva.com/create/videos/"
                    st.link_button("🎨  Edit in Canva", canva_url,
                                   use_container_width=True)

            # Show setup hint only if not connected
            if not canva_api.is_connected():
                st.markdown("""
                <div style="background:rgba(96,204,190,.06);border:1px solid rgba(96,204,190,.15);
                            border-radius:12px;padding:16px 20px;margin-top:12px">
                    <p style="font-size:13px;font-weight:600;color:#60ccbe;margin:0 0 8px">
                        💡 Want direct upload to Canva?</p>
                    <p style="font-size:12px;color:rgba(255,255,255,.5);margin:0;line-height:1.8">
                        Connect your Canva account in the <b>sidebar</b> to upload videos
                        directly to your Canva library with one click.<br>
                        Or: Download → Click "Edit in Canva" → Upload manually.</p>
                </div>""", unsafe_allow_html=True)

        except Exception as e:
            bar.empty(); msg.empty()
            st.error(f"**Processing failed:**\n\n```\n{e}\n```")
