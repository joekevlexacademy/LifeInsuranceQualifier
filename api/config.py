import psycopg2.extras

from .db import get_conn


def get_config(location_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM location_config WHERE location_id = %s",
                (location_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def is_setup_complete(location_id: str) -> bool:
    cfg = get_config(location_id)
    return bool(cfg and cfg.get("setup_complete"))
