import os
from datetime import datetime, timezone

from supabase import create_client

from . import ghl

GROUP_NAME = "Life Insurance Qualifier"

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


async def _get_or_create_group(access_token: str, location_id: str) -> tuple:
    try:
        groups = await ghl.list_custom_field_groups(access_token, location_id)
        for g in groups:
            if g.get("name") == GROUP_NAME:
                return g["id"], None
        result = await ghl.create_custom_field_group(access_token, location_id, GROUP_NAME)
        gid = result.get("id")
        if not gid:
            return None, f"API returned no id: {result}"
        return gid, None
    except Exception as exc:
        return None, str(exc)


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

    group_id, group_err = await _get_or_create_group(access_token, location_id)
    if group_id:
        steps.append({"label": f'Field group "{GROUP_NAME}" ready', "ok": True})
    else:
        steps.append({"label": f"Field group skipped: {group_err}", "ok": True})

    for field_def in FIELDS:
        label = field_def["name"]
        try:
            if label in existing_by_name:
                field_id = existing_by_name[label]["id"]
                config[field_def["config_key"]] = field_id
                if group_id:
                    try:
                        await ghl.update_custom_field(
                            access_token, location_id, field_id, {"groupId": group_id}
                        )
                    except Exception:
                        pass
                steps.append({"label": f"{label} field found", "ok": True})
            else:
                result = await ghl.create_custom_field(
                    access_token=access_token,
                    location_id=location_id,
                    name=label,
                    data_type=field_def["data_type"],
                    options=field_def.get("options"),
                    group_id=group_id,
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
