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


async def list_custom_field_folders(access_token: str, location_id: str) -> list:
    """
    Try all known GHL folder endpoint variants and return whichever works.
    Candidates (GHL docs are inconsistent — we probe until one succeeds):
      1. Top-level  GET /custom-fields/folders?locationId=...
      2. Top-level  GET /custom-fields/folder?locationId=...   (singular)
      3. Location   GET /locations/{id}/customFields/folders
    """
    candidates = [
        ("GET",  f"{GHL_BASE}/custom-fields/folders",            {"locationId": location_id}),
        ("GET",  f"{GHL_BASE}/custom-fields/folder",             {"locationId": location_id}),
        ("GET",  f"{GHL_BASE}/locations/{location_id}/customFields/folders", {}),
    ]
    last_err = ""
    async with httpx.AsyncClient() as client:
        for method, url, params in candidates:
            r = await client.get(url, headers=_headers(access_token), params=params)
            if r.status_code < 400:
                data = r.json()
                return (
                    data.get("folders")
                    or data.get("customFieldFolders")
                    or data.get("folder")
                    or []
                )
            last_err = f"{url} → HTTP {r.status_code}: {r.text[:200] or '<empty>'}"
    raise Exception(f"GHL list custom field folders failed. Last: {last_err}")


async def create_custom_field_folder(
    access_token: str, location_id: str, name: str
) -> str:
    """
    Create a custom field folder and return its ID.
    Candidates (probe until one returns a folder ID):
      1. Top-level  POST /custom-fields/folders  body: {name, locationId, model}
      2. Top-level  POST /custom-fields/folder   body: {name, locationId, model}
      3. Location   POST /locations/{id}/customFields/folders  body: {name, model}
    """
    candidates = [
        (f"{GHL_BASE}/custom-fields/folders",                       {"name": name, "locationId": location_id, "model": "contact"}),
        (f"{GHL_BASE}/custom-fields/folder",                        {"name": name, "locationId": location_id, "model": "contact"}),
        (f"{GHL_BASE}/locations/{location_id}/customFields/folders", {"name": name, "model": "contact"}),
    ]
    last_err = ""
    async with httpx.AsyncClient() as client:
        for url, body in candidates:
            r = await client.post(url, headers=_headers(access_token), json=body)
            if r.status_code < 400:
                data = r.json()
                folder = (
                    data.get("folder")
                    or data.get("customFieldFolder")
                    or data.get("folders", [{}])[0]
                    or data
                )
                fid = folder.get("id") or folder.get("_id") or ""
                if fid:
                    return fid
            last_err = f"{url} → HTTP {r.status_code}: {r.text[:200] or '<empty>'}"
    raise Exception(f"GHL create custom field folder failed. Last: {last_err}")


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
