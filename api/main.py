import os
import random
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query
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
async def home(location_id: str = Query(None)):
    if not location_id:
        return _html("landing.html")
    # GHL may load the menu URL before substituting {{location.id}} — serve
    # app.html so the client can detect the real sub-account via referrer/postMessage.
    if location_id.startswith("{{"):
        return _html("app.html")
    if not app_config.is_setup_complete(location_id):
        return RedirectResponse(f"/setup?step=setup&location_id={location_id}&_cb={random.randint(100000,999999)}")
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
    try:
        token_data = await auth.exchange_code(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GHL token exchange failed: {exc}") from exc

    try:
        location_id = await auth.save_installation(token_data)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Supabase save failed: {exc} | token_data keys: {list(token_data.keys())}",
        ) from exc

    company_id = token_data.get("companyId")
    redirect_url = f"/setup?step=setup&location_id={location_id}&_cb={random.randint(100000,999999)}"
    if company_id and company_id != location_id:
        redirect_url += f"&company_id={company_id}"
    return RedirectResponse(redirect_url)


# ── Debug ─────────────────────────────────────────────────────────────────────

@app.get("/api/debug/menu")
async def debug_menu(location_id: str = Query(...), agency_key: str = Query(None)):
    """Test agency key against GHL custom-menus API and show stored key info."""
    result: dict = {}

    # Show what's stored for this location's agency
    company_id = await auth.get_agency_id(location_id)
    result["stored_company_id"] = company_id
    result["is_self_referencing"] = (company_id == location_id)
    if company_id:
        stored_key = await auth.get_agency_key(company_id)
        result["stored_agency_key_prefix"] = stored_key[:12] + "…" if stored_key else None

    # Test whichever key is available: explicit param > stored > location token
    test_key = agency_key or (await auth.get_agency_key(company_id) if company_id else None)
    if not test_key:
        try:
            test_key = await auth.get_valid_token(location_id)
        except Exception:
            pass
    result["test_key_prefix"] = test_key[:12] + "…" if test_key else None

    try:
        existing = await ghl.list_custom_menus(test_key, company_id or location_id)
        result["list_ok"] = True
        result["menu_count"] = len(existing)
        result["menus"] = [{"title": m.get("title") or m.get("name"), "id": m.get("id") or m.get("_id"), "locations": len(m.get("locations") or [])} for m in existing]
    except Exception as exc:
        result["list_error"] = str(exc)

    return result


# ── Setup API ──────────────────────────────────────────────────────────────────

@app.get("/api/setup/has-agency-key")
async def has_agency_key(location_id: str = Query(...)):
    """Return whether an agency-level key is already stored for this location's agency."""
    company_id = await auth.get_agency_id(location_id)
    # Self-referencing means the row was created before company_id resolution was added —
    # treat as no agency key so the user is prompted to enter one.
    if not company_id or company_id == location_id:
        return {"has_agency_key": False}
    key = await auth.get_agency_key(company_id)
    return {"has_agency_key": bool(key)}


@app.post("/api/setup/agency-key")
async def store_agency_key_and_run(
    location_id: str = Query(...),
    agency_key: str = Body(..., embed=True),
):
    """Store an agency-level PIK and re-run setup for an already-configured location."""
    try:
        location_token = await auth.get_valid_token(location_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token lookup failed: {exc}")

    company_id = await auth.get_agency_id(location_id)

    # Fix stale self-referencing rows and resolve real company_id from GHL
    if not company_id or company_id == location_id:
        try:
            loc_data = await ghl.get_location(location_token, location_id)
            real_cid = loc_data.get("companyId") or loc_data.get("parentId")
            if real_cid and real_cid != location_id:
                company_id = real_cid
                _sb().table("installations").update({"agency_id": real_cid}).eq("location_id", location_id).execute()
        except Exception:
            pass

    if company_id:
        try:
            await auth.save_agency_key(company_id, agency_key)
        except Exception:
            pass

    return await app_setup.run(
        location_id, location_token,
        company_id=company_id,
        agency_token=agency_key,
    )


@app.get("/api/setup/locations")
async def list_setup_locations(location_id: str = Query(...)):
    try:
        token = await auth.get_valid_token(location_id)
        locations = await ghl.list_locations(token, location_id)
        return {
            "locations": [
                {"id": loc["id"], "name": loc.get("name", loc["id"])}
                for loc in locations
            ]
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/setup/run")
async def run_setup(location_id: str = Query(...), company_id: str = Query(None)):
    # Token for field operations (may be a PIK or an OAuth token)
    try:
        location_token = await auth.get_valid_token(location_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token lookup failed: {exc}")

    # Derive company_id from the installation row if caller didn't pass one
    if not company_id:
        company_id = await auth.get_agency_id(location_id)

    # Self-referencing means the row was saved before company_id resolution existed.
    # Fetch the real company_id from GHL and repair the stale row.
    if not company_id or company_id == location_id:
        try:
            loc_data = await ghl.get_location(location_token, location_id)
            real_cid = loc_data.get("companyId") or loc_data.get("parentId")
            if real_cid and real_cid != location_id:
                company_id = real_cid
                _sb().table("installations").update({"agency_id": real_cid}).eq("location_id", location_id).execute()
        except Exception:
            pass

    # Menu operations need the agency-level key (custom-menu-link.write scope).
    # Use get_agency_key to avoid accidentally picking up a subaccount PIK via fallback.
    agency_token: str | None = None
    if company_id and company_id != location_id:
        agency_token = await auth.get_agency_key(company_id)
        try:
            await auth.ensure_location_installation(company_id, location_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to register location: {exc}")
    if not agency_token:
        try:
            agency_token = await auth.get_any_menu_token()
        except Exception:
            pass

    return await app_setup.run(location_id, location_token, company_id=company_id, agency_token=agency_token)


@app.post("/api/setup/run")
async def run_setup_with_key(
    location_id: str = Query(...),
    company_id: str = Query(None),
    api_key: str = Body(..., embed=True),
    agency_key: str | None = Body(None, embed=True),
):
    """Setup using a GHL Private Integration key (for agency-level installs)."""
    # Resolve company_id in priority order:
    #   1. Caller-supplied query param
    #   2. GHL /locations/{id} response (companyId field) — works with any PIK that has locations.readonly
    #   3. Existing Supabase row for this location
    if not company_id:
        try:
            loc_data = await ghl.get_location(api_key, location_id)
            company_id = loc_data.get("companyId") or loc_data.get("parentId")
        except Exception:
            pass
    if not company_id:
        company_id = await auth.get_agency_id(location_id)

    try:
        await auth.save_api_key_installation(company_id or location_id, location_id, api_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save API key: {exc}")

    # Store agency key if provided — persisted under company_id so future setups
    # can use it without re-entering it.
    if agency_key and company_id:
        try:
            await auth.save_agency_key(company_id, agency_key)
        except Exception:
            pass

    # For menu operations: explicit agency_key > stored agency-level PIK > any OAuth token.
    # Use get_agency_key (not get_valid_token) so we never accidentally pick up a
    # subaccount PIK or a stale/revoked token from the company row.
    agency_tok: str | None = agency_key
    if not agency_tok and company_id and company_id != location_id:
        try:
            agency_tok = await auth.get_agency_key(company_id)
        except Exception:
            pass
    if not agency_tok:
        try:
            agency_tok = await auth.get_any_menu_token()
        except Exception:
            pass

    return await app_setup.run(location_id, api_key, company_id=company_id, agency_token=agency_tok)


# ── App API ────────────────────────────────────────────────────────────────────

@app.get("/api/configured-locations")
async def configured_locations():
    """Return all sub-accounts that have completed setup, with names from GHL."""
    sb = _sb()
    rows = (
        sb.table("location_config")
        .select("location_id")
        .eq("setup_complete", True)
        .execute()
    )
    locations = []
    for row in rows.data or []:
        lid = row["location_id"]
        try:
            token = await auth.get_valid_token(lid)
            loc_data = await ghl.get_location(token, lid)
            name = loc_data.get("name") or lid
        except Exception:
            name = lid
        locations.append({"id": lid, "name": name})
    return {"locations": locations}


@app.get("/api/location")
async def get_location(location_id: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    data = await ghl.get_location(token, location_id)
    return {"id": location_id, "name": data.get("name", "")}


@app.get("/api/contact")
async def get_contact(location_id: str = Query(...), contact_id: str = Query(...)):
    token = await auth.get_valid_token(location_id)
    contact = await ghl.get_contact(token, contact_id)
    cfg = app_config.get_config(location_id)

    # Build a name→value map for previously-saved LIQ custom fields so the
    # qualify form can be pre-filled when reopening an existing contact.
    liq: dict = {}
    if cfg:
        _liq_keys = {
            cfg.get("field_coverage_amount_id"):    "coverage_amount",
            cfg.get("field_product_type_id"):       "product_type",
            cfg.get("field_budget_id"):             "budget",
            cfg.get("field_urgency_id"):            "urgency",
            cfg.get("field_coverage_reason_id"):    "coverage_reason",
            cfg.get("field_applicant_id"):          "applicant",
            cfg.get("field_triage_flags_id"):       "triage_flags",
            cfg.get("field_medications_id"):        "med_list",
            cfg.get("field_existing_coverage_id"):  "existing_coverage",
            cfg.get("field_prior_outcome_id"):      "prior_outcome",
            cfg.get("field_underwriting_notes_id"): "underwriting_notes",
            cfg.get("field_dependency_details_id"): "dependency_details",
            cfg.get("field_qual_summary_id"):       "qual_summary",
        }
        _liq_keys.pop(None, None)  # remove any unconfigured fields
        for cf in (contact.get("customFields") or []):
            fid = cf.get("id")
            val = cf.get("value") or cf.get("fieldValue") or ""
            if fid in _liq_keys and val:
                liq[_liq_keys[fid]] = val

    return {
        "id": contact.get("id"),
        "firstName": contact.get("firstName", ""),
        "lastName": contact.get("lastName", ""),
        "email": contact.get("email", ""),
        "phone": contact.get("phone", ""),
        "dateOfBirth": contact.get("dateOfBirth", ""),
        "gender": contact.get("gender", ""),
        "state": contact.get("state", ""),
        "address1": contact.get("address1", ""),
        "city": contact.get("city", ""),
        "postalCode": contact.get("postalCode", ""),
        "companyName": contact.get("companyName", ""),
        "liq": liq,
    }


@app.get("/api/contacts/search")
async def search_contacts(location_id: str = Query(...), q: str = Query(...)):
    try:
        token = await auth.get_valid_token(location_id)
        contacts = await ghl.search_contacts(token, location_id, q)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
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


@app.delete("/api/qualifications")
async def clear_qualifications(location_id: str = Query(...)):
    _sb().table("qualifications").delete().eq("location_id", location_id).execute()
    return {"ok": True}


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
    try:
        token = await auth.get_valid_token(payload.location_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token lookup failed: {exc}")

    cfg = app_config.get_config(payload.location_id)
    if not cfg:
        raise HTTPException(status_code=400, detail="Location not configured. Run setup first.")

    # Create contact if this is a new qualification
    contact_id = payload.contact_id
    if not contact_id:
        name_parts = (payload.full_name or "New Contact").split(" ", 1)
        try:
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
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to create GHL contact: {exc}")
        contact_id = contact["id"]

    # Map triage_state computed value to GHL SINGLE_OPTIONS labels
    _triage_labels = {
        "clean": "Clean",
        "follow_up": "Follow-up Required",
        "elevated": "Elevated Attention",
    }
    triage_label = _triage_labels.get(payload.triage_state or "", payload.triage_state)

    # Computed fields (triage state, product direction, active deps, summary) are
    # derived from the triage section which cannot be pre-filled on re-open.
    # Only overwrite them if the agent actually engaged with the triage section
    # this session — otherwise the existing GHL values are left untouched.
    triage_engaged = bool(
        payload.pending_tests or payload.hospital_recent
        or payload.underwriting_history or payload.dui_history
        or payload.sleep_apnea or payload.cpap or payload.diabetes_meds
        or payload.psych_meds or payload.inhaler or payload.cardiac_history
    )

    # Explicit fields: only sent when the form field has a value (guard below).
    # Computed fields: only sent when triage was engaged this session.
    field_map: dict = {
        "field_coverage_amount_id":    payload.coverage_amount,
        "field_product_type_id":       payload.product_type,
        "field_budget_id":             payload.budget,
        "field_urgency_id":            payload.urgency,
        "field_coverage_reason_id":    payload.goal,
        "field_applicant_id":          _build_applicant(payload),
        "field_triage_flags_id":       _build_triage_flags(payload),
        "field_medications_id":        payload.med_list,
        "field_existing_coverage_id":  payload.existing_coverage,
        "field_prior_outcome_id":      payload.prior_outcome,
        "field_underwriting_notes_id": payload.underwriting_notes,
        "field_dependency_details_id": _build_dependency_details(payload),
    }
    if triage_engaged:
        field_map.update({
            "field_triage_state_id":      triage_label,
            "field_product_direction_id": payload.product_direction,
            "field_active_deps_id":       payload.active_dependencies,
            "field_qual_summary_id":      _build_summary(payload, triage_label),
        })
    custom_fields = [
        {"id": cfg[cfg_key], "value": value}
        for cfg_key, value in field_map.items()
        if cfg.get(cfg_key) and value
    ]

    # Standard GHL contact fields (written back, not just read).
    # Note: GHL PUT /contacts/{id} does not accept "gender" — state only.
    extra: dict = {}
    if payload.state:
        extra["state"] = payload.state

    try:
        if custom_fields or extra:
            await ghl.update_contact_fields(token, contact_id, custom_fields, extra=extra)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update GHL contact fields: {exc}")

    # Post a structured note to the contact record
    try:
        await ghl.create_note(token, contact_id, _build_note(payload))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create GHL note: {exc}")

    # Record in Supabase for the recent-qualifications list
    try:
        _sb().table("qualifications").insert(
            {
                "location_id": payload.location_id,
                "contact_id": contact_id,
                "contact_name": payload.full_name or "Unknown",
                "triage_state": payload.triage_state,
                "qualified_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save qualification record: {exc}")

    return {"ok": True, "contact_id": contact_id}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_applicant(p: QualificationSubmission) -> str:
    """Pipe-delimited key:value string for the LIQ Applicant field."""
    parts = []
    if p.age:       parts.append(f"age:{p.age}")
    if p.sex_at_birth: parts.append(f"sex:{p.sex_at_birth}")
    if p.occupation: parts.append(f"occupation:{p.occupation}")
    if p.height:    parts.append(f"height:{p.height}")
    if p.weight:    parts.append(f"weight:{p.weight}")
    return " | ".join(parts) if parts else ""


def _build_triage_flags(p: QualificationSubmission) -> str:
    """Pipe-delimited key:value string for the LIQ Triage Flags field."""
    def yn(v) -> str:
        if isinstance(v, bool): return "yes" if v else "no"
        return "yes" if v == "yes" else "no"
    parts = [
        f"pending_tests:{yn(p.pending_tests)}",
        f"hospital_recent:{yn(p.hospital_recent)}",
        f"prior_rating:{yn(p.underwriting_history)}",
        f"dui:{yn(p.dui_history)}",
        f"sleep_apnea:{yn(p.sleep_apnea)}",
        f"cpap:{yn(p.cpap)}",
        f"diabetes_meds:{yn(p.diabetes_meds)}",
        f"psych_meds:{yn(p.psych_meds)}",
        f"inhaler:{yn(p.inhaler)}",
        f"cardiac:{yn(p.cardiac_history)}",
        f"med_change:{yn(p.med_change)}",
    ]
    return " | ".join(parts)


def _build_dependency_details(p: QualificationSubmission) -> str:
    """Section-keyed multi-line block for the LIQ Dependency Details field."""
    sections = []

    if p.pending_tests == "yes":
        block = ["[pending]"]
        if p.pending_reason:  block.append(f"reason={p.pending_reason}")
        if p.pending_date:    block.append(f"date={p.pending_date}")
        if p.pending_doctor:  block.append(f"doctor={p.pending_doctor}")
        if p.pending_followup: block.append(f"followup={p.pending_followup}")
        if p.pending_notes:   block.append(f"notes={p.pending_notes}")
        if len(block) > 1:
            sections.append("\n".join(block))

    if p.sleep_apnea or p.cpap:
        block = ["[sleep]"]
        if p.apnea_type:       block.append(f"type={p.apnea_type}")
        if p.apnea_severity:   block.append(f"severity={p.apnea_severity}")
        if p.ahi:              block.append(f"ahi={p.ahi}")
        if p.cpap_use:         block.append(f"pap={p.cpap_use}")
        if p.nights_per_week:  block.append(f"nights={p.nights_per_week}")
        if p.hours_per_night:  block.append(f"hours={p.hours_per_night}")
        if p.daytime_fatigue:  block.append(f"fatigue={p.daytime_fatigue}")
        if p.oxygen_night:     block.append(f"o2={p.oxygen_night}")
        if p.apnea_conditions: block.append(f"conditions={p.apnea_conditions}")
        if len(block) > 1:
            sections.append("\n".join(block))

    if p.diabetes_meds:
        block = ["[diabetes]"]
        if p.diabetes_type:          block.append(f"type={p.diabetes_type}")
        if p.diagnosis_age:          block.append(f"dx_age={p.diagnosis_age}")
        if p.a1c:                    block.append(f"a1c={p.a1c}")
        if p.insulin_use:            block.append(f"insulin={p.insulin_use}")
        if p.diabetes_control:       block.append(f"control={p.diabetes_control}")
        if p.diabetes_complications: block.append(f"complications={p.diabetes_complications}")
        if len(block) > 1:
            sections.append("\n".join(block))

    if p.psych_meds:
        block = ["[mental]"]
        if p.mh_diagnosis:  block.append(f"diagnosis={p.mh_diagnosis}")
        if p.mh_stability:  block.append(f"stability={p.mh_stability}")
        if p.therapy:       block.append(f"therapy={p.therapy}")
        if p.mh_hospital:   block.append(f"hospital={p.mh_hospital}")
        if p.mh_notes:      block.append(f"notes={p.mh_notes}")
        if len(block) > 1:
            sections.append("\n".join(block))

    if p.inhaler:
        block = ["[resp]"]
        if p.resp_diagnosis: block.append(f"diagnosis={p.resp_diagnosis}")
        if p.rescue_use:     block.append(f"rescue={p.rescue_use}")
        if p.oral_steroids:  block.append(f"steroids={p.oral_steroids}")
        if p.smoker_status:  block.append(f"smoking={p.smoker_status}")
        if p.resp_hospital:  block.append(f"er={p.resp_hospital}")
        if len(block) > 1:
            sections.append("\n".join(block))

    if p.dui_history == "yes":
        block = ["[dui]"]
        if p.dui_count:         block.append(f"count={p.dui_count}")
        if p.dui_date:          block.append(f"date={p.dui_date}")
        if p.license_status:    block.append(f"license={p.license_status}")
        if p.substance_program: block.append(f"program={p.substance_program}")
        if p.bac:               block.append(f"bac={p.bac}")
        if len(block) > 1:
            sections.append("\n".join(block))

    return "\n\n".join(sections)


def _build_summary(p: QualificationSubmission, triage_label: str) -> str:
    """Compact summary written to LIQ Qualification Summary custom field."""
    deps = p.active_dependencies or "None"
    lines = [
        f"Triage: {triage_label}",
        f"Active Flags: {deps}",
        "",
        f"Product Direction: {p.product_direction or '—'}",
        "",
        "Coverage Goals:",
        f"  Type: {p.product_type or '—'}",
        f"  Amount: {p.coverage_amount or '—'}",
        f"  Budget: {p.budget or '—'}",
        f"  Urgency: {p.urgency or '—'}",
    ]
    if p.goal:
        lines.append(f"  Reason: {p.goal}")
    notes = []
    if p.pending_tests == "yes":
        notes.append("Pending tests / open work-up — hold on quoting")
    if p.hospital_recent == "yes":
        notes.append("Recent hospitalization — clarify dates and recovery status")
    if p.underwriting_history == "yes":
        notes.append("Prior underwriting friction — review before quoting")
    if p.cardiac_history:
        notes.append("Cardiac history marked — cardiology questions recommended")
    if notes:
        lines.append("")
        lines.append("Advisor Notes:")
        for note in notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)


def _build_note(p: QualificationSubmission) -> str:
    """Full structured note written to GHL contact Notes (Live Advisor Summary)."""
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
        f"  Reason   : {p.goal or '—'}",
        "",
        "▸ Applicant",
        f"  Age / Sex / State : {p.age or '—'} / {p.sex_at_birth or '—'} / {p.state or '—'}",
        f"  Occupation        : {p.occupation or '—'}",
        f"  Height / Weight   : {p.height or '—'} / {p.weight or '—'}",
        "",
        "▸ Triage Flags",
        f"  Pending tests     : {p.pending_tests or '—'}",
        f"  Recent hospital   : {p.hospital_recent or '—'}",
        f"  Prior rating      : {p.underwriting_history or '—'}",
        f"  DUI history       : {p.dui_history or '—'}",
        f"  Sleep apnea/CPAP  : {'yes' if p.sleep_apnea or p.cpap else 'no'}",
        f"  Diabetes meds     : {'yes' if p.diabetes_meds else 'no'}",
        f"  Psych meds        : {'yes' if p.psych_meds else 'no'}",
        f"  Inhaler           : {'yes' if p.inhaler else 'no'}",
        f"  Cardiac history   : {'yes' if p.cardiac_history else 'no'}",
        f"  Med change        : {p.med_change or '—'}",
        "",
        "▸ Medications",
        f"  {p.med_list or '—'}",
    ]

    # Dependency details blocks (only active ones)
    if p.pending_tests == "yes" and any([p.pending_reason, p.pending_date, p.pending_doctor]):
        lines += [
            "",
            "▸ Pending Work-up",
            f"  Reason   : {p.pending_reason or '—'}",
            f"  Date     : {p.pending_date or '—'}",
            f"  Doctor   : {p.pending_doctor or '—'}",
            f"  Follow-up: {p.pending_followup or '—'}",
        ]
        if p.pending_notes:
            lines.append(f"  Notes    : {p.pending_notes}")

    if p.sleep_apnea or p.cpap:
        lines += [
            "",
            "▸ Sleep Apnea",
            f"  Type / Severity : {p.apnea_type or '—'} / {p.apnea_severity or '—'}",
            f"  AHI             : {p.ahi or '—'}",
            f"  PAP therapy     : {p.cpap_use or '—'} ({p.nights_per_week or '—'} nights, {p.hours_per_night or '—'} hrs)",
            f"  Daytime fatigue : {p.daytime_fatigue or '—'}",
            f"  Night oxygen    : {p.oxygen_night or '—'}",
        ]
        if p.apnea_conditions:
            lines.append(f"  Conditions      : {p.apnea_conditions}")

    if p.diabetes_meds:
        lines += [
            "",
            "▸ Diabetes",
            f"  Type / Dx age : {p.diabetes_type or '—'} / {p.diagnosis_age or '—'}",
            f"  A1C           : {p.a1c or '—'}",
            f"  Insulin       : {p.insulin_use or '—'}",
            f"  Control       : {p.diabetes_control or '—'}",
        ]
        if p.diabetes_complications:
            lines.append(f"  Complications : {p.diabetes_complications}")

    if p.psych_meds:
        lines += [
            "",
            "▸ Mental Health",
            f"  Diagnosis  : {p.mh_diagnosis or '—'}",
            f"  Stability  : {p.mh_stability or '—'}",
            f"  Therapy    : {p.therapy or '—'}",
            f"  Hospital   : {p.mh_hospital or '—'}",
        ]
        if p.mh_notes:
            lines.append(f"  Notes      : {p.mh_notes}")

    if p.inhaler:
        lines += [
            "",
            "▸ Respiratory",
            f"  Diagnosis  : {p.resp_diagnosis or '—'}",
            f"  Rescue use : {p.rescue_use or '—'}",
            f"  Steroids   : {p.oral_steroids or '—'}",
            f"  Smoking    : {p.smoker_status or '—'}",
            f"  ER / hosp  : {p.resp_hospital or '—'}",
        ]

    if p.dui_history == "yes":
        lines += [
            "",
            "▸ Driving / DUI",
            f"  Count   : {p.dui_count or '—'}",
            f"  Date    : {p.dui_date or '—'}",
            f"  License : {p.license_status or '—'}",
            f"  Program : {p.substance_program or '—'}",
            f"  BAC     : {p.bac or '—'}",
        ]

    lines += [
        "",
        "▸ Underwriting",
        f"  Existing Coverage : {p.existing_coverage or '—'}",
        f"  Prior Outcome     : {p.prior_outcome or '—'}",
        f"  Notes             : {p.underwriting_notes or '—'}",
    ]
    return "\n".join(lines)
