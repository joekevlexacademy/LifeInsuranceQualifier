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


def _check(r: httpx.Response, operation: str) -> None:
    """Raise with the real GHL response body so errors are debuggable."""
    if r.status_code >= 400:
        body = r.text[:500] if r.text else "<empty>"
        raise Exception(f"GHL {operation} failed (HTTP {r.status_code}): {body}")


async def get_location(access_token: str, location_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/{location_id}",
            headers=_headers(access_token),
        )
        _check(r, "get location")
        return r.json().get("location", {})


async def get_contact(access_token: str, contact_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(access_token),
        )
        _check(r, "get contact")
        return r.json().get("contact", {})


async def search_contacts(access_token: str, location_id: str, query: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/contacts/",
            headers=_headers(access_token),
            params={"locationId": location_id, "query": query, "limit": 10},
        )
        _check(r, "search contacts")
        return r.json().get("contacts", [])


async def create_contact(access_token: str, location_id: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/contacts/",
            headers=_headers(access_token),
            json={"locationId": location_id, **data},
        )
        _check(r, "create contact")
        return r.json().get("contact", {})


async def update_contact_fields(
    access_token: str, contact_id: str, custom_fields: list, extra: dict | None = None
) -> dict:
    body: dict = {}
    if custom_fields:
        body["customFields"] = custom_fields
    if extra:
        body.update(extra)
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(access_token),
            json=body,
        )
        _check(r, "update contact")
        return r.json().get("contact", {})


async def create_note(access_token: str, contact_id: str, body: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/contacts/{contact_id}/notes",
            headers=_headers(access_token),
            json={"body": body},
        )
        _check(r, "create note")
        return r.json()


async def list_locations(access_token: str, company_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/search",
            headers=_headers(access_token),
            params={"companyId": company_id, "limit": 100},
        )
        _check(r, "list locations")
        return r.json().get("locations", [])


async def list_custom_menus(access_token: str, company_id: str) -> list:
    """List existing custom menu links. company_id is unused by GHL but kept for API symmetry."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/custom-menus/",
            headers=_headers(access_token),
            params={"limit": 100},
        )
        _check(r, "list custom menus")
        data = r.json()
        return data.get("customMenus") or data.get("menus") or []


def _menu_payload(name: str, url: str, locations: list | None = None) -> dict:
    return {
        "title": name,
        "url": url,
        "icon": {"name": "shield-alt", "fontFamily": "fas"},
        "showOnCompany": False,
        "showOnLocation": True,
        "showToAllLocations": not locations,
        "openMode": "iframe",
        "locations": locations or [],
        "userRole": "all",
        "allowCamera": False,
        "allowMicrophone": False,
    }


async def create_custom_menu(
    access_token: str,
    company_id: str,
    name: str,
    url: str,
    locations: list | None = None,
) -> dict:
    """Create a sidebar custom menu link scoped to specific locations (or all if locations is None)."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GHL_BASE}/custom-menus/",
            headers=_headers(access_token),
            json=_menu_payload(name, url, locations),
        )
        _check(r, "create custom menu")
        return r.json()


async def update_custom_menu(
    access_token: str,
    menu_id: str,
    name: str,
    url: str,
    locations: list | None = None,
) -> dict:
    """Update an existing custom menu link."""
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{GHL_BASE}/custom-menus/{menu_id}",
            headers=_headers(access_token),
            json=_menu_payload(name, url, locations),
        )
        _check(r, "update custom menu")
        return r.json()


async def list_custom_fields(access_token: str, location_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GHL_BASE}/locations/{location_id}/customFields",
            headers=_headers(access_token),
        )
        _check(r, "list custom fields")
        return r.json().get("customFields", [])


_FOLDER_PATHS = [
    "/customFields/folders",
    "/customFieldFolders",
]


async def list_custom_field_folders(access_token: str, location_id: str) -> list:
    """Try both known GHL folder endpoint paths and return whichever works."""
    last_exc: Exception = Exception("no folder endpoint tried")
    async with httpx.AsyncClient() as client:
        for suffix in _FOLDER_PATHS:
            r = await client.get(
                f"{GHL_BASE}/locations/{location_id}{suffix}",
                headers=_headers(access_token),
            )
            if r.status_code < 400:
                data = r.json()
                return data.get("folders") or data.get("customFieldFolders") or []
            last_exc = Exception(
                f"GHL list custom field folders ({suffix}) failed "
                f"(HTTP {r.status_code}): {r.text[:300] or '<empty>'}"
            )
    raise last_exc


async def create_custom_field_folder(
    access_token: str, location_id: str, name: str
) -> str:
    """Create a custom field folder and return its ID. Tries both known endpoint paths."""
    last_exc: Exception = Exception("no folder endpoint tried")
    async with httpx.AsyncClient() as client:
        for suffix in _FOLDER_PATHS:
            r = await client.post(
                f"{GHL_BASE}/locations/{location_id}{suffix}",
                headers=_headers(access_token),
                json={"name": name, "model": "contact"},
            )
            if r.status_code < 400:
                data = r.json()
                folder = data.get("folder") or data.get("customFieldFolder") or data
                fid = folder.get("id") or folder.get("_id") or ""
                if fid:
                    return fid
            last_exc = Exception(
                f"GHL create custom field folder ({suffix}) failed "
                f"(HTTP {r.status_code}): {r.text[:300] or '<empty>'}"
            )
    raise last_exc


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
        _check(r, "create custom field")
        return r.json().get("customField", {})
