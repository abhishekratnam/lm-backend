"""Minimal async client for Hasura: GraphQL endpoint + metadata/run_sql API."""

from __future__ import annotations

import httpx

from ..config import get_settings

_client: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        # hasura_url is "<root>/v1/graphql"; derive the service root once.
        root = settings.hasura_url.rsplit("/v1/", 1)[0]
        _client = httpx.AsyncClient(
            base_url=root,
            headers={"x-hasura-admin-secret": settings.hasura_admin_secret},
            timeout=httpx.Timeout(30.0),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class HasuraError(RuntimeError):
    """Raised when Hasura returns errors or an unusable response."""


async def graphql(query: str, variables: dict | None = None) -> dict:
    """Execute one GraphQL document; returns the `data` payload."""
    resp = await http().post("/v1/graphql", json={"query": query, "variables": variables or {}})
    try:
        body = resp.json()
    except ValueError:
        raise HasuraError(f"non-JSON response from Hasura (http {resp.status_code}): {resp.text[:300]}")
    if body.get("errors"):
        raise HasuraError(body["errors"][0].get("message", str(body["errors"][0])))
    if "data" not in body:
        raise HasuraError(f"unexpected response from Hasura: {str(body)[:300]}")
    return body["data"]


async def metadata(kind: str, args: dict) -> dict:
    """Call the Hasura metadata API with a single operation."""
    resp = await http().post("/v1/metadata", json={"type": kind, "args": args})
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:400]}
    if resp.status_code != 200:
        message = (
            body.get("message")
            or (body.get("errors") or [{}])[0].get("message")
            or str(body)[:400]
        )
        raise HasuraError(f"{kind}: {message}")
    return body


async def run_sql(sql: str) -> list[list[str | None]]:
    """Run SQL via Hasura's /v1/query endpoint.

    Note: recent Hasura versions no longer accept run_sql on /v1/metadata
    ('unknown metadata command "sql"'), it is served on /v1/query.
    """
    resp = await http().post("/v1/query", json={"type": "run_sql", "args": {"sql": sql}})
    try:
        body = resp.json()
    except ValueError:
        raise HasuraError(f"non-JSON response from /v1/query (http {resp.status_code}): {resp.text[:300]}")
    if resp.status_code != 200 or body.get("error"):
        raise HasuraError(f"run_sql: {str(body)[:400]}")
    if body.get("result_type") != "TuplesOk":
        return []
    return body.get("result", [])


async def source_tables(source: str = "default") -> list[dict]:
    """Tables Hasura sees in a source: [{"schema": "public", "name": "users"}, ...]."""
    return await metadata("pg_get_source_tables", {"source": source})


async def ping() -> None:
    await graphql("{ __typename }")
