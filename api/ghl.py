import httpx
from typing import Optional

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
    }


async def get_location(access_token: str, location_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/{location_id}",
            headers=_headers(access_token),
        )
        r.raise_for_status()
        return r.json().get("location", {})


async def get_contact(access_token: str, contact_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(access_token),
        )
        r.raise_for_status()
        return r.json().get("contact", {})


async def search_contacts(access_token: str, location_id: str, query: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/contacts/search",
            headers=_headers(access_token),
            params={"locationId": location_id, "query": query, "limit": 10},
        )
        r.raise_for_status()
        return r.json().get("contacts", [])


async def create_contact(access_token: str, location_id: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/contacts/",
            headers=_headers(access_token),
            json={"locationId": location_id, **data},
        )
        r.raise_for_status()
        return r.json().get("contact", {})


async def update_contact_fields(
    access_token: str, contact_id: str, custom_fields: list
) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(access_token),
            json={"customFields": custom_fields},
        )
        r.raise_for_status()
        return r.json().get("contact", {})


async def create_note(access_token: str, contact_id: str, body: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/contacts/{contact_id}/notes",
            headers=_headers(access_token),
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()


async def list_locations(access_token: str, company_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/search",
            headers=_headers(access_token),
            params={"companyId": company_id, "limit": 100},
        )
        r.raise_for_status()
        return r.json().get("locations", [])


async def list_custom_field_groups(access_token: str, location_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/{location_id}/customFieldGroups",
            headers=_headers(access_token),
        )
        r.raise_for_status()
        data = r.json()
        return data.get("groups") or data.get("fieldGroups") or []


async def create_custom_field_group(access_token: str, location_id: str, name: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/locations/{location_id}/customFieldGroups",
            headers=_headers(access_token),
            json={"name": name, "model": "contact"},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("fieldGroup") or data.get("group") or {}


async def update_custom_field(
    access_token: str, location_id: str, field_id: str, data: dict
) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{GHL_BASE}/locations/{location_id}/customFields/{field_id}",
            headers=_headers(access_token),
            json=data,
        )
        r.raise_for_status()
        return r.json().get("customField", {})


async def list_custom_fields(access_token: str, location_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/{location_id}/customFields",
            headers=_headers(access_token),
        )
        r.raise_for_status()
        return r.json().get("customFields", [])


async def create_custom_field(
    access_token: str,
    location_id: str,
    name: str,
    data_type: str,
    options: Optional[list] = None,
    group_id: Optional[str] = None,
) -> dict:
    payload: dict = {"name": name, "dataType": data_type, "model": "contact"}
    if options:
        payload["options"] = options
    if group_id:
        payload["groupId"] = group_id
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/locations/{location_id}/customFields",
            headers=_headers(access_token),
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("customField", {})
