"""Official MCP session adapter; no implicit server discovery or arbitrary tool calls."""

import json
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


class MCPGateway:
    def __init__(self, allowed_tools):
        self.allowed_tools = frozenset(allowed_tools)
        self.session = None
        self.stack = AsyncExitStack()

    async def connect_stdio(self, command, args=(), env=None):
        """Only operator-selected servers may be launched, never model-provided commands."""
        read, write = await self.stack.enter_async_context(
            stdio_client(StdioServerParameters(command=command, args=list(args), env=env or {}))
        )
        await self._initialize(read, write)
        return self

    async def connect_http(self, url):
        if not url.startswith("https://"):
            raise ValueError("Remote MCP requires verified HTTPS")
        read, write, _ = await self.stack.enter_async_context(streamablehttp_client(url))
        await self._initialize(read, write)
        return self

    async def _initialize(self, read, write):
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def list_tools(self):
        if self.session is None:
            raise RuntimeError("MCP is not connected")
        result = await self.session.list_tools()
        return [
            tool.model_dump(mode="json") for tool in result.tools if tool.name in self.allowed_tools
        ]

    async def call(self, name, arguments):
        if name not in self.allowed_tools:
            raise PermissionError("MCP tool is not authorized")
        if len(json.dumps(arguments)) > 32_768:
            raise ValueError("MCP input too large")
        if self.session is None:
            raise RuntimeError("MCP is not connected")
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError("MCP server reported a tool error")
        output = result.model_dump(mode="json")
        if len(json.dumps(output)) > 65_536:
            raise ValueError("MCP result exceeds context budget")
        return output

    async def close(self):
        await self.stack.aclose()
        self.session = None
