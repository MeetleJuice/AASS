import os
import secrets
import subprocess
import sys
import time
import uuid

import pytest

from tools import postgres_mcp
from tools.mcp_gateway import MCPGateway


@pytest.fixture
def live_postgres(monkeypatch):
    if os.environ.get("AASS_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set AASS_POSTGRES_INTEGRATION=1 for disposable PostgreSQL integration")
    import psycopg

    name = "aass-pg-test-" + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    child_env = os.environ.copy()
    child_env["POSTGRES_PASSWORD"] = password
    image = (
        "postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--memory=256m",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD",
            image,
        ],
        env=child_env,
        capture_output=True,
        check=True,
    )
    try:
        port = (
            subprocess.run(
                ["docker", "port", name, "5432"], capture_output=True, text=True, check=True
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(dsn, connect_timeout=1) as conn:
                    conn.execute("CREATE TABLE public.aass_fixture (id integer, label text)")
                    conn.execute("INSERT INTO public.aass_fixture VALUES (42, %s)", ("verified",))
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Disposable PostgreSQL did not become ready") from None
                time.sleep(0.25)
        monkeypatch.setenv("AASS_POSTGRES_DSN", dsn)
        monkeypatch.setenv("AASS_POSTGRES_SCHEMAS", "public")
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


async def test_postgres_readonly_mcp_round_trip(live_postgres):
    gateway = MCPGateway(["list_tables", "read_rows"])
    try:
        await gateway.connect_stdio(
            sys.executable,
            ["-m", "tools.postgres_mcp"],
            env={"AASS_POSTGRES_DSN": live_postgres, "AASS_POSTGRES_SCHEMAS": "public"},
        )
        tables = await gateway.call("list_tables", {})
        assert "aass_fixture" in str(tables)
        rows = await gateway.call(
            "read_rows", {"schema": "public", "table": "aass_fixture", "limit": 1}
        )
        assert "verified" in str(rows)
        with pytest.raises(RuntimeError, match="tool error"):
            await gateway.call("read_rows", {"schema": "pg_catalog", "table": "pg_authid"})
    finally:
        await gateway.close()


def test_postgres_transaction_is_readonly(live_postgres):
    import psycopg

    with postgres_mcp.connection() as conn:
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM public.aass_fixture")


def test_postgres_quoted_identifiers_prevent_sql_injection(live_postgres):
    import psycopg

    with pytest.raises(psycopg.errors.UndefinedTable):
        postgres_mcp.read_rows("public", "aass_fixture; DROP TABLE public.aass_fixture", 1)
    assert postgres_mcp.read_rows("public", "aass_fixture", 1)[0]["label"] == "verified"
