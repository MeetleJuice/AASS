"""Read-only PostgreSQL MCP tools. Operator supplies DSN and allowed schemas."""

import os

from mcp.server.fastmcp import FastMCP

server = FastMCP("aass-postgres-readonly")


def connection():
    import psycopg

    dsn = os.environ.get("AASS_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("AASS_POSTGRES_DSN is required")
    conn = psycopg.connect(
        dsn,
        connect_timeout=5,
        options="-c default_transaction_read_only=on "
        "-c statement_timeout=3000 -c lock_timeout=1000",
    )
    return conn


def allowed_schemas():
    return {
        s.strip() for s in os.environ.get("AASS_POSTGRES_SCHEMAS", "public").split(",") if s.strip()
    }


@server.tool()
def list_tables() -> list[dict]:
    """List tables only in operator-authorized schemas."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name LIMIT 100",
            (sorted(allowed_schemas()),),
        )
        return [{"schema": row[0], "table": row[1]} for row in cur.fetchall()]


@server.tool()
def read_rows(schema: str, table: str, limit: int = 20) -> list[dict]:
    """Read up to 100 rows from an authorized table; never accept arbitrary SQL."""
    from psycopg import sql
    from psycopg.rows import dict_row

    if schema not in allowed_schemas() or not 1 <= limit <= 100:
        raise ValueError("Schema or row limit not authorized")
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
                sql.Identifier(schema), sql.Identifier(table)
            ),
            (limit,),
        )
        # JSON-safe conversion and per-cell limits; gateway enforces total output limit.
        return [
            {key: str(value)[:4096] if value is not None else None for key, value in row.items()}
            for row in cur.fetchall()
        ]


if __name__ == "__main__":
    server.run(transport="stdio")
