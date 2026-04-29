import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client

from . import ghl

FIELDS = [
    {
        "name": "LIQ Triage State",
        "data_type": "SINGLE_OPTIONS",
        "options": ["Clean", "Follow-up Required", "Elevated Attention"],
        "config_key": "field_triage_state_id",
    },
    {
        "name": "LIQ Product Direction",
        "data_type": "TEXT",
        "config_key": "field_product_direction_id",
    },
    {
        "name": "LIQ Active Dependencies",
        "data_type": "TEXT",
        "config_key": "field_active_deps_id",
    },
    {
        "name": "LIQ Coverage Amount",
        "data_type": "TEXT",
        "config_key": "field_coverage_amount_id",
    },
    {
        "name": "LIQ Product Type",
        "data_type": "TEXT",
        "config_key": "field_product_type_id",
    },
    {
        "name": "LIQ Budget",
        "data_type": "TEXT",
        "config_key": "field_budget_id",
    },
    {
        "name": "LIQ Urgency",
        "data_type": "SINGLE_OPTIONS",
        "options": ["Immediately", "Within 30 days", "Within 60 days", "Just exploring"],
        "config_key": "field_urgency_id",
    },
    {
        "name": "LIQ Occupation",
        "data_type": "TEXT",
        "config_key": "field_occupation_id",
    },
    {
        "name": "LIQ Height",
        "data_type": "TEXT",
        "config_key": "field_height_id",
    },
    {
        "name": "LIQ Weight",
        "data_type": "TEXT",
        "config_key": "field_weight_id",
    },
    {
        "name": "LIQ Medications",
        "data_type": "LARGE_TEXT",
        "config_key": "field_medications_id",
    },
    {
        "name": "LIQ Existing Coverage",
        "data_type": "SINGLE_OPTIONS",
        "options": ["No current coverage", "Some coverage in force", "Actively replacing coverage"],
        "config_key": "field_existing_coverage_id",
    },
    {
        "name": "LIQ Prior Outcome",
        "data_type": "SINGLE_OPTIONS",
        "options": ["No recent application", "Approved as applied", "Rated", "Postponed", "Declined"],
        "config_key": "field_prior_outcome_id",
    },
    {
        "name": "LIQ Underwriting Notes",
        "data_type": "LARGE_TEXT",
        "config_key": "field_underwriting_notes_id",
    },
    {
        "name": "LIQ Qualification Summary",
        "data_type": "LARGE_TEXT",
        "config_key": "field_qual_summary_id",
    },
]

MENU_NAME = "Life Insurance Qualifier"


async def run(
    location_id: str,
    access_token: str,
    company_id: Optional[str] = None,
    agency_token: Optional[str] = None,
) -> dict:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    steps = []
    config: dict = {"location_id": location_id}

    # Check which fields already exist so re-running setup is safe
    try:
        existing = await ghl.list_custom_fields(access_token, location_id)
        existing_by_name = {f["name"]: f for f in existing}
    except Exception as exc:
        return {
            "steps": [{"label": f"GHL API error: {exc}", "ok": False}],
            "success": False,
        }

    for field_def in FIELDS:
        label = field_def["name"]
        try:
            if label in existing_by_name:
                config[field_def["config_key"]] = existing_by_name[label]["id"]
                steps.append({"label": f"{label} field found", "ok": True})
            else:
                result = await ghl.create_custom_field(
                    access_token=access_token,
                    location_id=location_id,
                    name=label,
                    data_type=field_def["data_type"],
                    options=field_def.get("options"),
                )
                config[field_def["config_key"]] = result["id"]
                steps.append({"label": f"{label} field created", "ok": True})
        except Exception as exc:
            steps.append({"label": f"{label} field failed: {exc}", "ok": False})

    # steps[0..14] = the 15 fields. Compute all_ok before adding further steps.
    all_ok = all(s["ok"] for s in steps)

    # steps[15] — sidebar menu link (non-blocking: failure won't prevent config save)
    menu_token = agency_token or access_token
    menu_cid = company_id or location_id
    menu_url: str = ""
    try:
        existing_menus = await ghl.list_custom_menus(menu_token, menu_cid)
        base = os.environ["APP_BASE_URL"].rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        # GHL substitutes {{location.id}} with the active sub-account ID at runtime,
        # so one shared menu link works for every sub-account.
        menu_url = base + "/?location_id={{location.id}}"

        # Match by title only — URL no longer contains a fixed location_id.
        existing = next(
            (m for m in existing_menus
             if (m.get("title") or m.get("name")) == MENU_NAME),
            None,
        )
        already_dynamic = "location.id" in existing.get("url", "") if existing else False
        if existing and existing.get("openMode") == "iframe" and already_dynamic:
            steps.append({"label": "Sidebar menu link found", "ok": True})
        elif existing:
            # Upgrade: switch to iframe mode and/or replace hardcoded URL with template
            menu_id = existing.get("id") or existing.get("_id")
            await ghl.update_custom_menu(
                access_token=menu_token,
                menu_id=menu_id,
                name=MENU_NAME,
                url=menu_url,
                location_id=location_id,
            )
            steps.append({"label": "Sidebar menu link updated to dynamic URL", "ok": True})
        else:
            await ghl.create_custom_menu(
                access_token=menu_token,
                company_id=menu_cid,
                name=MENU_NAME,
                url=menu_url,
                location_id=location_id,
            )
            steps.append({"label": "Sidebar menu link created", "ok": True})
    except Exception as exc:
        steps.append({"label": f"Sidebar menu link failed: {exc} [url={menu_url!r}]", "ok": False})

    # steps[16] — config save
    if all_ok:
        config["setup_complete"] = True
        config["setup_at"] = datetime.now(timezone.utc).isoformat()
        sb.table("location_config").upsert(config).execute()
        steps.append({"label": "Configuration saved", "ok": True})
    else:
        steps.append({"label": "Configuration not saved — fix errors above", "ok": False})

    return {"steps": steps, "success": all_ok}
