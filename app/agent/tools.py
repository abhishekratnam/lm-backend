"""The agent's two generic tools: run_graphql and get_schema."""

from __future__ import annotations

import json

from ..hasura import client
from ..hasura.schema import get_schema

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_graphql",
            "description": (
                "Execute one GraphQL request (query or mutation) against Hasura. Hasura exposes "
                "the whole Postgres schema: every table as query/mutation root fields, nested "
                "relationships, aggregates (e.g. orders_aggregate) and _by_pk lookups. Returns the "
                "'data' payload as JSON, or a HASURA_ERROR string you should fix and retry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The GraphQL document."},
                    "variables": {
                        "type": "object",
                        "description": "Optional variables for the document.",
                        "additionalProperties": True,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": (
                "Return the live database schema (tables, columns, relationships) as compact text. "
                "Use it before writing GraphQL whenever unsure about names or fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "boolean",
                        "description": "Re-introspect instead of using the cache.",
                    }
                },
            },
        },
    },
]


async def execute_tool(name: str, raw_arguments: str) -> str:
    """Run one tool call and return a string result (errors are strings too, so the model can recover)."""
    if name == "run_graphql":
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return f"ARGUMENT_ERROR: invalid JSON arguments ({exc})"
        query = args.get("query")
        if not query or not isinstance(query, str):
            return "ARGUMENT_ERROR: 'query' (string) is required"
        variables = args.get("variables") if isinstance(args.get("variables"), dict) else None
        try:
            data = await client.graphql(query, variables)
        except client.HasuraError as exc:
            return f"HASURA_ERROR: {exc}"
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    if name == "get_schema":
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            return await get_schema(force=bool(args.get("refresh")))
        except client.HasuraError as exc:
            return f"HASURA_ERROR: {exc}"

    return f"TOOL_ERROR: unknown tool '{name}'"
