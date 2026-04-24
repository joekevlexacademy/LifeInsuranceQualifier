import os
from datetime import datetime, timezone

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
]


async def run(location_id: str, access_token: str) -> dict:
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

    all_ok = all(s["ok"] for s in steps)

    if all_ok:
        config["setup_complete"] = True
        config["setup_at"] = datetime.now(timezone.utc).isoformat()
        sb.table("location_config").upsert(config).execute()
        steps.append({"label": "Configuration saved", "ok": True})
    else:
        steps.append({"label": "Configuration not saved — fix errors above", "ok": False})

    return {"steps": steps, "success": all_ok}
