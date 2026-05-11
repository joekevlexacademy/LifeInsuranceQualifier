import os
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
import psycopg2.extras

from .db import get_conn

GHL_TOKEN_URL = "https://services.leadconnectorhq.com/oauth/token"
_GHL_OAUTH_DOMAIN = os.environ.get("GHL_OAUTH_DOMAIN", "marketplace.gohighlevel.com")
GHL_OAUTH_BASE = f"https://{_GHL_OAUTH_DOMAIN}/v2/oauth/chooselocation"

GHL_SCOPES = " ".join([
    "locations.readonly",
    "custom-menu-link.readonly",
    "custom-menu-link.write",
])


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
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT refresh_token FROM installations WHERE location_id = %s",
                (location_id,),
            )
            row = cur.fetchone()
    refresh_token = row["refresh_token"]

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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE installations SET access_token=%s, refresh_token=%s, expires_at=%s WHERE location_id=%s",
                (data["access_token"], data.get("refresh_token", refresh_token), expires_at, location_id),
            )
    return data["access_token"]


async def save_api_key_installation(company_id: str, location_id: str, api_key: str) -> None:
    far_future = datetime.now(timezone.utc) + timedelta(days=36500)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO installations (location_id, agency_id, access_token, refresh_token, expires_at, uninstalled_at)
                VALUES (%s, %s, %s, '', %s, NULL)
                ON CONFLICT (location_id) DO UPDATE SET
                    agency_id      = EXCLUDED.agency_id,
                    access_token   = EXCLUDED.access_token,
                    refresh_token  = '',
                    expires_at     = EXCLUDED.expires_at,
                    uninstalled_at = NULL
                """,
                (location_id, company_id, api_key, far_future),
            )


async def get_agency_key(company_id: str) -> str | None:
    if not company_id:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT access_token, expires_at, refresh_token FROM installations WHERE location_id = %s",
                (company_id,),
            )
            record = cur.fetchone()

    if not record:
        return None
    if not record["refresh_token"]:
        return record["access_token"] or None
    try:
        expires_at = datetime.fromisoformat(str(record["expires_at"]))
        if expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return record["access_token"]
        return await _refresh(company_id)
    except Exception:
        return None


async def save_agency_key(company_id: str, api_key: str) -> None:
    if not company_id:
        return
    far_future = datetime.now(timezone.utc) + timedelta(days=36500)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM installations WHERE location_id IS NULL")
            cur.execute(
                """
                INSERT INTO installations (location_id, agency_id, access_token, refresh_token, expires_at, uninstalled_at)
                VALUES (%s, %s, %s, '', %s, NULL)
                ON CONFLICT (location_id) DO UPDATE SET
                    agency_id      = EXCLUDED.agency_id,
                    access_token   = EXCLUDED.access_token,
                    refresh_token  = '',
                    expires_at     = EXCLUDED.expires_at,
                    uninstalled_at = NULL
                """,
                (company_id, company_id, api_key, far_future),
            )


async def get_any_menu_token() -> str | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT access_token, expires_at, location_id, refresh_token FROM installations WHERE refresh_token != '' LIMIT 5"
            )
            rows = cur.fetchall()

    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    for row in rows:
        try:
            if datetime.fromisoformat(str(row["expires_at"])) > now:
                return row["access_token"]
            return await _refresh(row["location_id"])
        except Exception:
            continue
    return None


async def get_agency_id(location_id: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT agency_id FROM installations WHERE location_id = %s",
                (location_id,),
            )
            row = cur.fetchone()
    return row["agency_id"] if row and row.get("agency_id") else None


async def get_valid_token(location_id: str) -> str:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT access_token, expires_at, location_id, refresh_token FROM installations WHERE location_id = %s",
                (location_id,),
            )
            record = cur.fetchone()
            if not record:
                cur.execute(
                    "SELECT access_token, expires_at, location_id, refresh_token FROM installations WHERE agency_id = %s LIMIT 1",
                    (location_id,),
                )
                record = cur.fetchone()

    if not record:
        raise ValueError(f"No installation found for location_id: {location_id}")

    if not record["refresh_token"]:
        return record["access_token"]

    resolved_id = record["location_id"]
    expires_at = datetime.fromisoformat(str(record["expires_at"]))
    if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5):
        return await _refresh(resolved_id)

    return record["access_token"]


async def ensure_location_installation(company_id: str, location_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT location_id FROM installations WHERE location_id = %s",
                (location_id,),
            )
            if cur.fetchone():
                return
            cur.execute(
                "SELECT * FROM installations WHERE location_id = %s",
                (company_id,),
            )
            src = cur.fetchone()
            if not src:
                raise ValueError(f"No company installation found for: {company_id}")
            cur.execute(
                """
                INSERT INTO installations (location_id, agency_id, access_token, refresh_token, expires_at, uninstalled_at)
                VALUES (%s, %s, %s, %s, %s, NULL)
                """,
                (location_id, company_id, src["access_token"], src["refresh_token"], src["expires_at"]),
            )


async def save_installation(token_data: dict) -> str:
    location_id = token_data.get("locationId") or token_data.get("companyId")
    if not location_id:
        raise ValueError(f"No locationId or companyId in token response: {list(token_data.keys())}")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO installations (location_id, agency_id, access_token, refresh_token, expires_at, uninstalled_at)
                VALUES (%s, %s, %s, %s, %s, NULL)
                ON CONFLICT (location_id) DO UPDATE SET
                    agency_id      = EXCLUDED.agency_id,
                    access_token   = EXCLUDED.access_token,
                    refresh_token  = EXCLUDED.refresh_token,
                    expires_at     = EXCLUDED.expires_at,
                    uninstalled_at = NULL
                """,
                (
                    location_id,
                    token_data.get("companyId", ""),
                    token_data["access_token"],
                    token_data["refresh_token"],
                    expires_at,
                ),
            )
    return location_id
