#!/usr/bin/env python3
"""
SLC Video Merger – Streamlit Edition
All text is rendered by Pillow (no FFmpeg drawtext = no escaping bugs).
FFmpeg only does: overlay PNG on video, normalise, transitions, concatenate.

OneDrive upload uses Microsoft OAuth2 (device-code flow).
No app registration key needed — just a Client ID from Azure.
"""

import os, json, subprocess, tempfile, time
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import streamlit as st

try:
    import msal, requests
    ONEDRIVE_AVAILABLE = True
except ImportError:
    ONEDRIVE_AVAILABLE = False

# ── Embedded SLC logo (base64) — written to assets/ on startup ───────────
_SLC_LOGO_B64 = "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"

st.set_page_config(page_title="SLC Video Merger", page_icon="🎬", layout="wide")

BASE_DIR  = Path(__file__).parent
INTRO_TPL = BASE_DIR / "assets" / "intro_template.mp4"
SLC_LOGO  = BASE_DIR / "assets" / "slc_logo.png"

# Token cache persisted on disk so re-auth is not needed every run
# /tmp is writable on Streamlit Cloud; BASE_DIR/assets is read-only
TOKEN_CACHE_FILE = Path("/tmp/ms_token_cache.json")

# ── Watermark / badge cover ───────────────────────────────────────────────
WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H = 1655, 960, 240, 72
# Top watermark: NotebookLM badge, very top-centre of frame
WM_TOP_X, WM_TOP_Y, WM_TOP_W, WM_TOP_H = 760, 48, 390, 72

BOX_RADIUS = 10
WM_EC_X, WM_EC_Y, WM_EC_W, WM_EC_H = 448, 310, 1024, 420
EC_RADIUS  = 14

# ── SLC logo placement (anchored bottom-right, measured from reference) ───
LOGO_H            = 44   # scaled to fit neatly inside 72px box
LOGO_RIGHT_MARGIN = 113
LOGO_BOTTOM_MARGIN = 53

# ── OneDrive settings ─────────────────────────────────────────────────────
# Uses Microsoft's well-known "Microsoft Office" public client ID —
# no Azure app registration required.
MS_CLIENT_ID = "772dd850-50bd-4c97-9152-d1b3e78fb737"
MS_SCOPES    = ["https://graph.microsoft.com/Files.ReadWrite", "https://graph.microsoft.com/User.Read"]
ONEDRIVE_FOLDER_URL = "https://globaledulinkuk-my.sharepoint.com/:f:/g/personal/content_gamification_imperiallearning_co_uk/IgDpo-qQQhSNS5aOw2lBAFo-ASQb3KWLDkHS9kp6sIHuy0s?e=3Ualc4"
MS_AUTHORITY = "https://login.microsoftonline.com/globaledulinkuk.onmicrosoft.com"

TEAL, WHITE = (96, 204, 190), (255, 255, 255)


def _font(name):
    for c in [str(BASE_DIR / "fonts" / name),
              f"/usr/share/fonts/truetype/google-fonts/{name}",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(c): return c
    return None

BOLD, MEDIUM = _font("Poppins-Bold.ttf"), _font("Poppins-Medium.ttf")


def _ft(path, size):
    try:    return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except: return ImageFont.load_default()


def _make_logo_composite(logo_path, box, W=1920, H=1080, bg=(249,249,249,255)):
    """
    Render the background box + SLC logo centred inside as one RGBA PNG.
    box = (brx, bry, brw, brh) — the cover box in video coordinates.
    """
    brx, bry, brw, brh = box
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw background box
    draw.rounded_rectangle(
        [brx, bry, brx+brw, bry+brh],
        radius=BOX_RADIUS, fill=bg)

    # Load and scale logo to fit inside box with padding
    logo_h_px = brh - 12
    logo_img  = Image.open(str(logo_path)).convert("RGBA")
    ratio     = logo_img.width / logo_img.height
    logo_w_px = int(logo_h_px * ratio)
    # Clamp width to box width
    if logo_w_px > brw - 12:
        logo_w_px = brw - 12
        logo_h_px = int(logo_w_px / ratio)
    logo_img  = logo_img.resize((logo_w_px, logo_h_px), Image.LANCZOS)

    # Centre logo in box
    cx     = brx + brw // 2
    cy     = bry + brh // 2
    logo_x = cx - logo_w_px // 2
    logo_y = cy - logo_h_px // 2
    img.paste(logo_img, (logo_x, logo_y), logo_img)

    out = Path(str(logo_path)).parent / "logo_composite.png"
    img.save(str(out), "PNG")
    return out


def _make_ec_png(path, W=1920, H=1080):
    """Render the end-card cover PNG: rounded white box only."""
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [WM_EC_X, WM_EC_Y, WM_EC_X+WM_EC_W, WM_EC_Y+WM_EC_H],
        radius=EC_RADIUS, fill=(255, 255, 255, 255))
    img.save(str(path), "PNG")
    return path


def _make_box_png(boxes, path, W=1920, H=1080, colour=(255,255,255,255)):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for (x, y, w, h, r) in boxes:
        draw.rounded_rectangle([x, y, x+w, y+h], radius=r, fill=colour)
    img.save(str(path), "PNG")
    return path


# ──────────────────── PILLOW OVERLAYS ────────────────────────────────────
def render_intro_overlay(course, unit_num, unit_title, W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    pad  = W - 200
    csz  = 52; cfn = _ft(BOLD, csz)
    while csz > 28:
        bb = draw.textbbox((0,0), course, font=cfn)
        if bb[2]-bb[0] <= pad: break
        csz -= 2; cfn = _ft(BOLD, csz)
    c_asc, c_desc = cfn.getmetrics(); c_h = c_asc+c_desc
    ufn  = _ft(BOLD, 28); utxt = unit_num.upper()
    bb   = draw.textbbox((0,0), utxt, font=ufn)
    badge_w = bb[2]-bb[0]+70; badge_h = 56
    has_title = bool(unit_title and unit_title.strip()); title_h = 0
    if has_title:
        tsz = 30; tfn = _ft(MEDIUM, tsz)
        while tsz > 20:
            bb = draw.textbbox((0,0), unit_title, font=tfn)
            if bb[2]-bb[0] <= pad: break
            tsz -= 2; tfn = _ft(MEDIUM, tsz)
        t_asc, t_desc = tfn.getmetrics(); title_h = t_asc+t_desc
    gap1 = 45; gap2 = 25
    block_h = c_h+gap1+badge_h+(gap2+title_h if has_title else 0)
    start_y = (H//2-60)-block_h//2
    draw.text((W//2, start_y+c_h//2), course, fill=WHITE, font=cfn, anchor="mm")
    bx = (W-badge_w)//2; by = start_y+c_h+gap1
    draw.rounded_rectangle([bx,by,bx+badge_w,by+badge_h], radius=14, fill=TEAL+(230,))
    draw.text((bx+badge_w//2, by+badge_h//2), utxt, fill=WHITE, font=ufn, anchor="mm")
    if has_title:
        ty2 = by+badge_h+gap2
        draw.text((W//2, ty2+title_h//2), unit_title, fill=WHITE, font=tfn, anchor="mm")
    return img


def render_end_overlay(W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    fn   = _ft(BOLD, 42); bb = draw.textbbox((0,0), "END", font=fn)
    bw, bh = bb[2]-bb[0]+90, 72; bx, by = (W-bw)//2, (H-bh)//2-20
    draw.rounded_rectangle([bx,by,bx+bw,by+bh], radius=16, fill=TEAL+(230,))
    draw.text((bx+bw//2, by+bh//2), "END", fill=WHITE, font=fn, anchor="mm")
    return img


# ──────────────────── FFMPEG HELPERS ────────────────────────────────────
def _ff(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.strip().split("\n")
        raise RuntimeError("\n".join(err[-6:]) if len(err)>6 else r.stderr)
    return r


def _probe_resolution(path):
    r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
        "-show_entries","stream=width,height","-of","csv=p=0",str(path)],
        capture_output=True, text=True)
    try:    w, h = r.stdout.strip().split(","); return (int(w), int(h))
    except: return (1920, 1080)


def _probe_duration(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",str(path)],
        capture_output=True, text=True)
    if r.returncode!=0 or not r.stdout.strip():
        raise RuntimeError(f"Cannot read duration: {path}")
    return float(r.stdout.strip())


def _has_audio(path):
    r = subprocess.run(["ffprobe","-v","error","-select_streams","a",
        "-show_entries","stream=index","-of","csv=p=0",str(path)],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _detect_end_card_start(path):
    total = _probe_duration(path); t = max(0.0, total-20.0)
    while t < total-1.0:
        fd, tf = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            subprocess.run(["ffmpeg","-y","-ss",f"{t:.2f}","-i",str(path),
                "-vframes","1",tf], capture_output=True, timeout=8)
            a = np.array(Image.open(tf))
            if (a.mean(axis=2)>230).sum()/(a.shape[0]*a.shape[1]) > 0.95:
                return t
        except: pass
        finally:
            try: os.unlink(tf)
            except: pass
        t += 0.5
    return max(0.0, total-9.0)


def make_intro(course, unit_num, unit_title, tmp):
    png = str(tmp/"intro_overlay.png"); out = str(tmp/"intro.mp4")
    render_intro_overlay(course, unit_num, unit_title).save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,300*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg","-y","-i",str(INTRO_TPL),"-loop","1","-i",png,"-filter_complex",
        f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
        "-map","[out]","-map","0:a?","-c:v","libx264","-preset","ultrafast",
        "-crf","23","-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
        "-r","30","-pix_fmt","yuv420p",out], timeout=60)
    return Path(out)


def make_outro(tmp):
    png = str(tmp/"end_overlay.png"); out = str(tmp/"outro.mp4")
    render_end_overlay().save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,250*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg","-y","-i",str(INTRO_TPL),"-loop","1","-i",png,"-filter_complex",
        f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
        "-map","[out]","-map","0:a?","-c:v","libx264","-preset","ultrafast",
        "-crf","23","-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
        "-r","30","-pix_fmt","yuv420p",out], timeout=60)
    return Path(out)


def normalise(inp, out):
    ha = _has_audio(inp); cmd = ["ffmpeg","-y","-i",str(inp)]
    if not ha: cmd += ["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
    cmd += ["-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r","30","-c:v","libx264","-preset","ultrafast","-crf","23",
        "-c:a","aac","-b:a","128k","-ar","48000","-ac","2","-pix_fmt","yuv420p"]
    if not ha: cmd += ["-shortest"]
    cmd += [str(out)]; _ff(cmd); return Path(out)


def _detect_top_watermark_end(path, max_scan=120.0):
    """
    Detect when NotebookLM top watermark disappears using frame comparison.
    Grabs the first frame (has the badge), then scans forward until
    that specific region changes significantly = slide transitioned = badge gone.
    Returns end_time in seconds, or 0.0 if no badge detected.
    """
    try:
        src_w, src_h = _probe_resolution(path)
    except Exception:
        src_w, src_h = 1920, 1080

    sx = src_w / 1920
    sy = src_h / 1080
    rx = max(0, int(WM_TOP_X * sx))
    ry = max(0, int(WM_TOP_Y * sy))
    rw = max(1, int(WM_TOP_W * sx))
    rh = max(1, int(WM_TOP_H * sy))

    def _grab_region(t):
        fd, tf = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", tf],
                capture_output=True, timeout=8)
            img = Image.open(tf).convert("RGB")
            return np.array(img)[ry:ry+rh, rx:rx+rw].astype(float)
        except Exception:
            return None
        finally:
            try: os.unlink(tf)
            except OSError: pass

    # Get reference frame (t=0)
    ref = _grab_region(0.0)
    if ref is None or ref.size == 0:
        return 0.0
    # If region is not near-white, no badge present
    if (ref > 200).mean() < 0.60:
        return 0.0

    total    = _probe_duration(path)
    scan_end = min(max_scan, total - 2.0)
    step     = 0.5
    t        = step
    last_t   = 0.0

    while t <= scan_end:
        frame = _grab_region(t)
        if frame is not None and frame.size > 0:
            diff = np.abs(frame - ref).mean()
            if diff < 12:
                last_t = t   # region unchanged — badge still present
            else:
                return last_t + step   # region changed — badge gone
        t += step

    return min(last_t + step, max_scan)


def remove_notebooklm_watermark(inp, out, src_resolution, tmp, progress_cb=None):
    inp_str, out_str = str(inp), str(out)

    if progress_cb: progress_cb("Detecting end-card start time…")
    ecs      = _detect_end_card_start(inp_str)
    duration = _probe_duration(inp_str)

    # If end card detected, trim video at that point instead of covering it.
    # Only trim if end card starts with at least 2 s of content remaining
    # (guards against false positives on all-white title slides).
    trim_at = None
    if ecs < duration - 2.0:
        trim_at = ecs
        if progress_cb: progress_cb(f"✂️ Trimming end card at {ecs:.1f}s…")

    use_logo = SLC_LOGO.exists() and SLC_LOGO.stat().st_size > 500

    # Zone 1: top badge — detect duration by frame comparison
    if progress_cb: progress_cb("Detecting top watermark duration…")
    top_end = _detect_top_watermark_end(inp_str)
    top_png = tmp / "wm_top.png"
    if top_end > 0.5:
        if progress_cb: progress_cb(f"   Badge visible until ~{top_end:.1f}s")
        _make_box_png([(WM_TOP_X, WM_TOP_Y, WM_TOP_W, WM_TOP_H, BOX_RADIUS)],
                      top_png, colour=(249, 249, 249, 255))
        use_top  = True
        en_top   = f"lte(t\\,{top_end:.2f})"
    else:
        if progress_cb: progress_cb("   No top badge detected — skipping")
        Image.new("RGBA", (1920, 1080), (0,0,0,0)).save(str(top_png), "PNG")
        use_top = False
        en_top  = "0"

    if use_logo:
        comp_png = _make_logo_composite(
            logo_path=SLC_LOGO,
            box=(WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H),
        )
        fc = (
            "[1:v]format=rgba[comp];"
            "[0:v][comp]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[top];"
            f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]"
        )
        cmd = ["ffmpeg","-y","-i",inp_str,"-i",str(comp_png),"-i",str(top_png)]
    else:
        br_png = tmp/"wm_br.png"
        _make_box_png([(WM_BR_X,WM_BR_Y,WM_BR_W,WM_BR_H,BOX_RADIUS)],
                      br_png, colour=(249,249,249,255))
        fc = (
            "[1:v]format=rgba[br];"
            "[0:v][br]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[top];"
            f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]"
        )
        cmd = ["ffmpeg","-y","-i",inp_str,"-i",str(br_png),"-i",str(top_png)]

    # Add trim via -t if end card was detected
    if trim_at is not None:
        cmd += ["-filter_complex", fc,
                "-map","[vout]","-map","0:a",
                "-t", f"{trim_at:.2f}",
                "-c:v","libx264","-preset","ultrafast","-crf","23",
                "-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
                "-r","30","-pix_fmt","yuv420p",out_str]
    else:
        cmd += ["-filter_complex", fc,
                "-map","[vout]","-map","0:a",
                "-c:v","libx264","-preset","ultrafast","-crf","23",
                "-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
                "-r","30","-pix_fmt","yuv420p","-shortest",out_str]

    _ff(cmd, timeout=max(900, int(duration*25)))
    return Path(out)


def add_notebooklm_transition(intro, main, out, duration=1.0, direction="left"):
    tm = {"left":"wipeleft","right":"wiperight","up":"wipeup","down":"wipedown"}
    wipe = tm.get(direction,"wipeleft"); intro_d = _probe_duration(intro)
    half = max(0.25, min(duration/2, intro_d-0.05))
    cc = ("color=c=0x7B2CBF:s=1920x1080:r=30,"
          "drawbox=x=0:y=0:w=576:h=1080:color=0x7B2CBF:t=fill,"
          "drawbox=x=576:y=0:w=461:h=1080:color=0x4285F4:t=fill,"
          "drawbox=x=1037:y=0:w=346:h=1080:color=0x7EDFC3:t=fill,"
          "drawbox=x=1383:y=0:w=537:h=1080:color=0xB7E4C7:t=fill")
    _ff(["ffmpeg","-y","-i",str(intro),"-i",str(main),
         "-f","lavfi","-t",f"{duration}","-i",cc,
         "-f","lavfi","-t",f"{duration}","-i","anullsrc=r=48000:cl=stereo",
         "-filter_complex",
         "[0:v]fps=30,format=yuv420p,settb=AVTB[v0];"
         "[1:v]fps=30,format=yuv420p,settb=AVTB[v1];"
         "[2:v]fps=30,format=yuv420p,settb=AVTB[vc];"
         f"[v0][vc]xfade=transition={wipe}:duration={half}:offset={max(intro_d-half,0):.3f}[vx];"
         f"[vx][v1]xfade=transition={wipe}:duration={half}:offset={intro_d:.3f}[vout];"
         f"[0:a][3:a]acrossfade=d={half}:c1=tri:c2=tri[ax];"
         f"[ax][1:a]acrossfade=d={half}:c1=tri:c2=tri[aout]",
         "-map","[vout]","-map","[aout]",
         "-c:v","libx264","-preset","ultrafast","-crf","23",
         "-c:a","aac","-b:a","128k","-ar","48000","-ac","2",
         "-r","30","-pix_fmt","yuv420p",str(out)], timeout=180)
    return Path(out)


def concat(parts, out, tmp):
    lst = tmp/"list.txt"
    with open(lst,"w") as f:
        for p in parts: f.write(f"file '{Path(p).resolve()}'\n")
    try:
        _ff(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c","copy",str(out)])
    except RuntimeError:
        _ff(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
             "-c:v","libx264","-preset","ultrafast","-crf","23",
             "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p",str(out)])
    return Path(out)


def preview_frame(course, unit_num, unit_title):
    if not INTRO_TPL.exists(): raise FileNotFoundError(f"Missing: {INTRO_TPL}")
    fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try:
        subprocess.run(["ffmpeg","-y","-i",str(INTRO_TPL),"-ss","3","-vframes","1",tp],
                       capture_output=True, timeout=10)
        bg = Image.open(tp).convert("RGBA"); bg.load()
    finally:
        try: os.unlink(tp)
        except: pass
    comp = Image.alpha_composite(bg, render_intro_overlay(course,unit_num,unit_title)).convert("RGB")
    buf = BytesIO(); comp.save(buf,"JPEG",quality=90); buf.seek(0)
    return buf


# ──────────────────── ONEDRIVE OAUTH2 (DEVICE CODE FLOW) ────────────────
def _get_token_cache():
    cache = msal.SerializableTokenCache()
    # Try /tmp file first, then session_state backup
    if TOKEN_CACHE_FILE.exists():
        try:
            cache.deserialize(TOKEN_CACHE_FILE.read_text())
            return cache
        except Exception:
            pass
    if st.session_state.get("_ms_token_cache"):
        try:
            cache.deserialize(st.session_state["_ms_token_cache"])
        except Exception:
            pass
    return cache


def _save_token_cache(cache):
    if cache.has_state_changed:
        serialized = cache.serialize()
        # Save to /tmp (persists across reruns in same session)
        try:
            TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE_FILE.write_text(serialized)
        except Exception:
            pass
        # Also save to session_state (backup)
        st.session_state["_ms_token_cache"] = serialized


def _get_msal_app(cache=None):
    return msal.PublicClientApplication(
        MS_CLIENT_ID,
        authority=MS_AUTHORITY,
        token_cache=cache,
    )


def _get_access_token():
    """Return a valid access token or None. Tries cache first."""
    try:
        cache = _get_token_cache()
        app   = _get_msal_app(cache)
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(MS_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                _save_token_cache(cache)
                return result["access_token"]
    except Exception:
        # Corrupt/stale cache — clear it
        TOKEN_CACHE_FILE.unlink(missing_ok=True)
    return None


def _start_device_flow():
    """Initiate device-code flow. Returns the flow dict (contains user_code and verification_uri)."""
    cache = _get_token_cache()
    app   = _get_msal_app(cache)
    flow  = app.initiate_device_flow(scopes=MS_SCOPES)
    st.session_state["ms_flow"]  = flow
    st.session_state["ms_cache"] = cache
    return flow


def _complete_device_flow():
    """Poll for token after user completes auth. Returns (True, token) or (False, error)."""
    flow  = st.session_state.get("ms_flow")
    cache = st.session_state.get("ms_cache")
    if not flow or not cache:
        return False, "No active auth flow. Click 'Connect Microsoft Account' first."
    app    = _get_msal_app(cache)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_token_cache(cache)
        # clear flow from session
        st.session_state.pop("ms_flow", None)
        st.session_state.pop("ms_cache", None)
        return True, result["access_token"]
    err = result.get("error_description") or result.get("error") or str(result)
    return False, err


def _onedrive_upload(data: bytes, filename: str, folder_name: str, token: str, status_cb=None, **kwargs):
    """
    Upload video to OneDrive.
    Priority: 1) URL resolution  2) Personal search  3) Error (no auto-create)
    """
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    def _cb(s):
        if status_cb: status_cb(s)

    folder_id    = None
    drive_prefix = "me/drive"
    folder_url   = kwargs.get("folder_url", "").strip()

    # ── 1. URL resolution ────────────────────────────────────────────
    if folder_url:
        _cb("🔗 Resolving folder from URL…")
        try:
            import base64 as _b64
            b64 = _b64.urlsafe_b64encode(folder_url.encode()).rstrip(b"=").decode()
            for ep in [
                f"https://graph.microsoft.com/v1.0/shares/u!{b64}/root"
                "?$select=id,name,webUrl,parentReference",
                f"https://graph.microsoft.com/v1.0/shares/u!{b64}/driveItem"
                "?$select=id,name,webUrl,parentReference",
            ]:
                sr = requests.get(ep, headers=h, timeout=20)
                _cb(f"   → HTTP {sr.status_code}")
                if sr.status_code == 200:
                    item         = sr.json()
                    folder_id    = item["id"]
                    drv          = item.get("parentReference", {}).get("driveId", "")
                    drive_prefix = f"drives/{drv}" if drv else "me/drive"
                    _cb(f"✅ Folder resolved: '{item.get('name','?')}'")
                    break
            if not folder_id:
                _cb(f"⚠️ URL resolve failed ({sr.status_code}): {sr.text[:150]}")
        except Exception as ex:
            _cb(f"⚠️ URL error: {ex}")

    # ── 2. Search personal OneDrive by name ──────────────────────────
    if not folder_id:
        _cb("🔍 Searching personal OneDrive…")
        r = requests.get(
            "https://graph.microsoft.com/v1.0/me/drive/root/search"
            f"(q='{folder_name}')?$select=id,name,webUrl,folder,parentReference",
            headers=h, timeout=20)
        if r.status_code == 200:
            hits = [i for i in r.json().get("value", [])
                    if folder_name.lower() in i.get("name","").lower()]
            if hits:
                item         = hits[0]
                folder_id    = item["id"]
                drv          = item.get("parentReference", {}).get("driveId", "")
                drive_prefix = f"drives/{drv}" if drv else "me/drive"
                _cb(f"✅ Found in personal OneDrive: '{item['name']}'")

    # ── 3. Search sharedWithMe ────────────────────────────────────────
    if not folder_id:
        _cb("🔍 Searching shared items…")
        next_url = ("https://graph.microsoft.com/v1.0/me/drive/sharedWithMe"
                    "?$select=id,name,folder,remoteItem&$top=100")
        while next_url and not folder_id:
            rs = requests.get(next_url, headers=h, timeout=20)
            if rs.status_code != 200: break
            for item in rs.json().get("value", []):
                if folder_name.lower() in item.get("name", "").lower():
                    remote       = item.get("remoteItem", {})
                    folder_id    = remote.get("id") or item.get("id", "")
                    drv          = (remote.get("parentReference", {}).get("driveId", "")
                                    or item.get("parentReference", {}).get("driveId", ""))
                    drive_prefix = f"drives/{drv}" if drv else "me/drive"
                    _cb(f"✅ Found in shared items: '{item['name']}'")
                    break
            next_url = rs.json().get("@odata.nextLink")

    # ── 4. Give up — do NOT auto-create ──────────────────────────────
    if not folder_id:
        return False, (
            f"❌ Folder '{folder_name}' not found.\n\n"
            f"Please paste the folder URL in the **OneDrive folder URL** field above. "
            f"Open the folder in your browser and copy the address bar URL."
        )

    # ── 4. Create upload session ──────────────────────────────────────
    _cb("⬆️ Creating upload session…")

    # Build URL — prioritise folder_id based URL when we have one
    safe_name = filename.replace(" ", "_")
    if folder_id and drive_prefix != "me/drive":
        # Shared/remote folder — use drive+item format (most correct)
        urls_to_try = [
            f"https://graph.microsoft.com/v1.0/{drive_prefix}/items/{folder_id}:/{safe_name}:/createUploadSession",
            f"https://graph.microsoft.com/v1.0/{drive_prefix}/items/{folder_id}:/{filename}:/createUploadSession",
        ]
    elif folder_id:
        # Personal drive folder resolved by ID
        urls_to_try = [
            f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}:/{safe_name}:/createUploadSession",
            f"https://graph.microsoft.com/v1.0/me/drive/root:/{folder_name}/{safe_name}:/createUploadSession",
        ]
    else:
        # Fallback: path-based
        urls_to_try = [
            f"https://graph.microsoft.com/v1.0/me/drive/root:/{folder_name}/{safe_name}:/createUploadSession",
        ]

    r2 = None
    errors = []
    for i, session_url in enumerate(urls_to_try):
        _cb(f"   Trying URL format {i+1}: …{session_url[-60:]}")
        try:
            r2 = requests.post(
                session_url, headers=h,
                json={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
                timeout=30)
            _cb(f"   Response: HTTP {r2.status_code}")
            if r2.status_code in (200, 201):
                break
            else:
                errors.append(f"Format {i+1} → HTTP {r2.status_code}: {r2.text[:100]}")
                r2 = None
        except Exception as ex:
            errors.append(f"Format {i+1} → Exception: {ex}")
            r2 = None

    if r2 is None:
        err_detail = "\n".join(errors)
        return False, (
            f"❌ All upload session attempts failed:\n{err_detail}\n\n"
            f"folder_id=`{folder_id}` drive=`{drive_prefix}`"
        )

    upload_url = r2.json().get("uploadUrl")
    if not upload_url:
        return False, f"❌ No uploadUrl in response: {r2.text[:300]}"

    # ── 5. Upload in 5 MB chunks (smaller = safer on Streamlit Cloud) ──
    CHUNK    = 5 * 1024 * 1024   # 5 MB — must be multiple of 320 KB
    total    = len(data)
    uploaded = 0
    file_web_url = None
    last_pct = -1

    while uploaded < total:
        chunk     = data[uploaded: uploaded + CHUNK]
        chunk_end = uploaded + len(chunk) - 1
        pct       = int(uploaded / total * 100)

        # Only log every 10% to avoid spamming
        if pct // 10 != last_pct // 10:
            _cb(f"⬆️ Uploading… {pct}% ({uploaded//1048576} / {total//1048576} MB)")
            last_pct = pct

        r3 = requests.put(
            upload_url,
            data=chunk,
            timeout=180,   # 3 min per chunk
            headers={
                "Content-Length": str(len(chunk)),
                "Content-Range":  f"bytes {uploaded}-{chunk_end}/{total}",
                "Content-Type":   "video/mp4",
            })

        if r3.status_code in (200, 201):
            # Final chunk acknowledged — file is written
            try:
                file_web_url = r3.json().get("webUrl", "")
            except Exception:
                file_web_url = ""
        elif r3.status_code == 202:
            # Chunk accepted, more to send
            pass
        else:
            return False, (
                f"Upload failed at byte {uploaded} "
                f"(HTTP {r3.status_code}): {r3.text[:300]}"
            )

        uploaded += len(chunk)

    if uploaded >= total:
        _cb(f"✅ Upload complete! ({total//1048576} MB uploaded)")
        return True, file_web_url or "https://onedrive.live.com"
    else:
        return False, f"Upload incomplete — only {uploaded} of {total} bytes sent."


def _check_template():
    if not INTRO_TPL.exists():
        st.error(f"❌ Intro template not found: `{INTRO_TPL}`"); st.stop()
    if INTRO_TPL.stat().st_size < 10000:
        st.error("❌ Intro template appears corrupt."); st.stop()


def _ensure_logo():
    """Write embedded SLC logo to assets/slc_logo.png if not already there."""
    if not SLC_LOGO.exists() or SLC_LOGO.stat().st_size < 100:
        import base64
        SLC_LOGO.parent.mkdir(parents=True, exist_ok=True)
        SLC_LOGO.write_bytes(base64.b64decode(_SLC_LOGO_B64))


_check_template()
_ensure_logo()


# ──────────────────────── CSS ─────────────────────────────────────────────
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
.auth-box{background:rgba(255,255,255,.05);border:1px solid rgba(96,204,190,.3);border-radius:12px;padding:16px;margin:12px 0;font-size:14px}
</style>""", unsafe_allow_html=True)

# ──────────────────────── HEADER ──────────────────────────────────────────
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
st.markdown('<div><span class="sn">1</span><span class="st">Intro Customisation</span></div>', unsafe_allow_html=True)
course_name = st.text_input("Course Name", placeholder="e.g. Level 3 Diploma in Sports Development (RQF)")
c1, _ = st.columns(2)
with c1:
    unit_number = st.text_input("Unit / Chapter Number", placeholder="e.g. UNIT 03 | CHAPTER 06")
if st.button("👁 Preview Intro", type="secondary"):
    if course_name and unit_number:
        with st.spinner("Rendering…"):
            st.image(preview_frame(course_name, unit_number, ""), caption="Intro Preview", use_container_width=True)
    else:
        st.warning("Enter course name and unit number first.")
st.markdown("---")

# ── 2  VIDEO UPLOAD ───────────────────────────────────────────────────────
st.markdown('<div><span class="sn">2</span><span class="st">Upload NotebookLM Video</span></div>', unsafe_allow_html=True)
vid = st.file_uploader("Upload your NotebookLM video", type=["mp4","mov","webm","avi","mkv"], help="Up to 500 MB")
if vid:
    st.success(f"📁 **{vid.name}** — {vid.size/1048576:.1f} MB")
st.markdown("---")



# ── 2c  ONEDRIVE — auto-connect, fixed folder ────────────────────────────
if ONEDRIVE_AVAILABLE:
    _token = _get_access_token()
    if _token:
        st.markdown('<div><span class="sn">☁</span><span class="st">OneDrive</span></div>', unsafe_allow_html=True)
        st.success("✅ Connected to OneDrive — videos will upload automatically after merging.")
        if st.button("🔄 Switch account / Re-connect", type="secondary", key="od_reset"):
            TOKEN_CACHE_FILE.unlink(missing_ok=True)
            st.session_state.pop("ms_flow", None)
            st.session_state.pop("ms_cache", None)
            st.rerun()
    else:
        st.markdown('<div><span class="sn">☁</span><span class="st">OneDrive — One-time Setup</span></div>', unsafe_allow_html=True)
        st.markdown(
            '<p style="font-size:13px;color:rgba(255,255,255,.7);margin-bottom:8px">'
            'Sign in once with the department Microsoft account — '
            'stays connected permanently for all users.</p>',
            unsafe_allow_html=True)
        if "ms_flow" not in st.session_state:
            if st.button("🔑 Connect Department Microsoft Account"):
                with st.spinner("Starting sign-in…"):
                    flow = _start_device_flow()
                st.rerun()
        else:
            flow = st.session_state["ms_flow"]
            st.markdown(f"""
            <div class="auth-box">
            <strong>Step 1</strong> — Open this link:<br>
            <a href="{flow['verification_uri']}" target="_blank" style="color:#60ccbe;font-size:15px">
            {flow['verification_uri']}</a><br><br>
            <strong>Step 2</strong> — Enter this code: &nbsp;
            <code style="background:#1a3a5c;padding:4px 12px;border-radius:6px;font-size:18px;
                          letter-spacing:3px;color:#60ccbe">{flow['user_code']}</code><br><br>
            <strong>Step 3</strong> — Sign in with the department account, then click below.
            </div>""", unsafe_allow_html=True)
            if st.button("✅ I've signed in — complete connection"):
                with st.spinner("Completing sign-in…"):
                    ok, result = _complete_device_flow()
                if ok:
                    st.success("✅ Connected! Upload will be available after merging.")
                    st.rerun()
                else:
                    st.error(f"Sign-in failed: {result}")

st.markdown("---")

# ── 3  MERGE ──────────────────────────────────────────────────────────────
st.markdown('<div><span class="sn">3</span><span class="st">Generate Final Video</span></div>', unsafe_allow_html=True)
st.markdown('<p style="font-size:13px;color:rgba(255,255,255,.5);margin-bottom:16px">'
    'Merges intro + transition + NotebookLM video (watermarks replaced) + outro.</p>',
    unsafe_allow_html=True)

# Store folder URL in session state so it's available after rerun
if "onedrive_url_input" in dir() and onedrive_url_input.strip():
    st.session_state["_od_url"] = onedrive_url_input.strip()

if st.button("🎬 Merge & Download", type="primary", use_container_width=True):
    if not course_name: st.error("Enter a course name."); st.stop()
    if not unit_number: st.error("Enter a unit number."); st.stop()
    if not vid:         st.error("Upload a video.");      st.stop()

    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td); bar = st.progress(0, "Starting…"); msg = st.empty()
        try:
            raw = tmp/"raw.mp4"; raw.write_bytes(vid.getvalue())
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
                pool.submit(_job, "norm",  normalise,  raw, tmp/"norm.mp4")

            if errors:
                raise RuntimeError("; ".join(f"{k}: {v}" for k,v in errors.items()))

            msg.info(f"⏳ **Step 2 / 4** — Replacing watermarks ({src_res[0]}×{src_res[1]})…")
            bar.progress(40)
            norm_clean = remove_notebooklm_watermark(
                results["norm"], tmp/"norm_clean.mp4", src_res, tmp,
                progress_cb=lambda s: msg.info(f"⏳ **Step 2 / 4** — {s}"))

            msg.info("⏳ **Step 3 / 4** — Adding 4-colour transition…")
            bar.progress(65)
            with_trans = add_notebooklm_transition(results["intro"], norm_clean, tmp/"intro_and_main.mp4")

            msg.info("⏳ **Step 4 / 4** — Merging final segments…")
            bar.progress(85)
            final = concat([with_trans, results["outro"]], tmp/"final.mp4", tmp)

            bar.progress(100); secs = time.time()-t0
            data = final.read_bytes(); mb = len(data)/1048576
            msg.empty(); bar.empty()

            # Save to session_state so upload button works after rerun
            safec    = course_name[:30].replace(" ","_")
            safeu    = unit_number.replace(" ","_").replace("|","")
            filename = f"SLC_Video_{safec}_{safeu}.mp4"
            st.session_state["video_data"]     = data
            st.session_state["video_filename"] = filename
            st.session_state["video_mb"]       = mb
            st.session_state["video_secs"]     = secs

        except Exception as e:
            bar.empty(); msg.empty()
            st.error(f"**Processing failed:**\n\n```\n{e}\n```")

# ── Show result + download + upload (outside temp dir, persists on rerun) ─
if st.session_state.get("video_data"):
    data     = st.session_state["video_data"]
    filename = st.session_state["video_filename"]
    mb       = st.session_state["video_mb"]
    secs     = st.session_state["video_secs"]

    st.markdown(f"""<div class="ok">
        <div style="font-size:48px;margin-bottom:8px">✅</div>
        <h3>Video Ready!</h3>
        <p style="color:rgba(255,255,255,.5);font-size:13px">
            {secs:.1f}s &nbsp;•&nbsp; {mb:.1f} MB</p>
    </div>""", unsafe_allow_html=True)

    st.markdown('<div style="margin:16px 0"><span class="sn">▶</span>'
        '<span class="st">Preview</span></div>', unsafe_allow_html=True)
    st.video(data, format="video/mp4")

    st.download_button("⬇ Download Final Video", data, filename,
                       "video/mp4", use_container_width=True)

    # ── OneDrive upload — uses fixed department folder ───────────────
    current_token = _get_access_token()
    if current_token and ONEDRIVE_AVAILABLE:
        st.markdown("---")
        st.markdown('<div style="margin:8px 0"><span class="sn">☁</span>'
            '<span class="st">Save to OneDrive</span></div>', unsafe_allow_html=True)
        if st.button("☁ Upload to OneDrive", use_container_width=True):
            prog = st.progress(0, "Starting upload…")
            stat = st.empty()

            def _log(s):
                stat.info(s)
                if "%" in s:
                    try:
                        pct = int(s.split("%")[0].split()[-1])
                        prog.progress(pct, s)
                    except Exception:
                        pass

            ok, result = _onedrive_upload(
                data, filename, "",
                current_token,
                status_cb=_log,
                folder_url=ONEDRIVE_FOLDER_URL,
            )
            prog.empty()
            if ok:
                stat.empty()
                st.success(f"✅ Uploaded **{filename}** to OneDrive! [Open file]({result})")
            else:
                stat.empty()
                st.error(result)
