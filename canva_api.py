"""
Canva Connect API integration.
OAuth 2.0 with PKCE + Asset Upload for video files.
"""

import os, hashlib, secrets, base64, time, json
from urllib.parse import urlencode, quote
import requests
import streamlit as st

# ── Canva API endpoints ──
CANVA_AUTH_URL   = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL  = "https://api.canva.com/rest/v1/oauth/token"
CANVA_UPLOAD_URL = "https://api.canva.com/rest/v1/asset-uploads"
CANVA_UPLOAD_JOB = "https://api.canva.com/rest/v1/asset-uploads/{job_id}"


def _get_credentials():
    """Get Canva Client ID and Secret from Streamlit secrets or env."""
    cid = None
    sec = None
    # Try Streamlit secrets first (for Streamlit Cloud)
    try:
        cid = st.secrets.get("CANVA_CLIENT_ID", None)
        sec = st.secrets.get("CANVA_CLIENT_SECRET", None)
    except Exception:
        pass
    # Fallback to env vars (for local dev)
    if not cid:
        cid = os.environ.get("CANVA_CLIENT_ID", "")
    if not sec:
        sec = os.environ.get("CANVA_CLIENT_SECRET", "")
    return cid, sec


def is_configured():
    """Check if Canva API credentials are set."""
    cid, sec = _get_credentials()
    return bool(cid and sec)


def is_connected():
    """Check if user has a valid Canva access token."""
    return bool(st.session_state.get("canva_access_token"))


def _generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest   = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def get_redirect_uri():
    """Build the redirect URI for the current Streamlit app."""
    # For Streamlit Cloud, use the app's URL
    # For local dev, use localhost
    try:
        # Try to get from secrets
        uri = st.secrets.get("CANVA_REDIRECT_URI", None)
        if uri:
            return uri
    except Exception:
        pass
    # Fallback: construct from current URL or default
    return os.environ.get("CANVA_REDIRECT_URI", "http://127.0.0.1:8501/")


def start_auth_flow():
    """Generate the Canva authorization URL and store PKCE state."""
    cid, _ = _get_credentials()
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    # Store PKCE verifier and state in session
    st.session_state["canva_code_verifier"] = verifier
    st.session_state["canva_auth_state"]    = state

    redirect_uri = get_redirect_uri()

    params = {
        "code_challenge":        challenge,
        "code_challenge_method": "s256",
        "scope":                 "asset:write asset:read",
        "response_type":         "code",
        "client_id":             cid,
        "state":                 state,
        "redirect_uri":          redirect_uri,
    }
    url = CANVA_AUTH_URL + "?" + urlencode(params)
    return url


def handle_callback(query_params):
    """Exchange the auth code from Canva callback for an access token.
    Returns True if successful."""
    code  = query_params.get("code", [None])
    state = query_params.get("state", [None])

    # Handle both list and string returns from st.query_params
    if isinstance(code, list):  code  = code[0]  if code  else None
    if isinstance(state, list): state = state[0] if state else None

    if not code:
        return False

    # Verify state matches
    expected_state = st.session_state.get("canva_auth_state", "")
    if state != expected_state:
        st.error("OAuth state mismatch — possible CSRF attack. Please try again.")
        return False

    # Exchange code for token
    cid, secret = _get_credentials()
    verifier     = st.session_state.get("canva_code_verifier", "")
    redirect_uri = get_redirect_uri()

    body = {
        "grant_type":    "authorization_code",
        "code_verifier": verifier,
        "code":          code,
        "redirect_uri":  redirect_uri,
    }

    # Basic auth: base64(client_id:client_secret)
    auth_str = base64.b64encode(f"{cid}:{secret}".encode()).decode()

    try:
        resp = requests.post(
            CANVA_TOKEN_URL,
            data=body,
            headers={
                "Content-Type":  "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_str}",
            },
            timeout=15,
        )

        if resp.status_code == 200:
            data = resp.json()
            st.session_state["canva_access_token"]  = data["access_token"]
            st.session_state["canva_refresh_token"] = data.get("refresh_token", "")
            st.session_state["canva_token_expiry"]  = time.time() + data.get("expires_in", 14400)
            return True
        else:
            st.error(f"Canva token exchange failed: {resp.status_code} — {resp.text[:300]}")
            return False

    except Exception as e:
        st.error(f"Canva auth error: {e}")
        return False


def refresh_token_if_needed():
    """Refresh the access token if it's about to expire."""
    expiry = st.session_state.get("canva_token_expiry", 0)
    if time.time() < expiry - 300:  # 5 min buffer
        return True

    refresh = st.session_state.get("canva_refresh_token", "")
    if not refresh:
        return False

    cid, secret = _get_credentials()
    auth_str = base64.b64encode(f"{cid}:{secret}".encode()).decode()

    try:
        resp = requests.post(
            CANVA_TOKEN_URL,
            data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh,
            },
            headers={
                "Content-Type":  "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_str}",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["canva_access_token"]  = data["access_token"]
            st.session_state["canva_refresh_token"] = data.get("refresh_token", refresh)
            st.session_state["canva_token_expiry"]  = time.time() + data.get("expires_in", 14400)
            return True
    except Exception:
        pass
    return False


def upload_video(video_bytes, filename="SLC_Video.mp4"):
    """Upload a video to the user's Canva asset library.
    Returns (success, message)."""

    if not refresh_token_if_needed():
        return False, "Canva token expired. Please reconnect."

    token = st.session_state.get("canva_access_token", "")
    if not token:
        return False, "Not connected to Canva."

    # Encode filename as base64 for the metadata header
    name_b64 = base64.b64encode(filename.encode("utf-8")).decode("ascii")
    metadata = json.dumps({"name_base64": name_b64})

    try:
        resp = requests.post(
            CANVA_UPLOAD_URL,
            data=video_bytes,
            headers={
                "Authorization":         f"Bearer {token}",
                "Content-Type":          "application/octet-stream",
                "Asset-Upload-Metadata": metadata,
            },
            timeout=120,
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            job_id = data.get("job", {}).get("id", "")

            # Poll for completion
            for _ in range(30):
                time.sleep(2)
                poll = requests.get(
                    CANVA_UPLOAD_JOB.format(job_id=job_id),
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                if poll.status_code == 200:
                    pdata = poll.json()
                    status = pdata.get("job", {}).get("status", "")
                    if status == "success":
                        asset_id = pdata.get("job", {}).get("asset", {}).get("id", "")
                        return True, f"Uploaded to Canva! Asset ID: {asset_id}"
                    elif status == "failed":
                        err = pdata.get("job", {}).get("error", {}).get("message", "Unknown error")
                        return False, f"Canva upload failed: {err}"
                    # Still processing, continue polling

            return False, "Upload timed out — check Canva manually."

        else:
            return False, f"Canva API error {resp.status_code}: {resp.text[:300]}"

    except Exception as e:
        return False, f"Upload error: {e}"


def disconnect():
    """Clear Canva session tokens."""
    for key in ["canva_access_token", "canva_refresh_token",
                "canva_token_expiry", "canva_code_verifier", "canva_auth_state"]:
        st.session_state.pop(key, None)
