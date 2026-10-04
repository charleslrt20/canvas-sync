import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "list_courses", "upcoming", "missing", "assignment_details",
    "announcements", "grades", "list_files", "read_file",
}


async def _session_roundtrip(env):
    params = StdioServerParameters(command=sys.executable, args=["-m", "canvas_mcp.server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("missing", {})
            return listed.tools, result


def test_stdio_server_lists_read_only_tools_and_reports_missing_token(tmp_path):
    empty_env = tmp_path / ".env"
    empty_env.write_text("")
    tools, result = anyio.run(_session_roundtrip, {"CANVAS_ENV_FILE": str(empty_env), "PATH": "/usr/bin:/bin"})
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    text = result.content[0].text
    assert text == "Canvas error: CANVAS_TOKEN is not set"


def test_unexpected_exceptions_become_short_messages(monkeypatch):
    from canvas_mcp import server

    class Boom:
        def missing(self):
            raise KeyError("weird canvas json")

    monkeypatch.setattr(server, "_tools", lambda: Boom())
    assert server._run("missing") == "Canvas error: unexpected response from Canvas (KeyError)"
