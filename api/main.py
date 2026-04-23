import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from supabase import create_client

from . import auth, ghl
from . import setup as app_setup
from . import config as app_config
from .models import QualificationSubmission

load_dotenv()

app = FastAPI(title="Life Insurance Qualifier")

FRONTEND = Path(__file__).parent.parent / "frontend"


def _html(name: str) -> HTMLResponse:
    return HTMLResponse((FRONTEND / name).read_text(encoding="utf-8"))


def _sb():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return _html("setup.html")


@app.get("/", response_class=HTMLResponse)
async def home(location_id: str = Query(...)):
    if not app_config.is_setup_complete(location_id):
        return RedirectResponse("/setup")
    return _html("app.html")


@app.get("/qualify", response_class=HTMLResponse)
async def qualify_page():
    return _html("qualify.html")


# ── OAuth ──────────────────────────────────────────────────────────────────────

@app.get("/oauth/start")
async def oauth_start():
    return RedirectResponse(auth.get_oauth_url())


@app.get("/oauth/callback")
async def oauth_callback(code: str = Query(...)):
    token_data = await auth.exchange_code(code)
    location_id = await auth.save_installation(token_data)
    return RedirectResponse(f"/setup?step=setup&location_id={location_id}")


# ── Setup API ──────────────────────────────────────────────────────────────────

@app.get("/api/setup/run")
async def run_setup(location_id: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    return await app_setup.run(location_id, token)


# ── App API ────────────────────────────────────────────────────────────────────

@app.get("/api/location")
async def get_location(location_id: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    data = await ghl.get_location(token, location_id)
    return {"id": location_id, "name": data.get("name", "")}


@app.get("/api/contact")
async def get_contact(location_id: str = Query(...), contact_id: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    contact = await ghl.get_contact(token, contact_id)
    return {
        "id": contact.get("id"),
        "firstName": contact.get("firstName", ""),
        "lastName": contact.get("lastName", ""),
        "email": contact.get("email", ""),
        "phone": contact.get("phone", ""),
    }


@app.get("/api/contacts/search")
async def search_contacts(location_id: str = Query(...), q: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    contacts = await ghl.search_contacts(token, location_id, q)
    return {
        "contacts": [
            {
                "id": c.get("id"),
                "name": f"{c.get('firstName','')} {c.get('lastName','')}".strip(),
                "email": c.get("email", ""),
                "phone": c.get("phone", ""),
            }
            for c in contacts
        ]
    }


@app.get("/api/qualifications/recent")
async def recent_qualifications(location_id: str = Query(...)):
    result = (
        _sb()
        .table("qualifications")
        .select("*")
        .eq("location_id", location_id)
        .order("qualified_at", desc=True)
        .limit(10)
        .execute()
    )
    return {"qualifications": result.data or []}


@app.post("/api/submit")
async def submit_qualification(payload: QualificationSubmission):
    token = await auth.get_valid_token(payload.location_id)
    cfg = app_config.get_config(payload.location_id)

    if not cfg:
        raise HTTPException(status_code=400, detail="Location not configured. Run setup first.")

    # Create contact if this is a new qualification
    contact_id = payload.contact_id
    if not contact_id:
        name_parts = (payload.full_name or "New Contact").split(" ", 1)
        contact = await ghl.create_contact(
            token,
            payload.location_id,
            {
                "firstName": name_parts[0],
                "lastName": name_parts[1] if len(name_parts) > 1 else "",
                "email": payload.email or "",
                "phone": payload.phone or "",
            },
        )
        contact_id = contact["id"]

    # Write custom field values back to the GHL contact
    field_map = {
        "field_triage_state_id": payload.triage_state,
        "field_product_direction_id": payload.product_direction,
        "field_active_deps_id": payload.active_dependencies,
        "field_coverage_amount_id": payload.coverage_amount,
        "field_product_type_id": payload.product_type,
    }
    custom_fields = [
        {"id": cfg[cfg_key], "value": value}
        for cfg_key, value in field_map.items()
        if cfg.get(cfg_key) and value
    ]
    if custom_fields:
        await ghl.update_contact_fields(token, contact_id, custom_fields)

    # Post a structured note to the contact record
    await ghl.create_note(token, contact_id, _build_note(payload))

    # Record in Supabase for the recent-qualifications list
    _sb().table("qualifications").insert(
        {
            "location_id": payload.location_id,
            "contact_id": contact_id,
            "contact_name": payload.full_name or "Unknown",
            "triage_state": payload.triage_state,
            "qualified_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    return {"ok": True, "contact_id": contact_id}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_note(p: QualificationSubmission) -> str:
    deps = p.active_dependencies or "None"
    state_label = (p.triage_state or "N/A").replace("_", " ").title()
    lines = [
        "═══ Life Insurance Qualification ═══",
        f"Triage State      : {state_label}",
        f"Product Direction : {p.product_direction or '—'}",
        f"Active Flags      : {deps}",
        "",
        "▸ Coverage Goals",
        f"  Type     : {p.product_type or '—'}",
        f"  Amount   : {p.coverage_amount or '—'}",
        f"  Budget   : {p.budget or '—'}",
        f"  Urgency  : {p.urgency or '—'}",
        f"  Goal     : {p.goal or '—'}",
        "",
        "▸ Applicant",
        f"  Age / Sex / State : {p.age or '—'} / {p.sex_at_birth or '—'} / {p.state or '—'}",
        f"  Occupation        : {p.occupation or '—'}",
        f"  Height / Weight   : {p.height or '—'} / {p.weight or '—'}",
        "",
        "▸ Medications",
        f"  {p.med_list or '—'}",
        "",
        "▸ Underwriting",
        f"  Existing Coverage : {p.existing_coverage or '—'}",
        f"  Prior Outcome     : {p.prior_outcome or '—'}",
        f"  Notes             : {p.underwriting_notes or '—'}",
    ]
    return "\n".join(lines)
