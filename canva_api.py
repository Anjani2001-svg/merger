"""
Canva Connect API integration.
OAuth 2.0 with PKCE + Asset Upload + Create Design + Open Editor.
"""

import os
import hashlib
import secrets
import base64
import time
import json
from urllib.parse import urlencode

import requests
import streamlit as st

CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_UPLOAD_URL = "https://api.canva.com/rest/v1/asset-uploads"
CANVA_UPLOAD_JOB_URL = "https://api.canva.com/rest/v1/asset-uploads/{job_id}"
CANVA_CREATE_DESIGN = "https://api.canva.com/rest/v1/designs"
CANVA_GET_DESIGN = "https://api.canva.com/rest/v1/designs/{design_id}"


def _get_credentials():
    cid = None
    sec = None

    try:
        cid = st.secrets.get("CANVA_CLIENT_ID", None)
        sec = st.secrets.get("CANVA_CLIENT_SECRET", None)
    except Exception:
        pass

    if not cid:
        cid = os.environ.get("CANVA_CLIENT_ID", "")
    if not sec:
        sec = os.environ.get("CANVA_CLIENT_SECRET", "")

    return cid, sec


def is_configured():
    cid, sec = _get_credentials()
    return bool(cid and sec)


def is_connected():
    return bool(st.session_state.get("canva_access_token"))


def _generate_pkce():
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def get_redirect_uri():
    try:
        uri = st.secrets.get("CANVA_REDIRECT_URI", None)
        if uri:
            return uri
    except Exception:
        pass

    return os.environ.get("CANVA_REDIRECT_URI", "http://127.0.0.1:8501/")


def start_auth_flow():
    cid, _ = _get_credentials()
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    st.session_state["canva_code_verifier"] = verifier
    st.session_state["canva_auth_state"] = state

    redirect_uri = get_redirect_uri()

    params = {
        "code_challenge": challenge,
        "code_challenge_method": "s256",
        "scope": "asset:write asset:read design:write design:read",
        "response_type": "code",
        "client_id": cid,
        "state": state,
        "redirect_uri": redirect_uri,
    }
    return CANVA_AUTH_URL + "?" + urlencode(params)


def handle_callback(query_params):
    code = query_params.get("code", [None])
    state = query_params.get("state", [None])

    if isinstance(code, list):
        code = code[0] if code else None
    if isinstance(state, list):
        state = state[0] if state else None

    if not code:
        return False

    expected_state = st.session_state.get("canva_auth_state", "")
    if state != expected_state:
        st.error("OAuth state mismatch. Please try again.")
        return False

    cid, secret = _get_credentials()
    verifier = st.session_state.get("canva_code_verifier", "")
    redirect_uri = get_redirect_uri()

    body = {
        "grant_type": "authorization_code",
        "code_verifier": verifier,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    auth_str = base64.b64encode(f"{cid}:{secret}".encode("utf-8")).decode("ascii")

    try:
        resp = requests.post(
            CANVA_TOKEN_URL,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_str}",
            },
            timeout=20,
        )

        if resp.status_code == 200:
            data = resp.json()
            st.session_state["canva_access_token"] = data["access_token"]
            st.session_state["canva_refresh_token"] = data.get("refresh_token", "")
            st.session_state["canva_token_expiry"] = time.time() + data.get("expires_in", 14400)
            return True

        st.error(f"Canva token exchange failed: {resp.status_code} — {resp.text[:300]}")
        return False

    except Exception as e:
        st.error(f"Canva auth error: {e}")
        return False


def refresh_token_if_needed():
    expiry = st.session_state.get("canva_token_expiry", 0)
    if time.time() < expiry - 300:
        return True

    refresh = st.session_state.get("canva_refresh_token", "")
    if not refresh:
        return False

    cid, secret = _get_credentials()
    auth_str = base64.b64encode(f"{cid}:{secret}".encode("utf-8")).decode("ascii")

    try:
        resp = requests.post(
            CANVA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_str}",
            },
            timeout=20,
        )

        if resp.status_code == 200:
            data = resp.json()
            st.session_state["canva_access_token"] = data["access_token"]
            st.session_state["canva_refresh_token"] = data.get("refresh_token", refresh)
            st.session_state["canva_token_expiry"] = time.time() + data.get("expires_in", 14400)
            return True
    except Exception:
        pass

    return False


def upload_video(video_bytes, filename="SLC_Video.mp4"):
    if not refresh_token_if_needed():
        return False, "Canva token expired. Please reconnect.", None

    token = st.session_state.get("canva_access_token", "")
    if not token:
        return False, "Not connected to Canva.", None

    name_b64 = base64.b64encode(filename.encode("utf-8")).decode("ascii")
    metadata = json.dumps({"name_base64": name_b64})

    try:
        resp = requests.post(
            CANVA_UPLOAD_URL,
            data=video_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Asset-Upload-Metadata": metadata,
            },
            timeout=120,
        )

        if resp.status_code not in (200, 201):
            return False, f"Canva API error {resp.status_code}: {resp.text[:300]}", None

        data = resp.json()
        job_id = data.get("job", {}).get("id", "")

        if not job_id:
            return False, "Upload started but no job ID was returned.", None

        for _ in range(45):
            time.sleep(2)
            poll = requests.get(
                CANVA_UPLOAD_JOB_URL.format(job_id=job_id),
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )

            if poll.status_code == 200:
                pdata = poll.json()
                job = pdata.get("job", {})
                status = job.get("status", "")

                if status == "success":
                    asset_id = job.get("asset", {}).get("id", "")
                    return True, "Uploaded to Canva successfully.", asset_id

                if status == "failed":
                    err = job.get("error", {}).get("message", "Unknown error")
                    return False, f"Canva upload failed: {err}", None

        return False, "Upload timed out. Check Canva Uploads manually.", None

    except Exception as e:
        return False, f"Upload error: {e}", None


def create_blank_video_design(title="SLC Video Edit"):
    if not refresh_token_if_needed():
        return False, "Canva token expired. Please reconnect.", None

    token = st.session_state.get("canva_access_token", "")
    if not token:
        return False, "Not connected to Canva.", None

    body = {
        "design_type": {
            "type": "custom",
            "width": 1920,
            "height": 1080,
        },
        "title": title,
    }

    try:
        resp = requests.post(
            CANVA_CREATE_DESIGN,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            return False, f"Create design failed: {resp.status_code} - {resp.text[:300]}", None

        data = resp.json()
        design_id = data.get("design", {}).get("id", "")

        if not design_id:
            return False, "Design created but no design ID was returned.", None

        return True, "Design created successfully.", design_id

    except Exception as e:
        return False, f"Create design error: {e}", None


def get_design_edit_url(design_id):
    if not refresh_token_if_needed():
        return False, "Canva token expired. Please reconnect.", None

    token = st.session_state.get("canva_access_token", "")
    if not token:
        return False, "Not connected to Canva.", None

    try:
        resp = requests.get(
            CANVA_GET_DESIGN.format(design_id=design_id),
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )

        if resp.status_code != 200:
            return False, f"Get design failed: {resp.status_code} - {resp.text[:300]}", None

        data = resp.json()
        design = data.get("design", {})
        urls = design.get("urls", {}) if isinstance(design.get("urls", {}), dict) else {}
        edit_url = urls.get("edit_url") or urls.get("edit") or design.get("edit_url")

        if not edit_url:
            return False, "No edit URL returned for this design.", None

        return True, "Editor URL retrieved.", edit_url

    except Exception as e:
        return False, f"Get design error: {e}", None


def upload_video_and_open_editor(video_bytes, filename="SLC_Video.mp4"):
    ok, msg, asset_id = upload_video(video_bytes, filename)
    if not ok:
        return False, msg, None

    title = os.path.splitext(filename)[0]
    ok, msg, design_id = create_blank_video_design(title=title)
    if not ok:
        return False, msg, None

    ok, msg, edit_url = get_design_edit_url(design_id)
    if not ok:
        return False, msg, None

    return True, "Uploaded and Canva editor opened successfully.", {
        "asset_id": asset_id,
        "design_id": design_id,
        "edit_url": edit_url,
    }


def disconnect():
    for key in [
        "canva_access_token",
        "canva_refresh_token",
        "canva_token_expiry",
        "canva_code_verifier",
        "canva_auth_state",
    ]:
        st.session_state.pop(key, None)
