import os
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
from supabase import create_client

GHL_TOKEN_URL = "https://services.leadconnectorhq.com/oauth/token"
# Supports standard GHL domain and white-label custom domains.
# Set GHL_OAUTH_DOMAIN in Railway env vars if using a custom domain (e.g. app.hatch.insure).
# Defaults to marketplace.gohighlevel.com if not set.
_GHL_OAUTH_DOMAIN = os.environ.get("GHL_OAUTH_DOMAIN", "marketplace.gohighlevel.com")
GHL_OAUTH_BASE = f"https://{_GHL_OAUTH_DOMAIN}/v2/oauth/chooselocation"

GHL_SCOPES = " ".join([
    "contacts.readonly",
    "contacts.write",
    "locations.readonly",
    "customFields.readonly",
    "customFields.write",
    "notes.write",
])


def _sb():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def get_oauth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": os.environ["GHL_CLIENT_ID"],
        "redirect_uri": f"{os.environ['APP_BASE_URL']}/oauth/callback",
        "scope": GHL_SCOPES,
    }
    return f"{GHL_OAUTH_BASE}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            GHL_TOKEN_URL,
            data={
                "client_id": os.environ["GHL_CLIENT_ID"],
                "client_secret": os.environ["GHL_CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{os.environ['APP_BASE_URL']}/oauth/callback",
            },
        )
        r.raise_for_status()
        return r.json()


async def _refresh(location_id: str) -> str:
    sb = _sb()
    row = (
        sb.table("installations")
        .select("refresh_token")
        .eq("location_id", location_id)
        .single()
        .execute()
    )
    refresh_token = row.data["refresh_token"]

    async with httpx.AsyncClient() as client:
        r = await client.post(
            GHL_TOKEN_URL,
            data={
                "client_id": os.environ["GHL_CLIENT_ID"],
                "client_secret": os.environ["GHL_CLIENT_SECRET"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        r.raise_for_status()
        data = r.json()

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
    sb.table("installations").update(
        {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_token),
            "expires_at": expires_at.isoformat(),
        }
    ).eq("location_id", location_id).execute()

    return data["access_token"]


async def get_valid_token(location_id: str) -> str:
    sb = _sb()
    row = (
        sb.table("installations")
        .select("access_token, expires_at")
        .eq("location_id", location_id)
        .single()
        .execute()
    )
    if not row.data:
        raise ValueError(f"No installation found for location_id: {location_id}")

    expires_at = datetime.fromisoformat(row.data["expires_at"])
    if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5):
        return await _refresh(location_id)

    return row.data["access_token"]


async def save_installation(token_data: dict) -> str:
    sb = _sb()
    location_id = token_data["locationId"]
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    sb.table("installations").upsert(
        {
            "location_id": location_id,
            "agency_id": token_data.get("companyId", ""),
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_at": expires_at.isoformat(),
            "uninstalled_at": None,
        }
    ).execute()

    return location_id
