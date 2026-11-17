"""Bootstraps Hasura: waits for it, tracks every public table, creates FK relationships."""

from __future__ import annotations

import asyncio
import logging

from .config import get_settings
from .hasura import client
from .hasura.schema import get_schema, warm

log = logging.getLogger("bootstrap")

FKS_SQL = """
select kcu.table_name, kcu.column_name, ccu.table_name as ref_table
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name
 and tc.constraint_schema = kcu.constraint_schema
join information_schema.constraint_column_usage ccu
  on ccu.constraint_name = tc.constraint_name
 and ccu.constraint_schema = tc.constraint_schema
where tc.constraint_type = 'FOREIGN KEY' and tc.constraint_schema = 'public'
order by kcu.table_name, kcu.column_name
"""


def build_track_ops(tables: list[str], fks: list[tuple[str, str, str]]) -> list[tuple[str, dict]]:
    """Track tables, then derive object/array relationships from foreign keys.

    Naming: object rel on the child table = column minus `_id` (e.g. user_id -> user);
    array rel on the parent table = child table name. Suffixed on conflicts.
    """
    ops: list[tuple[str, dict]] = []

    for table in tables:
        ops.append(
            ("pg_track_table", {"source": "default", "table": {"schema": "public", "name": table}})
        )

    used_object: dict[str, set] = {}
    used_array: dict[str, set] = {}

    def unique(table: str, base: str, used: dict[str, set]) -> str:
        seen = used.setdefault(table, set())
        name, n = base, 2
        while name in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name)
        return name

    for table, column, ref in fks:
        base = column[:-3] if column.endswith("_id") and len(column) > 3 else f"fk_{column}"
        ops.append(
            (
                "pg_create_object_relationship",
                {
                    "source": "default",
                    "table": {"schema": "public", "name": table},
                    "name": unique(table, base, used_object),
                    "using": {"foreign_key_constraint_on": column},
                },
            )
        )
        # Array rel: the FK column lives on the child table; v2.42+ requires
        # the explicit {table, columns} form (a bare column string fails to parse).
        ops.append(
            (
                "pg_create_array_relationship",
                {
                    "source": "default",
                    "table": {"schema": "public", "name": ref},
                    "name": unique(ref, table, used_array),
                    "using": {
                        "foreign_key_constraint_on": {
                            "table": {"schema": "public", "name": table},
                            "columns": [column],
                        }
                    },
                },
            )
        )

    return ops


async def _run_sql_rows(sql: str) -> list[list[str | None]]:
    rows = await client.run_sql(sql)
    return rows[1:] if rows else []


async def run() -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        log.warning("LLM_API_KEY is not set — /chat will fail until it is configured (see .env.example)")

    reachable = False
    for attempt in range(60):
        try:
            await client.ping()
            reachable = True
            break
        except Exception:
            if attempt == 0:
                log.info("Waiting for Hasura at %s ...", settings.hasura_url)
            await asyncio.sleep(1)
    if not reachable:
        log.warning("Hasura not reachable after 60s — bootstrap skipped, will retry on next start")
        return

    try:
        tables = [
            t["name"]
            for t in await client.source_tables("default")
            if t.get("schema") == "public" and t.get("name")
        ]
        fks = [tuple(row) for row in await _run_sql_rows(FKS_SQL) if row and len(row) == 3]

        warnings: list[str] = []
        for kind, args in build_track_ops(tables, fks):
            try:
                await client.metadata(kind, args)
            except client.HasuraError as exc:
                if "already" in str(exc).lower():  # idempotent re-run
                    continue
                warnings.append(f"{kind}: {exc}")
        if warnings:
            log.warning("Some metadata operations failed: %s", "; ".join(warnings))

        await warm()
        schema_text = await get_schema()
        tracked = sum(1 for line in schema_text.splitlines() if line.startswith("TABLE "))
        if tracked == 0:
            log.error("Bootstrap ran but Hasura still exposes 0 tables — agent queries will fail; check warnings above")
        else:
            log.info("Hasura bootstrap ok — %d tables tracked, %d foreign keys linked", tracked, len(fks))
    except Exception as exc:
        log.warning("Hasura bootstrap incomplete: %s", exc)
