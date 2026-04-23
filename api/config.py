import os
from supabase import create_client


def _sb():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def get_config(location_id: str) -> dict | None:
    result = (
        _sb()
        .table("location_config")
        .select("*")
        .eq("location_id", location_id)
        .single()
        .execute()
    )
    return result.data


def is_setup_complete(location_id: str) -> bool:
    cfg = get_config(location_id)
    return bool(cfg and cfg.get("setup_complete"))
