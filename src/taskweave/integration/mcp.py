"""Optional official MCP stdio transport; stdout contains protocol messages only."""
import asyncio
import json
from taskweave.core.validation import TaskError
from taskweave.infrastructure.agent_connection import AgentClient
from taskweave.integration.tools import tool_definitions, invoke


def build_server(home=None):
    try:
        from mcp.server.lowlevel import Server
        from mcp import types
    except ImportError as exc:
        raise TaskError('MCP_DEPENDENCY_MISSING', '请安装 taskweave[mcp] 可选依赖') from exc
    definitions = tool_definitions()
    client = AgentClient(home)

    async def listing(context, params):
        return types.ListToolsResult(tools=[types.Tool(name=item['name'], description=item['description'],
                                                       input_schema=item['parameters']) for item in definitions])

    async def calling(context, params):
        try:
            result = await asyncio.to_thread(invoke, client, params.name, params.arguments or {})
            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(result, ensure_ascii=False))],
                                        structured_content=result if isinstance(result, dict) else {'value': result})
        except TaskError as exc:
            return types.CallToolResult(is_error=True, content=[types.TextContent(type='text', text=json.dumps({'error': exc.document()}, ensure_ascii=False))])

    return Server('TaskWeave', version='0.1.0', instructions='Discover summaries, describe selected contracts, then author/execute. Read acceptance evidence; human decides in the workbench.',
                  on_list_tools=listing, on_call_tool=calling,
                  get_tool_input_schema=lambda name: next((item['parameters'] for item in definitions if item['name'] == name), None))


def run(home=None):
    server = build_server(home)
    from mcp.server.stdio import stdio_server

    async def serve():
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    asyncio.run(serve())
