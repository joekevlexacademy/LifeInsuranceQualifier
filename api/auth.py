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
    "locations.readonly",
    "custom-menu-link.readonly",
    "custom-menu-link.write",
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


async def save_api_key_installation(company_id: str, location_id: str, api_key: str) -> None:
    """Store a GHL Private Integration key as the location's access credential."""
    sb = _sb()
    far_future = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
    sb.table("installations").upsert({
        "location_id": location_id,
        "agency_id": company_id,
        "access_token": api_key,
        "refresh_token": "",
        "expires_at": far_future,
        "uninstalled_at": None,
    }).execute()


async def get_agency_id(location_id: str) -> str | None:
    """Look up the company/agency id stored alongside a location's installation row."""
    sb = _sb()
    rows = (
        sb.table("installations")
        .select("agency_id")
        .eq("location_id", location_id)
        .execute()
    )
    if rows.data and rows.data[0].get("agency_id"):
        return rows.data[0]["agency_id"]
    return None


async def get_valid_token(location_id: str) -> str:
    sb = _sb()

    def _first(rows) -> dict | None:
        return rows.data[0] if rows.data else None

    # Try direct location match first
    record = _first(
        sb.table("installations")
        .select("access_token, expires_at, location_id, refresh_token")
        .eq("location_id", location_id)
        .execute()
    )

    # Fall back to company-level install
    if not record:
        record = _first(
            sb.table("installations")
            .select("access_token, expires_at, location_id, refresh_token")
            .eq("agency_id", location_id)
            .execute()
        )

    if not record:
        raise ValueError(f"No installation found for location_id: {location_id}")

    # Private Integration keys have no refresh_token — they don't expire
    if not record.get("refresh_token"):
        return record["access_token"]

    resolved_id = record["location_id"]
    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5):
        return await _refresh(resolved_id)

    return record["access_token"]


async def ensure_location_installation(company_id: str, location_id: str) -> None:
    """Create a location row from the company token only if one does not already exist.
    Never overwrites an existing row so stored PIKs are never clobbered."""
    sb = _sb()
    # If a row already exists for this location (e.g. a PIK was saved), leave it alone.
    existing = sb.table("installations").select("location_id").eq("location_id", location_id).execute()
    if existing.data:
        return
    rows = sb.table("installations").select("*").eq("location_id", company_id).execute()
    if not rows.data:
        raise ValueError(f"No company installation found for: {company_id}")
    src = rows.data[0]
    sb.table("installations").insert({
        "location_id": location_id,
        "agency_id": company_id,
        "access_token": src["access_token"],
        "refresh_token": src["refresh_token"],
        "expires_at": src["expires_at"],
        "uninstalled_at": None,
    }).execute()


async def save_installation(token_data: dict) -> str:
    sb = _sb()
    location_id = token_data.get("locationId") or token_data.get("companyId")
    if not location_id:
        raise ValueError(f"No locationId or companyId in token response: {list(token_data.keys())}")
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
