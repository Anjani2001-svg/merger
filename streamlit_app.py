#!/usr/bin/env python3
"""
SLC Video Merger – Streamlit Edition  (Queue build)
All text is rendered by Pillow (no FFmpeg drawtext = no escaping bugs).
FFmpeg only does: overlay PNG on video, normalise, transitions, concatenate.

OneDrive upload uses Microsoft OAuth2 (device-code flow).
No app registration key needed — just a Client ID from Azure.
"""

import os, json, subprocess, tempfile, time, uuid
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import streamlit as st

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import msal, requests
    ONEDRIVE_AVAILABLE = True
except ImportError:
    ONEDRIVE_AVAILABLE = False

# ── Embedded SLC logo (base64) — written to assets/ on startup ───────────
_SLC_LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAHcAAABNCAYAAACc2PtBAAAtpElEQVR4nO29WY8kyZXv9ztm5mvsuWctXc1ukk1OX1KjucQVpAcBepAAfWJ9AAkC9HAx94ozHK69VFdlVVbusftiZnpwN0/PrC2bPcTVDHmAzIjwcHeLsGNn/x8LqWpHn4QPvwbAK7wAqNvz/DvO618iqvfKIR4Qh/LgpHded/67jzefCVT/ADT3e+e4vVF7z5VX773m3wupj5/yDpIPM/L7DPs+xvbJ37lG4e9d9zd6N5kfdvktkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRAAAAA="

st.set_page_config(page_title="SLC Video Merger", page_icon="🎬", layout="wide")

BASE_DIR  = Path(__file__).parent
INTRO_TPL = BASE_DIR / "assets" / "intro_template.mp4"
SLC_LOGO  = BASE_DIR / "assets" / "slc_logo.png"

TOKEN_CACHE_FILE = Path("/tmp/ms_token_cache.json")

# ── Watermark / badge cover ───────────────────────────────────────────────
WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H = 1655, 960, 240, 72
WM_TOP_X, WM_TOP_Y, WM_TOP_W, WM_TOP_H = 760, 48, 390, 72

BOX_RADIUS = 10
WM_EC_X, WM_EC_Y, WM_EC_W, WM_EC_H = 448, 310, 1024, 420
EC_RADIUS  = 14

LOGO_H            = 44
LOGO_RIGHT_MARGIN = 113
LOGO_BOTTOM_MARGIN = 53

MS_CLIENT_ID = st.secrets.get("MS_CLIENT_ID", "")
MS_SCOPES    = ["https://graph.microsoft.com/Files.ReadWrite", "https://graph.microsoft.com/User.Read"]
ONEDRIVE_FOLDER_URL = st.secrets.get("ONEDRIVE_FOLDER_URL", "")
MS_AUTHORITY = st.secrets.get("MS_AUTHORITY", "https://login.microsoftonline.com/common")

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
    brx, bry, brw, brh = box
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([brx, bry, brx+brw, bry+brh], radius=BOX_RADIUS, fill=bg)
    logo_h_px = brh - 12
    logo_img  = Image.open(str(logo_path)).convert("RGBA")
    ratio     = logo_img.width / logo_img.height
    logo_w_px = int(logo_h_px * ratio)
    if logo_w_px > brw - 12:
        logo_w_px = brw - 12
        logo_h_px = int(logo_w_px / ratio)
    logo_img  = logo_img.resize((logo_w_px, logo_h_px), Image.LANCZOS)
    cx     = brx + brw // 2; cy = bry + brh // 2
    logo_x = cx - logo_w_px // 2; logo_y = cy - logo_h_px // 2
    img.paste(logo_img, (logo_x, logo_y), logo_img)
    out = Path(str(logo_path)).parent / "logo_composite.png"
    img.save(str(out), "PNG")
    return out


def _make_ec_png(path, W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([WM_EC_X, WM_EC_Y, WM_EC_X+WM_EC_W, WM_EC_Y+WM_EC_H],
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


def _detect_end_card_start(path, progress_cb=None):
    """Detect where the NotebookLM end card begins using OpenCV template matching.

    Returns the trim timestamp, or the full duration if no end card is found.
    """
    total = _probe_duration(path)

    def _grab_cv(t):
        """Extract frame at *t* as a 640×360 BGR OpenCV image (or None)."""
        fd, tf = tempfile.mkstemp(suffix=".png"); os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", "-s", "640x360", tf],
                capture_output=True, timeout=10)
            if os.path.getsize(tf) < 100:
                return None
            if CV2_AVAILABLE:
                return cv2.imread(tf)
            else:
                return np.asarray(Image.open(tf).convert("L"), dtype=np.float32)
        except Exception:
            return None
        finally:
            try: os.unlink(tf)
            except OSError: pass

    def _score_frame(frame):
        """Return template-match score (0..1) for *frame*, or -1."""
        if frame is None:
            return -1.0
        if CV2_AVAILABLE:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            try:
                res = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
                _, mx, _, _ = cv2.minMaxLoc(res)
                return float(mx)
            except cv2.error:
                return -1.0
        else:
            crop = frame[cy1:cy2, cx1:cx2]
            if crop.shape != template_gray.shape:
                return -1.0
            diff = float(np.mean(np.abs(crop.astype(float) - template_gray.astype(float))))
            return max(0.0, 1.0 - diff / 50.0)

    HARD_THRESH  = 0.70   # definite end-card match
    SOFT_THRESH  = 0.35   # transition / fade-in region

    if progress_cb: progress_cb("   Capturing end-card reference…")

    # ── Get the last READABLE frame ─────────────────────────────────────
    end_frame = None
    for offset in [1.0, 2.0, 3.0, 5.0]:
        t_try = max(0.0, total - offset)
        end_frame = _grab_cv(t_try)
        if end_frame is not None:
            if progress_cb: progress_cb(f"   End frame captured at t={t_try:.1f}s")
            break
    if end_frame is None:
        if progress_cb: progress_cb("   Cannot read any frame near the end")
        return total

    # Content reference from 40 % of video
    content_frame = _grab_cv(total * 0.40)

    # ── Extract centre 60 % crop as template ────────────────────────────
    h, w = end_frame.shape[:2]
    cx1, cy1 = int(w * 0.20), int(h * 0.20)
    cx2, cy2 = int(w * 0.80), int(h * 0.80)
    template = end_frame[cy1:cy2, cx1:cx2]

    if CV2_AVAILABLE:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        template_gray = template

    # ── Safety checks ───────────────────────────────────────────────────
    end_score = _score_frame(end_frame)
    if end_score < HARD_THRESH:
        if progress_cb: progress_cb(f"   End frame score {end_score:.2f} — not an end card")
        return total

    if content_frame is not None and _score_frame(content_frame) >= HARD_THRESH:
        if progress_cb: progress_cb("   Content matches end-card template — skipping trim")
        return total

    if progress_cb: progress_cb("   End-card confirmed. Scanning backward…")

    # ── Phase 1 — coarse backward scan (1 s steps, hard threshold) ─────
    scan_limit = max(0.0, total - 60.0)
    boundary = total
    t = total - 1.0
    while t > scan_limit:
        frame = _grab_cv(t)
        if frame is not None and _score_frame(frame) >= HARD_THRESH:
            boundary = t
            t -= 1.0
        else:
            break

    # ── Phase 2 — fine forward scan (0.1 s steps) to find precise edge ─
    fine_start = max(scan_limit, boundary - 2.0)
    fine_end   = min(total, boundary + 1.0)
    precise    = boundary
    t = fine_start
    while t <= fine_end:
        frame = _grab_cv(t)
        sc = _score_frame(frame)
        if sc >= HARD_THRESH:
            precise = t
            break
        t += 0.10

    # ── Phase 3 — walk backward in 0.10 s steps (hard threshold) ───────
    t = precise - 0.10
    while t > scan_limit:
        frame = _grab_cv(t)
        sc = _score_frame(frame)
        if sc >= HARD_THRESH:
            precise = t
            t -= 0.10
        else:
            break

    # ── Phase 4 — detect transition zone (soft threshold) ──────────────
    # The end card often fades in over 0.3-0.5 s before the hard match.
    # Walk further back with the lower threshold to catch that.
    transition_start = precise
    t = precise - 0.10
    while t > scan_limit:
        frame = _grab_cv(t)
        sc = _score_frame(frame)
        if sc >= SOFT_THRESH:
            transition_start = t
            t -= 0.10
        else:
            break

    # Use the transition start (catches the fade-in)
    precise = transition_start

    # ── Phase 5 — content-divergence detection ──────────────────────────
    # The transition often starts with a white flash / dissolve BEFORE the
    # end-card template fades in.  These frames score low on the template
    # but look nothing like the preceding content.  Compare each frame
    # against a confirmed-content reference; if the pixel diff is abnormally
    # high, the frame is still part of the transition.
    content_ref_t = max(0.0, precise - 5.0)
    content_ref = _grab_cv(content_ref_t)
    if content_ref is not None:
        if CV2_AVAILABLE:
            ref_gray = cv2.cvtColor(content_ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            ref_gray = content_ref.astype(np.float32)

        def _content_diff(frame):
            if frame is None:
                return 0.0
            if CV2_AVAILABLE:
                g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            else:
                g = frame.astype(np.float32)
            return float(np.mean(np.abs(g - ref_gray)))

        # Measure baseline diff — sample a frame right next to the reference
        baseline_diff = _content_diff(_grab_cv(content_ref_t + 1.0))
        # Threshold: anything more than 4× the baseline (or > 3.0 absolute)
        # is a diverged frame (transition / flash)
        diff_thresh = max(3.0, baseline_diff * 4.0)

        t = precise - 0.10
        while t > scan_limit:
            frame = _grab_cv(t)
            d = _content_diff(frame)
            if d > diff_thresh:
                precise = t
                t -= 0.10
            else:
                break

    ec_len = total - precise
    if ec_len < 0.5:
        if progress_cb: progress_cb(f"   End card {ec_len:.2f}s — too short, skipping")
        return total

    if progress_cb:
        progress_cb(f"   End card: {precise:.1f}s → {total:.1f}s  ({ec_len:.1f}s)")
    return precise


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


def _detect_notebooklm_logo_cv(video_path, progress_cb=None):
    """Use OpenCV to detect the NotebookLM logo on the front page.
    Extracts the bottom-right logo from a middle frame as a template,
    then searches the front page (top half) for the same logo via
    multi-scale template matching.
    Returns (x, y, w, h) in 1920x1080 coordinates, or None.
    """
    if not CV2_AVAILABLE:
        if progress_cb: progress_cb("OpenCV not available")
        return None
    try:
        duration = _probe_duration(str(video_path))
    except Exception:
        return None

    mid_t = min(duration * 0.3, max(5.0, duration - 10))
    fd1, tf_mid = tempfile.mkstemp(suffix=".png"); os.close(fd1)
    fd2, tf_front = tempfile.mkstemp(suffix=".png"); os.close(fd2)
    try:
        subprocess.run(["ffmpeg","-y","-ss",f"{mid_t:.2f}","-i",str(video_path),
                        "-vframes","1",tf_mid], capture_output=True, timeout=10)
        subprocess.run(["ffmpeg","-y","-ss","0.5","-i",str(video_path),
                        "-vframes","1",tf_front], capture_output=True, timeout=10)
        mid_img = cv2.imread(tf_mid)
        front_img = cv2.imread(tf_front)
        if mid_img is None or front_img is None:
            return None

        fh, fw = front_img.shape[:2]
        mh, mw = mid_img.shape[:2]

        # --- Step 1: extract bottom-right logo from middle frame as template ---
        sx_m, sy_m = mw / 1920, mh / 1080
        bx = max(0, int(WM_BR_X * sx_m)); by = max(0, int(WM_BR_Y * sy_m))
        bw = min(int(WM_BR_W * sx_m), mw - bx)
        bh = min(int(WM_BR_H * sy_m), mh - by)
        template = mid_img[by:by+bh, bx:bx+bw]
        if template.size == 0:
            return None

        # --- Step 2: multi-scale template matching on front page top half ---
        search_h = int(fh * 0.50)
        search_region = front_img[0:search_h, :]
        gray_region = cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)
        gray_tmpl  = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        th, tw = gray_tmpl.shape[:2]

        best_match = None
        best_val   = 0.50

        for scale in np.arange(0.5, 1.6, 0.1):
            sw = int(tw * scale); sh = int(th * scale)
            if sw >= search_region.shape[1] or sh >= search_region.shape[0] or sw < 10 or sh < 10:
                continue
            scaled_tmpl = cv2.resize(gray_tmpl, (sw, sh))
            res = cv2.matchTemplate(gray_region, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_match = (max_loc[0], max_loc[1], sw, sh)

        if best_match:
            sx_f, sy_f = 1920 / fw, 1080 / fh
            pad = 8
            rx = max(0, int((best_match[0] - pad) * sx_f))
            ry = max(0, int((best_match[1] - pad) * sy_f))
            rw = int((best_match[2] + pad * 2) * sx_f)
            rh = int((best_match[3] + pad * 2) * sy_f)
            if progress_cb: progress_cb(f"   CV match at ({rx},{ry}) {rw}x{rh}  conf={best_val:.2f}")
            return (rx, ry, rw, rh)

        return None

    except Exception as e:
        if progress_cb: progress_cb(f"   CV detection error: {e}")
        return None
    finally:
        try: os.unlink(tf_mid)
        except: pass
        try: os.unlink(tf_front)
        except: pass


def _detect_top_watermark_end(path, max_scan=120.0, badge_box=None):
    try:
        src_w, src_h = _probe_resolution(path)
    except Exception:
        src_w, src_h = 1920, 1080
    sx = src_w / 1920; sy = src_h / 1080
    if badge_box:
        bb_x, bb_y, bb_w, bb_h = badge_box
        rx = max(0, int(bb_x * sx)); ry = max(0, int(bb_y * sy))
        rw = max(1, int(bb_w * sx)); rh = max(1, int(bb_h * sy))
    else:
        rx = max(0, int(WM_TOP_X * sx)); ry = max(0, int(WM_TOP_Y * sy))
        rw = max(1, int(WM_TOP_W * sx)); rh = max(1, int(WM_TOP_H * sy))

    def _grab_region(t):
        fd, tf = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            subprocess.run(["ffmpeg","-y","-ss",f"{t:.2f}","-i",str(path),
                             "-vframes","1",tf], capture_output=True, timeout=8)
            img = Image.open(tf).convert("RGB")
            return np.array(img)[ry:ry+rh, rx:rx+rw].astype(float)
        except Exception:
            return None
        finally:
            try: os.unlink(tf)
            except OSError: pass

    ref = _grab_region(0.0)
    if ref is None or ref.size == 0: return 0.0
    if (ref > 200).mean() < 0.60: return 0.0
    total = _probe_duration(path); scan_end = min(max_scan, total - 2.0)
    step = 0.5; t = step; last_t = 0.0
    while t <= scan_end:
        frame = _grab_region(t)
        if frame is not None and frame.size > 0:
            diff = np.abs(frame - ref).mean()
            if diff < 12: last_t = t
            else: return last_t + step
        t += step
    return min(last_t + step, max_scan)


def remove_notebooklm_watermark(inp, out, src_resolution, tmp, progress_cb=None):
    inp_str, out_str = str(inp), str(out)
    if progress_cb: progress_cb("Detecting end-card start time…")
    ecs = _detect_end_card_start(inp_str, progress_cb=progress_cb)
    duration = _probe_duration(inp_str)
    # The detector returns `duration` when no end card is found.
    # Any value less than that means a genuine end card was detected.
    trim_at = None
    if ecs < duration - 0.3:
        trim_at = ecs
        if progress_cb: progress_cb(f"✂️ Trimming end card at {trim_at:.1f}s  ({duration - trim_at:.1f}s removed)")
    else:
        if progress_cb: progress_cb("   No end card to trim")
    use_logo = SLC_LOGO.exists() and SLC_LOGO.stat().st_size > 500

    # --- OpenCV logo detection for front-page badge ---
    if progress_cb: progress_cb("Detecting front-page logo with OpenCV…")
    cv_badge = _detect_notebooklm_logo_cv(inp_str, progress_cb=progress_cb)
    top_png = tmp / "wm_top.png"
    if cv_badge:
        badge_x, badge_y, badge_w, badge_h = cv_badge
        if progress_cb: progress_cb(f"   CV detected badge at ({badge_x},{badge_y}) {badge_w}x{badge_h}")
        if progress_cb: progress_cb("Detecting top watermark duration…")
        top_end = _detect_top_watermark_end(inp_str, badge_box=(badge_x, badge_y, badge_w, badge_h))
        if top_end > 0.5:
            if progress_cb: progress_cb(f"   Badge visible until ~{top_end:.1f}s")
            _make_box_png([(badge_x, badge_y, badge_w, badge_h, BOX_RADIUS)],
                          top_png, colour=(249, 249, 249, 255))
            use_top = True; en_top = f"lte(t\\,{top_end:.2f})"
        else:
            if progress_cb: progress_cb("   Badge not visible long enough — skipping")
            Image.new("RGBA", (1920, 1080), (0,0,0,0)).save(str(top_png), "PNG")
            use_top = False; en_top = "0"
    else:
        if progress_cb: progress_cb("   No front-page badge detected — skipping")
        Image.new("RGBA", (1920, 1080), (0,0,0,0)).save(str(top_png), "PNG")
        use_top = False; en_top = "0"
    if use_logo:
        comp_png = _make_logo_composite(logo_path=SLC_LOGO, box=(WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H))
        fc = ("[1:v]format=rgba[comp];[0:v][comp]overlay=x=0:y=0[v1];"
              "[2:v]format=rgba[top];"
              f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]")
        cmd = ["ffmpeg","-y","-i",inp_str,"-i",str(comp_png),"-i",str(top_png)]
    else:
        br_png = tmp/"wm_br.png"
        _make_box_png([(WM_BR_X,WM_BR_Y,WM_BR_W,WM_BR_H,BOX_RADIUS)], br_png, colour=(249,249,249,255))
        fc = ("[1:v]format=rgba[br];[0:v][br]overlay=x=0:y=0[v1];"
              "[2:v]format=rgba[top];"
              f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]")
        cmd = ["ffmpeg","-y","-i",inp_str,"-i",str(br_png),"-i",str(top_png)]
    if trim_at is not None:
        cmd += ["-filter_complex",fc,"-map","[vout]","-map","0:a",
                "-t",f"{trim_at:.2f}","-c:v","libx264","-preset","ultrafast","-crf","23",
                "-c:a","aac","-b:a","128k","-ar","48000","-ac","2","-r","30","-pix_fmt","yuv420p",out_str]
    else:
        cmd += ["-filter_complex",fc,"-map","[vout]","-map","0:a",
                "-c:v","libx264","-preset","ultrafast","-crf","23",
                "-c:a","aac","-b:a","128k","-ar","48000","-ac","2","-r","30","-pix_fmt","yuv420p","-shortest",out_str]
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


# ──────────────────── ONEDRIVE OAUTH2 ────────────────────────────────────
def _get_token_cache():
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        try: cache.deserialize(TOKEN_CACHE_FILE.read_text()); return cache
        except Exception: pass
    if st.session_state.get("_ms_token_cache"):
        try: cache.deserialize(st.session_state["_ms_token_cache"])
        except Exception: pass
    return cache


def _save_token_cache(cache):
    if cache.has_state_changed:
        serialized = cache.serialize()
        try:
            TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE_FILE.write_text(serialized)
        except Exception: pass
        st.session_state["_ms_token_cache"] = serialized


def _get_msal_app(cache=None):
    return msal.PublicClientApplication(MS_CLIENT_ID, authority=MS_AUTHORITY, token_cache=cache)


def _get_access_token():
    try:
        cache = _get_token_cache(); app = _get_msal_app(cache)
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(MS_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                _save_token_cache(cache); return result["access_token"]
    except Exception:
        TOKEN_CACHE_FILE.unlink(missing_ok=True)
    return None


def _start_device_flow():
    cache = _get_token_cache(); app = _get_msal_app(cache)
    flow = app.initiate_device_flow(scopes=MS_SCOPES)
    st.session_state["ms_flow"] = flow; st.session_state["ms_cache"] = cache
    return flow


def _complete_device_flow():
    flow = st.session_state.get("ms_flow"); cache = st.session_state.get("ms_cache")
    if not flow or not cache: return False, "No active auth flow."
    app = _get_msal_app(cache); result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_token_cache(cache)
        st.session_state.pop("ms_flow", None); st.session_state.pop("ms_cache", None)
        return True, result["access_token"]
    err = result.get("error_description") or result.get("error") or str(result)
    return False, err


def _onedrive_upload(data: bytes, filename: str, folder_name: str, token: str, status_cb=None, **kwargs):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    def _cb(s):
        if status_cb: status_cb(s)
    folder_id = None; drive_prefix = "me/drive"; folder_url = kwargs.get("folder_url","").strip()
    if folder_url:
        _cb("🔗 Resolving folder from URL…")
        try:
            import base64 as _b64
            b64 = _b64.urlsafe_b64encode(folder_url.encode()).rstrip(b"=").decode()
            for ep in [
                f"https://graph.microsoft.com/v1.0/shares/u!{b64}/root?$select=id,name,webUrl,parentReference",
                f"https://graph.microsoft.com/v1.0/shares/u!{b64}/driveItem?$select=id,name,webUrl,parentReference",
            ]:
                sr = requests.get(ep, headers=h, timeout=20)
                _cb(f"   → HTTP {sr.status_code}")
                if sr.status_code == 200:
                    item = sr.json(); folder_id = item["id"]
                    drv = item.get("parentReference",{}).get("driveId","")
                    drive_prefix = f"drives/{drv}" if drv else "me/drive"
                    _cb(f"✅ Folder resolved: '{item.get('name','?')}'"); break
            if not folder_id: _cb(f"⚠️ URL resolve failed ({sr.status_code})")
        except Exception as ex: _cb(f"⚠️ URL error: {ex}")
    if not folder_id:
        _cb("🔍 Searching personal OneDrive…")
        r = requests.get(f"https://graph.microsoft.com/v1.0/me/drive/root/search(q='{folder_name}')?$select=id,name,webUrl,folder,parentReference", headers=h, timeout=20)
        if r.status_code == 200:
            hits = [i for i in r.json().get("value",[]) if folder_name.lower() in i.get("name","").lower()]
            if hits:
                item = hits[0]; folder_id = item["id"]
                drv = item.get("parentReference",{}).get("driveId","")
                drive_prefix = f"drives/{drv}" if drv else "me/drive"
                _cb(f"✅ Found: '{item['name']}'")
    if not folder_id:
        return False, (f"❌ Folder '{folder_name}' not found. Paste the folder URL above.")
    _cb("⬆️ Creating upload session…")
    safe_name = filename.replace(" ","_")
    if folder_id and drive_prefix != "me/drive":
        urls_to_try = [
            f"https://graph.microsoft.com/v1.0/{drive_prefix}/items/{folder_id}:/{safe_name}:/createUploadSession",
            f"https://graph.microsoft.com/v1.0/{drive_prefix}/items/{folder_id}:/{filename}:/createUploadSession",
        ]
    else:
        urls_to_try = [
            f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}:/{safe_name}:/createUploadSession",
            f"https://graph.microsoft.com/v1.0/me/drive/root:/{folder_name}/{safe_name}:/createUploadSession",
        ]
    r2 = None; errors = []
    for i, session_url in enumerate(urls_to_try):
        _cb(f"   Trying URL format {i+1}…")
        try:
            r2 = requests.post(session_url, headers=h, json={"item":{"@microsoft.graph.conflictBehavior":"rename"}}, timeout=30)
            if r2.status_code in (200,201): break
            else: errors.append(f"Format {i+1} → HTTP {r2.status_code}"); r2 = None
        except Exception as ex: errors.append(f"Format {i+1} → {ex}"); r2 = None
    if r2 is None: return False, f"❌ All upload attempts failed:\n{chr(10).join(errors)}"
    upload_url = r2.json().get("uploadUrl")
    if not upload_url: return False, f"❌ No uploadUrl in response"
    CHUNK = 5*1024*1024; total = len(data); uploaded = 0; file_web_url = None; last_pct = -1
    while uploaded < total:
        chunk = data[uploaded:uploaded+CHUNK]; chunk_end = uploaded+len(chunk)-1
        pct = int(uploaded/total*100)
        if pct//10 != last_pct//10:
            _cb(f"⬆️ Uploading… {pct}% ({uploaded//1048576} / {total//1048576} MB)")
            last_pct = pct
        r3 = requests.put(upload_url, data=chunk, timeout=180,
                          headers={"Content-Length":str(len(chunk)),"Content-Range":f"bytes {uploaded}-{chunk_end}/{total}","Content-Type":"video/mp4"})
        if r3.status_code in (200,201):
            try: file_web_url = r3.json().get("webUrl","")
            except: file_web_url = ""
        elif r3.status_code == 202: pass
        else: return False, f"Upload failed at byte {uploaded} (HTTP {r3.status_code})"
        uploaded += len(chunk)
    _cb(f"✅ Upload complete! ({total//1048576} MB)")
    return True, file_web_url or "https://onedrive.live.com"


def _check_template():
    if not INTRO_TPL.exists():
        st.error(f"❌ Intro template not found: `{INTRO_TPL}`"); st.stop()
    if INTRO_TPL.stat().st_size < 10000:
        st.error("❌ Intro template appears corrupt."); st.stop()


def _ensure_logo():
    if not SLC_LOGO.exists() or SLC_LOGO.stat().st_size < 100:
        import base64
        SLC_LOGO.parent.mkdir(parents=True, exist_ok=True)
        SLC_LOGO.write_bytes(base64.b64decode(_SLC_LOGO_B64))


_check_template()
_ensure_logo()

# ──────────────────────── QUEUE HELPERS ──────────────────────────────────
def _new_item(course_name, unit_number, orig_filename, video_bytes):
    return {
        "id":            uuid.uuid4().hex[:8],
        "course_name":   course_name,
        "unit_number":   unit_number,
        "orig_filename": orig_filename,
        "size_mb":       len(video_bytes) / 1048576,
        "video_bytes":   video_bytes,
        "status":        "pending",   # pending | processing | done | failed
        "result_data":   None,
        "result_filename": None,
        "error":         None,
        "secs":          None,
        "mb_out":        None,
        "od_url":        None,
    }


def _process_item(item: dict, bar_slot, msg_slot) -> dict:
    """Run the full merge pipeline for one queue item. Returns updated item dict."""
    item = dict(item)   # shallow copy so we don't mutate while iterating
    item["status"] = "processing"
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            raw = tmp / "raw.mp4"
            raw.write_bytes(item["video_bytes"])
            src_res = _probe_resolution(str(raw))

            msg_slot.info("⏳ **1/4** — Building intro, outro, normalising…")
            bar_slot.progress(10)

            results, errors = {}, {}
            def _job(name, fn, *args):
                try:    results[name] = fn(*args)
                except Exception as e: errors[name] = e

            with ThreadPoolExecutor(max_workers=1) as pool:
                # normalise runs in background (longest step)
                pool.submit(_job, "norm", normalise, raw, tmp/"norm.mp4")
                # intro & outro share INTRO_TPL — run sequentially to
                # avoid concurrent FFmpeg reads that fail on Windows
                _job("intro", make_intro, item["course_name"], item["unit_number"], "", tmp)
                _job("outro", make_outro, tmp)

            if errors:
                raise RuntimeError("; ".join(f"{k}: {v}" for k,v in errors.items()))

            msg_slot.info(f"⏳ **2/4** — Replacing watermarks ({src_res[0]}×{src_res[1]})…")
            bar_slot.progress(40)
            norm_clean = remove_notebooklm_watermark(
                results["norm"], tmp/"norm_clean.mp4", src_res, tmp,
                progress_cb=lambda s: msg_slot.info(f"⏳ **2/4** — {s}"))

            msg_slot.info("⏳ **3/4** — Adding 4-colour transition…")
            bar_slot.progress(65)
            with_trans = add_notebooklm_transition(results["intro"], norm_clean, tmp/"intro_and_main.mp4")

            msg_slot.info("⏳ **4/4** — Merging final segments…")
            bar_slot.progress(85)
            final = concat([with_trans, results["outro"]], tmp/"final.mp4", tmp)

            bar_slot.progress(100)
            data = final.read_bytes()
            safec = item["course_name"][:30].replace(" ","_")
            safeu = item["unit_number"].replace(" ","_").replace("|","")
            fn    = f"SLC_Video_{safec}_{safeu}.mp4"

            item["status"]          = "done"
            item["result_data"]     = data
            item["result_filename"] = fn
            item["secs"]            = time.time() - t0
            item["mb_out"]          = len(data) / 1048576

    except Exception as e:
        item["status"] = "failed"
        item["error"]  = str(e)

    return item


# ──────────────────────── SESSION STATE INIT ─────────────────────────────
if "queue" not in st.session_state:
    st.session_state["queue"] = []


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
.q-row{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.badge-pending{background:rgba(255,200,80,.15);color:#ffc850;border:1px solid rgba(255,200,80,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-processing{background:rgba(96,204,190,.15);color:#60ccbe;border:1px solid rgba(96,204,190,.4);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-done{background:rgba(80,200,120,.15);color:#50c878;border:1px solid rgba(80,200,120,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-failed{background:rgba(255,80,80,.15);color:#ff5050;border:1px solid rgba(255,80,80,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
</style>""", unsafe_allow_html=True)

# ──────────────────────── HEADER ──────────────────────────────────────────
st.markdown("""<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
  <h1 style="margin:0;font-size:28px">🎬 SLC Video Merger</h1>
  <span style="background:#60ccbe;color:#0a2a3c;font-size:11px;font-weight:700;
        padding:3px 12px;border-radius:20px;text-transform:uppercase">Queue</span>
</div>""", unsafe_allow_html=True)
st.markdown("""<div style="text-align:center;margin:8px 0 24px">
  <span class="fb">🎬 Custom Intro</span><span class="fa">→</span>
  <span class="fb">🟪🟦🟩⬜ Transition</span><span class="fa">→</span>
  <span class="fb">📹 NotebookLM Video</span><span class="fa">→</span>
  <span class="fb">🔚 Outro</span>
</div>""", unsafe_allow_html=True)

# ── OneDrive connection (top, so token is available everywhere) ───────────
if ONEDRIVE_AVAILABLE:
    _token = _get_access_token()
    with st.expander("☁  OneDrive Connection", expanded=not bool(_token)):
        if _token:
            st.success("✅ Connected — processed videos can be uploaded to the department folder.")
            if st.button("🔄 Switch / Re-connect", type="secondary", key="od_reset"):
                TOKEN_CACHE_FILE.unlink(missing_ok=True)
                st.session_state.pop("ms_flow", None); st.session_state.pop("ms_cache", None)
                st.rerun()
        else:
            st.markdown('<p style="font-size:13px;color:rgba(255,255,255,.7)">Sign in once — stays connected for all users.</p>', unsafe_allow_html=True)
            if "ms_flow" not in st.session_state:
                if st.button("🔑 Connect Department Microsoft Account"):
                    with st.spinner("Starting sign-in…"):
                        _start_device_flow()
                    st.rerun()
            else:
                flow = st.session_state["ms_flow"]
                st.markdown(f"""<div class="auth-box">
                <strong>Step 1</strong> — Open: <a href="{flow['verification_uri']}" target="_blank" style="color:#60ccbe">{flow['verification_uri']}</a><br><br>
                <strong>Step 2</strong> — Enter code: &nbsp;<code style="background:#1a3a5c;padding:4px 12px;border-radius:6px;font-size:18px;letter-spacing:3px;color:#60ccbe">{flow['user_code']}</code><br><br>
                <strong>Step 3</strong> — Sign in, then click below.
                </div>""", unsafe_allow_html=True)
                if st.button("✅ I've signed in — complete connection"):
                    with st.spinner("Completing sign-in…"):
                        ok, result = _complete_device_flow()
                    if ok: st.success("✅ Connected!"); st.rerun()
                    else:  st.error(f"Sign-in failed: {result}")

st.markdown("---")

# ── SECTION 1 — Add to Queue ──────────────────────────────────────────────
st.markdown('<div><span class="sn">1</span><span class="st">Add Video to Queue</span></div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    add_course = st.text_input("Course Name", key="add_course",
                               placeholder="e.g. Level 3 Diploma in Sports Development (RQF)")
with c2:
    add_unit = st.text_input("Unit / Chapter Number", key="add_unit",
                             placeholder="e.g. UNIT 03 | CHAPTER 06")

add_vid = st.file_uploader("Upload NotebookLM Video", type=["mp4","mov","webm","avi","mkv"],
                           help="Up to 500 MB per file", key="add_vid")

col_prev, col_add = st.columns([1, 2])
with col_prev:
    if st.button("👁 Preview Intro", type="secondary", key="btn_preview"):
        if add_course and add_unit:
            with st.spinner("Rendering…"):
                st.image(preview_frame(add_course, add_unit, ""), caption="Intro Preview", use_container_width=True)
        else:
            st.warning("Enter course name and unit number first.")

with col_add:
    if st.button("➕ Add to Queue", type="primary", use_container_width=True, key="btn_add"):
        if not add_course:
            st.error("Enter a course name.")
        elif not add_unit:
            st.error("Enter a unit number.")
        elif not add_vid:
            st.error("Upload a video file.")
        else:
            item = _new_item(add_course, add_unit, add_vid.name, add_vid.getvalue())
            st.session_state["queue"].append(item)
            st.success(f"✅ **{add_vid.name}** added to queue ({item['size_mb']:.1f} MB)")
            st.rerun()

st.markdown("---")

# ── SECTION 2 — Queue Manager ─────────────────────────────────────────────
queue: list = st.session_state["queue"]

pending_count    = sum(1 for i in queue if i["status"] == "pending")
processing_count = sum(1 for i in queue if i["status"] == "processing")
done_count       = sum(1 for i in queue if i["status"] == "done")
failed_count     = sum(1 for i in queue if i["status"] == "failed")

st.markdown(
    f'<div><span class="sn">2</span>'
    f'<span class="st">Queue</span>'
    f'&nbsp;&nbsp;<span style="font-size:13px;color:rgba(255,255,255,.5)">'
    f'{len(queue)} item{"s" if len(queue)!=1 else ""} &nbsp;·&nbsp; '
    f'🟡 {pending_count} pending &nbsp;·&nbsp; '
    f'✅ {done_count} done &nbsp;·&nbsp; '
    f'❌ {failed_count} failed'
    f'</span></div>',
    unsafe_allow_html=True
)

if not queue:
    st.markdown('<p style="color:rgba(255,255,255,.35);font-size:14px;margin:16px 0 0 38px">'
                'No videos queued yet — add one above.</p>', unsafe_allow_html=True)
else:
    # ── Queue rows ────────────────────────────────────────────────────────
    for idx, item in enumerate(queue):
        status  = item["status"]
        badge   = {
            "pending":    '<span class="badge-pending">🟡 Pending</span>',
            "processing": '<span class="badge-processing">🔵 Processing</span>',
            "done":       '<span class="badge-done">✅ Done</span>',
            "failed":     '<span class="badge-failed">❌ Failed</span>',
        }.get(status, status)

        size_str = f"{item['size_mb']:.1f} MB in"
        if item.get("mb_out"):
            size_str += f" · {item['mb_out']:.1f} MB out"
        if item.get("secs"):
            size_str += f" · {item['secs']:.0f}s"

        st.markdown(f"""<div class="q-row">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <span style="font-weight:700;color:rgba(255,255,255,.4);font-size:12px">#{idx+1}</span>
              {badge}
              <span style="font-weight:600;color:#fff">{item['course_name']}</span>
              <span style="color:rgba(96,204,190,.8);font-size:13px">{item['unit_number']}</span>
              <span style="color:rgba(255,255,255,.35);font-size:12px">{item['orig_filename']} · {size_str}</span>
            </div>
        </div>""", unsafe_allow_html=True)

        # Action buttons per item
        btn_cols = st.columns([1, 1, 1, 1, 3])
        with btn_cols[0]:
            if status in ("pending", "failed"):
                if st.button("🗑 Remove", key=f"rm_{item['id']}"):
                    st.session_state["queue"] = [q for q in queue if q["id"] != item["id"]]
                    st.rerun()
        with btn_cols[1]:
            if status == "failed" and item.get("error"):
                st.button("⚠️ Error", key=f"err_{item['id']}",
                          help=item["error"], type="secondary")
        with btn_cols[2]:
            if status == "done" and item.get("result_data"):
                st.download_button(
                    "⬇ Download",
                    data=item["result_data"],
                    file_name=item["result_filename"],
                    mime="video/mp4",
                    key=f"dl_{item['id']}",
                )
        with btn_cols[3]:
            current_token = _get_access_token() if ONEDRIVE_AVAILABLE else None
            if status == "done" and item.get("result_data") and current_token:
                od_label = "✅ Uploaded" if item.get("od_url") else "☁ Upload"
                if not item.get("od_url"):
                    if st.button(od_label, key=f"od_{item['id']}"):
                        with st.spinner(f"Uploading {item['result_filename']}…"):
                            logs = []
                            ok, result = _onedrive_upload(
                                item["result_data"], item["result_filename"], "",
                                current_token,
                                status_cb=lambda s: logs.append(s),
                                folder_url=ONEDRIVE_FOLDER_URL,
                            )
                        if ok:
                            # Update item in queue
                            for q in st.session_state["queue"]:
                                if q["id"] == item["id"]:
                                    q["od_url"] = result
                            st.success(f"✅ Uploaded! [Open]({result})")
                            st.rerun()
                        else:
                            st.error(result)
                else:
                    st.markdown(f'<a href="{item["od_url"]}" target="_blank" '
                                f'style="color:#50c878;font-size:13px">✅ On OneDrive</a>',
                                unsafe_allow_html=True)

    st.markdown("")

    # ── Queue control buttons ─────────────────────────────────────────────
    qcol1, qcol2, qcol3 = st.columns([2, 1, 1])

    with qcol1:
        process_disabled = pending_count == 0
        if st.button(
            f"🎬 Process Queue  ({pending_count} pending)",
            type="primary",
            use_container_width=True,
            disabled=process_disabled,
            key="btn_process",
        ):
            # Process all pending items sequentially
            overall_bar  = st.progress(0, "Starting queue…")
            overall_msg  = st.empty()
            item_bar     = st.progress(0)
            item_msg     = st.empty()

            pending_ids = [i["id"] for i in st.session_state["queue"] if i["status"] == "pending"]
            total_jobs  = len(pending_ids)

            for job_idx, iid in enumerate(pending_ids):
                # Find item in live queue list
                item_ref = next((q for q in st.session_state["queue"] if q["id"] == iid), None)
                if item_ref is None:
                    continue

                overall_msg.info(
                    f"**Job {job_idx+1} / {total_jobs}** — "
                    f"{item_ref['course_name']} · {item_ref['unit_number']}"
                )
                overall_bar.progress((job_idx) / total_jobs,
                                     f"Processing {job_idx+1}/{total_jobs}…")
                item_bar.progress(0)
                item_msg.empty()

                updated = _process_item(item_ref, item_bar, item_msg)

                # Write back into queue
                for q in st.session_state["queue"]:
                    if q["id"] == iid:
                        q.update(updated)
                        break

            overall_bar.progress(1.0, "Queue complete!")
            item_bar.empty()
            item_msg.empty()
            time.sleep(0.8)
            overall_bar.empty(); overall_msg.empty()
            st.rerun()

    with qcol2:
        if st.button("🗑 Clear Done", type="secondary", use_container_width=True, key="btn_clear_done"):
            st.session_state["queue"] = [q for q in queue if q["status"] != "done"]
            st.rerun()

    with qcol3:
        if st.button("🗑 Clear All", type="secondary", use_container_width=True, key="btn_clear_all"):
            st.session_state["queue"] = []
            st.rerun()

    # ── Bulk OneDrive upload for all done items ───────────────────────────
    current_token = _get_access_token() if ONEDRIVE_AVAILABLE else None
    uploadable = [q for q in queue if q["status"] == "done" and not q.get("od_url") and q.get("result_data")]
    if uploadable and current_token:
        st.markdown("---")
        st.markdown('<div style="margin:4px 0 12px"><span class="sn">☁</span>'
                    '<span class="st">Bulk OneDrive Upload</span></div>', unsafe_allow_html=True)
        if st.button(f"☁ Upload All to OneDrive  ({len(uploadable)} files)",
                     use_container_width=True, key="btn_od_all"):
            bulk_bar = st.progress(0)
            bulk_msg = st.empty()
            for i, item in enumerate(uploadable):
                bulk_msg.info(f"Uploading {i+1}/{len(uploadable)}: {item['result_filename']}")
                bulk_bar.progress((i) / len(uploadable))
                ok, result = _onedrive_upload(
                    item["result_data"], item["result_filename"], "",
                    current_token, folder_url=ONEDRIVE_FOLDER_URL,
                )
                for q in st.session_state["queue"]:
                    if q["id"] == item["id"]:
                        q["od_url"] = result if ok else "error"
            bulk_bar.progress(1.0)
            bulk_msg.success(f"✅ Uploaded {len(uploadable)} files!")
            time.sleep(1)
            bulk_bar.empty(); bulk_msg.empty()
            st.rerun()

st.markdown("---")

# ── Results preview (expandable per done item) ────────────────────────────
done_items = [q for q in st.session_state["queue"] if q["status"] == "done"]
if done_items:
    st.markdown('<div><span class="sn">3</span><span class="st">Preview Results</span></div>',
                unsafe_allow_html=True)
    for item in done_items:
        with st.expander(f"▶  {item['course_name']} — {item['unit_number']}", expanded=False):
            st.video(item["result_data"], format="video/mp4")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇ Download", data=item["result_data"],
                                   file_name=item["result_filename"], mime="video/mp4",
                                   use_container_width=True, key=f"dlp_{item['id']}")
            with c2:
                if item.get("od_url") and item["od_url"] != "error":
                    st.markdown(f'<a href="{item["od_url"]}" target="_blank" '
                                f'style="color:#50c878">✅ View on OneDrive</a>',
                                unsafe_allow_html=True)
