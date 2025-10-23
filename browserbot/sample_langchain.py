from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from dotenv import load_dotenv
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from langchain.agents import create_agent

import os
os.environ["FASTMCP_SILENT"] = "1"


load_dotenv(".env")  # load environment variables from .env file

# `thread_id` is a unique identifier for a given conversation.
CONFIG: RunnableConfig = {"configurable": {"thread_id": "1"}}
CHECKPOINTER = InMemorySaver()


class ResponseFormat(BaseModel):
    """Structured response schema for the agent."""

    description: str = Field(..., description="A brief description of your findings.")
    hyper_links: Sequence[str] | None = Field(
        None, description="Links that support the answer."
    )


@dataclass
class Context:
    """Custom runtime context schema."""

    user_id: str


MODEL = ChatOllama(model="gpt-oss:20b", temperature=0)


@tool
def get_weather(location: str) -> str:
    """Get weather for a location."""
    return f"Weather in {location}: Sunny, 72°F"


@tool
def get_user_location(runtime: ToolRuntime[Context]) -> str:
    """Retrieve user information based on user ID."""
    user_id = runtime.context.user_id
    return "Florida" if user_id == "1" else "SF"


SYSTEM_PROMPT = """You are a helpful web research assistant. Use the available tools to search for information and provide comprehensive responses.

When searching for LinkedIn profiles:
1. First use navigate tool to go to Google search with a specific query like "Anthony Sun LinkedIn site:linkedin.com"
2. Then use list_links to find LinkedIn profile links
3. Navigate to the actual LinkedIn profile
4. Extract relevant information like job titles, company, etc.
5. Provide a structured response with the findings

Always provide a complete response with your findings, even if the search doesn't return perfect results."""


async def _display_stream(
    chunks: AsyncIterator[dict[str, Sequence[BaseMessage]]],
) -> None:
    """Pretty-print streaming updates from the agent."""
    async for chunk in chunks:
        for node_name, node_data in chunk.items():
            messages = node_data.get("messages", [])
            if node_name == "agent":
                for msg in messages:
                    content = getattr(msg, "content", "")
                    if isinstance(content, str) and content.strip():
                        print(f"💭 Agent: {content[:200]}...")
                    for tool_call in getattr(msg, "tool_calls", []) or []:
                        name = tool_call.get("name", "<unknown>")
                        args = tool_call.get("args", {})
                        print(f"🔧 Calling tool: {name}({args})")
            elif node_name == "tools":
                for msg in messages:
                    content = getattr(msg, "content", "")
                    if content:
                        print(f"📊 Tool result: {content}")
        print("-" * 30)


async def main() -> None:
    """Entry point for running the sample agent."""
    client = MultiServerMCPClient(
        {
            "browserbot": {
                "transport": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--project",
                    "./",
                    "--with",
                    "fastmcp",
                    "fastmcp",
                    "run",
                    "./browserbot/fastmcp_server.py",
                ],
            }
        }
    ) 

    async with client.session("browserbot") as session:
        mcp_tools = await client.get_tools()
        tools = [get_weather, get_user_location, *mcp_tools]

        agent = create_agent(
            model=MODEL,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=CHECKPOINTER,
            context_schema=Context,
            response_format=ResponseFormat,
        )

        print("Starting agent execution...")
        try:
            user_request = {
                "messages": [
                    {
                        "role": "user",
                        "content": "Search for Anthony Sun's LinkedIn profile and tell me about his professional background.",
                    }
                ]
            }

            async with agent.astream(
                user_request,
                stream_mode="updates",
                config=CONFIG,
                context=Context(user_id="1"),
            ) as stream:
                await _display_stream(stream)
        except Exception as exc:  # pragma: no cover - demo resilience
            print(f"Error during agent execution: {exc}")
            print(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(main())
