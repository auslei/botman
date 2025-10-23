import asyncio
from fastmcp import Client, FastMCP

# Option 1: In-memory server (for testing - create some tools first)
server = FastMCP("TestServer")

@server.tool()
def test_tool(message: str) -> str:
    """A simple test tool."""
    return f"Test response: {message}"

client = Client(server)

# Option 2: For external MCP server, use subprocess approach
# This would require a different client setup - let's stick with in-memory for now

async def main():
    async with client:
        # Basic server interaction
        await client.ping()
        
        # List available operations
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        
        for t in tools:
            print(f"tool: {t.name}, tool description: {t.description}")
            print(f"""inputs: {t.inputSchema}
                      outputs: {t.outputSchema}\n""")
        
        #print(tools)
        
        # Execute operations
        #result = await client.call_tool("open_session", {"url": "https://www.google.com"})

        #print(result)

asyncio.run(main())