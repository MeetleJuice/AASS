"""Operator-selected browser and MCP capabilities exposed to the worker."""

import asyncio
import base64
import os
from pathlib import Path

from settings import is_link
from tools.browser_session import BrowserSession
from tools.mcp_gateway import MCPGateway


class OperatorTools:
    def __init__(self, *, browser_origins=(), mcp_config=None):
        self.browser_origins = list(browser_origins)
        self.mcp_config = mcp_config
        self.browser = None
        self.pending_image = None

    def describe(self):
        return {
            "browser_origins": self.browser_origins,
            "mcp_tools": self.mcp_config.get("allowed_tools", []) if self.mcp_config else [],
        }

    def browser_action(self, action, artifact_dir):
        if not self.browser_origins:
            raise PermissionError("Browser access was not configured by the operator")
        if self.browser is None:
            self.browser = BrowserSession(self.browser_origins)
        operation = action.get("operation")
        if operation == "navigate":
            return self.browser.navigate(action["url"])
        if operation == "click":
            self.browser.click(action.get("selector"), x=action.get("x"), y=action.get("y"))
            return "Click completed"
        if operation == "screenshot":
            path = Path(artifact_dir) / "browser.png"
            if is_link(path):
                raise PermissionError("Screenshot destination cannot be a link")
            self.browser.screenshot(path)
            if path.stat().st_size > 256 * 1024:
                raise ValueError("Browser screenshot exceeds image input limit")
            self.pending_image = base64.b64encode(path.read_bytes()).decode("ascii")
            return {
                "artifact": str(path),
                "note": "Screenshot saved and attached to the next local worker request.",
            }
        if operation == "text":
            return self.browser.text()
        raise ValueError("Unknown browser operation")

    def mcp_action(self, name, arguments):
        if self.mcp_config is None:
            raise PermissionError("MCP access was not configured by the operator")

        async def call():
            config = self.mcp_config
            gateway = MCPGateway(config["allowed_tools"])
            try:
                async with asyncio.timeout(30):
                    if "url" in config:
                        await gateway.connect_http(config["url"])
                    else:
                        # Pass only explicit binding names, not the entire host environment.
                        names = config.get("environment_names", [])
                        await gateway.connect_stdio(
                            config["command"],
                            config.get("args", []),
                            env={n: os.environ[n] for n in names if n in os.environ},
                        )
                    return await gateway.call(name, arguments)
            finally:
                await gateway.close()

        return asyncio.run(call())

    def consume_image(self):
        image, self.pending_image = self.pending_image, None
        return image

    def close(self):
        if self.browser:
            self.browser.close()
            self.browser = None
