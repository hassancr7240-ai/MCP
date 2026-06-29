import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    url = "https://registry-mcp-server.azurewebsites.net/sse"
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("AVAILABLE TOOLS:")
            for t in tools.tools:
                print(" -", t.name, ":", t.description)

asyncio.run(main())
