import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras

from .db import get_conn
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
        "name": "LIQ Applicant",
        "data_type": "TEXT",
        "config_key": "field_applicant_id",
    },
    {
        "name": "LIQ Product Type",
        "data_type": "SINGLE_OPTIONS",
        "options": ["Term life", "Whole life", "Universal life", "Final expense", "Mortgage protection", "Not sure yet"],
        "config_key": "field_product_type_id",
    },
    {
        "name": "LIQ Coverage Amount",
        "data_type": "TEXT",
        "config_key": "field_coverage_amount_id",
    },
    {
        "name": "LIQ Budget",
        "data_type": "TEXT",
        "config_key": "field_budget_id",
    },
    {
        "name": "LIQ Coverage Reason",
        "data_type": "TEXT",
        "config_key": "field_coverage_reason_id",
    },
    {
        "name": "LIQ Urgency",
        "data_type": "SINGLE_OPTIONS",
        "options": ["Immediately", "Within 30 days", "Within 60 days", "Just exploring"],
        "config_key": "field_urgency_id",
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
        "name": "LIQ Triage Flags",
        "data_type": "TEXT",
        "config_key": "field_triage_flags_id",
    },
    {
        "name": "LIQ Medications",
        "data_type": "LARGE_TEXT",
        "config_key": "field_medications_id",
    },
    {
        "name": "LIQ Active Dependencies",
        "data_type": "TEXT",
        "config_key": "field_active_deps_id",
    },
    {
        "name": "LIQ Dependency Details",
        "data_type": "LARGE_TEXT",
        "config_key": "field_dependency_details_id",
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
    steps = []
    config: dict = {"location_id": location_id}

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
        await asyncio.sleep(0.4)

    all_ok = all(s["ok"] for s in steps)

    # Sidebar menu link (non-blocking)
    menu_cid = company_id or location_id
    menu_url: str = ""
    if not agency_token:
        steps.append({
            "label": (
                "Sidebar menu link skipped — enter an agency-level Private Integration key "
                "(agency view → Settings → Private Integrations) and re-run setup to enable"
            ),
            "ok": False,
        })
    else:
        try:
            existing_menus = await ghl.list_custom_menus(agency_token, menu_cid)
            base = os.environ["APP_BASE_URL"].rstrip("/")
            if not base.startswith("http"):
                base = "https://" + base
            menu_url = base + "/?location_id={{location.id}}"

            existing = next(
                (m for m in existing_menus
                 if (m.get("title") or m.get("name")) == MENU_NAME),
                None,
            )
            if existing:
                menu_id = existing.get("id") or existing.get("_id")
                raw_locs = existing.get("locations") or []
                existing_locs = [
                    (loc["id"] if isinstance(loc, dict) else loc)
                    for loc in raw_locs
                ]
                if location_id not in existing_locs:
                    existing_locs.append(location_id)
                existing_url = existing.get("url", "")
                is_iframe = existing.get("openMode") == "iframe"
                already_listed = location_id in [
                    (loc["id"] if isinstance(loc, dict) else loc)
                    for loc in (existing.get("locations") or [])
                ]
                url_clean = "location_id={{location.id}}" in existing_url
                if is_iframe and url_clean and already_listed:
                    steps.append({"label": "Sidebar menu link found", "ok": True})
                else:
                    await ghl.update_custom_menu(
                        access_token=agency_token,
                        menu_id=menu_id,
                        name=MENU_NAME,
                        url=menu_url,
                        locations=existing_locs,
                    )
                    steps.append({"label": "Sidebar menu link updated", "ok": True})
            else:
                await ghl.create_custom_menu(
                    access_token=agency_token,
                    company_id=menu_cid,
                    name=MENU_NAME,
                    url=menu_url,
                    locations=[location_id],
                )
                steps.append({"label": "Sidebar menu link created", "ok": True})
        except Exception as exc:
            err_str = str(exc)
            label = f"Sidebar menu link failed: {exc} [url={menu_url!r}]"
            if company_id and "Invalid Private Integration" in err_str:
                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE installations SET access_token='', refresh_token='' WHERE location_id = %s",
                                (company_id,),
                            )
                except Exception:
                    pass
                label += " — agency key appears revoked; re-run setup to enter a new one"
            steps.append({"label": label, "ok": False})

    # Save config to DB
    if all_ok:
        config["setup_complete"] = True
        config["setup_at"] = datetime.now(timezone.utc).isoformat()
        cols = list(config.keys())
        vals = [config[k] for k in cols]
        col_names = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "location_id")
        sql = (
            f"INSERT INTO location_config ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT (location_id) DO UPDATE SET {update_clause}"
        )
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, vals)
        steps.append({"label": "Configuration saved", "ok": True})
    else:
        steps.append({"label": "Configuration not saved — fix errors above", "ok": False})

    return {"steps": steps, "success": all_ok}
