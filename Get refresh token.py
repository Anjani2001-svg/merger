#!/usr/bin/env python3
"""
Run this ONCE locally to get a refresh token for the SLC Video Merger.
Paste the printed refresh_token into your .streamlit/secrets.toml

Requirements:
    pip install google-auth-oauthlib

Usage:
    python get_refresh_token.py
"""
from google_auth_oauthlib.flow import InstalledAppFlow

# ── Paste your OAuth Desktop client ID + secret from Google Cloud Console ──
CLIENT_ID     = "PASTE_YOUR_CLIENT_ID_HERE.apps.googleusercontent.com"
CLIENT_SECRET = "PASTE_YOUR_CLIENT_SECRET_HERE"

SCOPES = ["https://www.googleapis.com/auth/drive"]

client_config = {
    "installed": {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

print("\n" + "=" * 70)
print("SUCCESS - copy these three values into .streamlit/secrets.toml")
print("=" * 70)
print(f"""
[gdrive_oauth]
client_id     = "{CLIENT_ID}"
client_secret = "{CLIENT_SECRET}"
refresh_token = "{creds.refresh_token}"
""")
