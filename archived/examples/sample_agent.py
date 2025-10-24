# agent.py
import os
import asyncio
import mcp
from openai import OpenAI
from agents  import Agent, Runner, trace
from agents.mcp import MCPServerStdio

from dotenv import load_dotenv
from pathlib import Path

# Load .env from the project root (adjust path if your .env is elsewhere)
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)  # loads into os.environ

# 1) OpenAI client
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="https://api.openai.com/v1")
#client = OpenAI(api_key=os.environ.get('DEEPSEEK_API_KEY'), base_url="https://api.deepseek.com")

async def main():
    async with MCPServerStdio(
        name="Filesystem Server via npx",
        params={
            "command": "uv",
            "args": [
                "run",
                "--project",
                "G:\\dev\\botman",
                "--with",
                "fastmcp",
                "fastmcp",
                "run",
                "G:\\dev\\botman\\botman\\mcp\\server.py"
            ],
        }
    ) as mcp_server:
        agent = Agent(name="BrowserBot Agent",
                      mcp_servers=[mcp_server],
                      model="gpt-5-nano",
                      handoff_description="Use the browser automation tools to interact with web pages as needed.")
        with trace("browser workflow"):
            result = await Runner.run(agent,"Browse the internet and find the linkedin page of Anthony Sun, he worked in the tech industry in Australia. Return the job titles listed on his profile.")
            print(result.final_output)

# Run the async function
asyncio.run(main())

