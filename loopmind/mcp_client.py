from mcp import Client

class McpClient:
    def __init__(self, url):
        self.client = Client(url)
        self._entered = False
        self._mcp_tools = None

    async def _ensure_entered(self):
        if not self._entered:
            await self.client.__aenter__()
            self._entered = True

    async def close(self):
        if self._entered:
            await self.client.__aexit__(None, None, None)
            self._entered = False

    async def call_tool(self, name, arguments):
        await self._ensure_entered()
        result = await self.client.call_tool(name, arguments)
        return result.structured_content

    # Private: Tool load the tools
    async def _read_tools(self):
        if self._mcp_tools:
            return
        await self._ensure_entered()
        self._mcp_tools = await self.client.list_tools()

    async def tool_names(self):
        await self._read_tools()
        return [t.name for t in self._mcp_tools.tools]

    async def get_tools(self):
        await self._read_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.input_schema,
            }
            for t in self._mcp_tools.tools
        ]
