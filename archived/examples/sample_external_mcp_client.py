import asyncio
import subprocess
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    """Connect to external MCP server using stdio transport."""
    
    # Server command - same as used in langchain example
    server_params = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "--project",
            "./",
            "--with", 
            "fastmcp",
            "fastmcp",
            "run",
            "./botman/mcp/server.py"
        ]
    )
    
    print("Connecting to external MCP server...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()
            
            print("Connected successfully!")
            
            # List available tools
            tools_result = await session.list_tools()
            print(f"\nFound {len(tools_result.tools)} tools:")
            
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # List available resources  
            try:
                resources_result = await session.list_resources()
                print(f"\nFound {len(resources_result.resources)} resources:")
                for resource in resources_result.resources:
                    print(f"  - {resource.name}: {resource.description}")
            except Exception as e:
                print(f"No resources available: {e}")
            
            # List available prompts
            try:
                prompts_result = await session.list_prompts()
                print(f"\nFound {len(prompts_result.prompts)} prompts:")
                for prompt in prompts_result.prompts:
                    print(f"  - {prompt.name}: {prompt.description}")
            except Exception as e:
                print(f"No prompts available: {e}")
            
            # Try calling a tool (if any are available)
            if tools_result.tools:
                print(f"\nTrying to call first tool: {tools_result.tools[0].name}")
                try:
                    # This is just an example - you'd need to provide proper arguments
                    # based on the tool's input schema
                    tool_result = await session.call_tool(
                        tools_result.tools[0].name, 
                        {}  # Empty arguments - adjust based on tool requirements
                    )
                    print(f"Tool result: {tool_result}")
                except Exception as e:
                    print(f"Tool call failed (expected - need proper arguments): {e}")

if __name__ == "__main__":
    asyncio.run(main())
