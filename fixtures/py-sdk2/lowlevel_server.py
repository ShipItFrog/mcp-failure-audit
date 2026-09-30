"""Deliberately broken MCP server -- official Python SDK 2.x, low-level Server API.

TEST FIXTURE for rule R5: the on_call_tool handler has no try/except, so an exception
escapes to the dispatcher instead of becoming an is_error tool result. Do not copy
this code into a real server.
"""

import anyio

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

INVENTORY = {"apple": 3}


async def list_tools(ctx, params):
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="stock",
                description="Return the stock count for an item.",
                input_schema={
                    "type": "object",
                    "properties": {"item": {"type": "string"}},
                    "required": ["item"],
                },
            )
        ]
    )


async def call_tool(ctx, params):
    # R5: no try/except -- a missing item raises KeyError, which reaches the client as a
    # JSON-RPC error (code 0, raw exception text) instead of an is_error tool result
    count = INVENTORY[params.arguments["item"]]
    return types.CallToolResult(content=[types.TextContent(type="text", text=str(count))])


server = Server("fixture-lowlevel-sdk2", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
