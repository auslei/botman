import asyncio
from fastmcp import Client, FastMCP

# In-memory server (ideal for testing)
server = FastMCP("TestServer")
client = Client(server)

# HTTP server
#client = Client("https://example.com/mcp")

# Local Python script
client = Client("browserbot/fastmcp_server.py")

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