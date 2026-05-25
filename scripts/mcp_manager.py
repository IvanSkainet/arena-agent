#!/usr/bin/env python3
from __future__ import annotations
import asyncio, json, os, sys, urllib.request
from pathlib import Path
ROOT = Path(os.environ.get('ARENA_AGENT_HOME', Path.home() / 'arena-agent'))
MCP_DIR = ROOT / 'mcp'; CONFIG = MCP_DIR / 'mcp.json'
STREAM = os.environ.get('ARENA_MCP_STREAM_URL','http://127.0.0.1:8767')

def init_mcp():
    MCP_DIR.mkdir(exist_ok=True)
    if not CONFIG.exists(): CONFIG.write_text(json.dumps({'mcpServers': {}}, indent=2))
def load_config(): init_mcp(); return json.loads(CONFIG.read_text())
def save_config(cfg): CONFIG.write_text(json.dumps(cfg, indent=2))
def http_json(path, payload=None, headers=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(STREAM+path, data=data, headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream', **(headers or {})}, method='POST' if payload is not None else 'GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read().decode('utf-8','replace')
async def run_mcp_client(server_name, action, tool_name=None, tool_args=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    cfg=load_config()
    if server_name not in cfg['mcpServers']: raise SystemExit(f"Error: MCP Server '{server_name}' not found.")
    srv=cfg['mcpServers'][server_name]; env=os.environ.copy(); env.update(srv.get('env', {}))
    params=StdioServerParameters(command=srv['command'], args=srv['args'], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if action == 'tools':
                tools=await session.list_tools(); print(json.dumps([{'name':t.name,'description':t.description,'schema':t.inputSchema} for t in tools.tools], indent=2))
            elif action == 'call':
                args=json.loads(tool_args) if tool_args else {}; res=await session.call_tool(tool_name, arguments=args)
                for c in res.content: print(c.text if c.type=='text' else f'[{c.type} content]')
def stream_health():
    st,h,b=http_json('/health'); print(b)
def stream_init():
    payload={'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}
    st,h,b=http_json('/mcp', payload); print(b)
def stream_tools():
    payload={'jsonrpc':'2.0','id':2,'method':'tools/list'}
    st,h,b=http_json('/mcp', payload); print(b)
def stream_call(name, args='{}'):
    payload={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':name,'arguments':json.loads(args)}}
    st,h,b=http_json('/mcp', payload); print(b)
def stream_sse_probe():
    req=urllib.request.Request(STREAM+'/mcp', headers={'Accept':'text/event-stream'})
    with urllib.request.urlopen(req, timeout=5) as r:
        data=r.read(400).decode('utf-8','replace')
        print(data)
def run():
    if len(sys.argv)<2:
        print('Usage: agentctl mcp [install|list|tools|call|stream-health|stream-init|stream-tools|stream-call|stream-sse]'); return
    action=sys.argv[1]
    if action=='install':
        if len(sys.argv)<4: print('Usage: agentctl mcp install <name> <command> [args...]'); return
        cfg=load_config(); cfg['mcpServers'][sys.argv[2]]={'command':sys.argv[3],'args':sys.argv[4:],'env':{}}; save_config(cfg); print(f"Installed MCP server '{sys.argv[2]}'")
    elif action=='list': print(json.dumps(load_config(), indent=2))
    elif action=='tools': asyncio.run(run_mcp_client(sys.argv[2], 'tools'))
    elif action=='call': asyncio.run(run_mcp_client(sys.argv[2], 'call', sys.argv[3], sys.argv[4] if len(sys.argv)>4 else '{}'))
    elif action=='stream-health': stream_health()
    elif action=='stream-init': stream_init()
    elif action=='stream-tools': stream_tools()
    elif action=='stream-call': stream_call(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else '{}')
    elif action=='stream-sse': stream_sse_probe()
    else: print('Unknown MCP action')
if __name__=='__main__': run()
