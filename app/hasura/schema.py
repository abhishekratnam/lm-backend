"""Introspects Hasura's GraphQL schema and renders it as compact text for the agent."""

from __future__ import annotations

from . import client

INTROSPECTION = """
query AgentSchema {
  __schema {
    queryType {
      fields {
        name
        type { kind name ofType { kind name ofType { kind name } } }
      }
    }
    types {
      kind
      name
      fields(includeDeprecated: true) {
        name
        type { kind name ofType { kind name ofType { kind name } } }
      }
    }
  }
}
"""

# Hasura helper types that are returned by root fields but are not tables.
_NOT_TABLE_SUFFIXES = ("_aggregate", "_mutation_response", "_stream")


def _unwrap(t: dict) -> dict | None:
    while t and t.get("ofType") and t.get("kind") in ("NON_NULL", "LIST"):
        t = t["ofType"]
    return t


def _is_list(t: dict) -> bool:
    while t.get("kind") == "NON_NULL":
        t = t["ofType"]
    return t.get("kind") == "LIST"


def _type_str(t: dict | None) -> str:
    if not t:
        return "?"
    kind = t.get("kind")
    if kind == "NON_NULL":
        return _type_str(t.get("ofType")) + "!"
    if kind == "LIST":
        return "[" + _type_str(t.get("ofType")) + "]"
    return t.get("name") or kind


def _render(schema: dict) -> str:
    root_fields = (schema.get("queryType") or {}).get("fields") or []

    # Row types = unwrapped return types of the query root (users, orders, ...).
    row_types: set[str] = set()
    for field in root_fields:
        name = field.get("name") or ""
        if name.startswith("__"):
            continue
        base = _unwrap(field["type"])
        if base and base.get("name") and not base["name"].startswith("__"):
            if not base["name"].endswith(_NOT_TABLE_SUFFIXES):
                row_types.add(base["name"])

    objects = {
        t["name"]: t
        for t in schema.get("types", [])
        if t.get("kind") == "OBJECT" and t.get("name") in row_types
    }

    lines: list[str] = []
    for name in sorted(objects):
        lines.append(f"TABLE {name}")
        columns: list[str] = []
        rels: list[str] = []
        for field in objects[name].get("fields") or []:
            fname = field["name"]
            if fname.startswith("__"):
                continue
            base = _unwrap(field["type"])
            if base and base.get("name") in row_types:
                direction = "many" if _is_list(field["type"]) else "one"
                rels.append(f"rel {fname}: {direction} {base['name']}")
            else:
                columns.append(f"  {fname}: {_type_str(field['type'])}")
        lines.extend(columns)
        lines.extend("  " + rel for rel in rels)
    return "\n".join(lines)


_text_cache: str | None = None


async def get_schema(force: bool = False) -> str:
    """Compact schema text; cached after the first introspection."""
    global _text_cache
    if _text_cache is None or force:
        data = await client.graphql(INTROSPECTION)
        _text_cache = _render(data["__schema"])
    return _text_cache


async def warm() -> None:
    await get_schema(force=True)
