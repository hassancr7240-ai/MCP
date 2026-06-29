import os
import json
import asyncio
import anthropic
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from mcp.client.sse import sse_client
from mcp import ClientSession

MCP_URL = "https://registry-mcp-server.azurewebsites.net/sse"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MCP_TIMEOUT = 30

_cached_tools = []
_cached_tool_schemas = []
_mcp_connected = False


async def refresh_tools():
    global _cached_tools, _cached_tool_schemas, _mcp_connected
    try:
        async with asyncio.timeout(MCP_TIMEOUT):
            async with sse_client(MCP_URL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    _cached_tools = [{"name": t.name, "description": t.description} for t in tools.tools]
                    _cached_tool_schemas = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {"type": "object", "properties": {}},
                        }
                        for t in tools.tools
                    ]
                    _mcp_connected = True
    except Exception as e:
        _mcp_connected = False
        print(f"MCP connection failed: {e}")


@asynccontextmanager
async def lifespan(app):
    await refresh_tools()
    yield


app = FastAPI(lifespan=lifespan)


def build_html():
    if _mcp_connected:
        dot_class = "status-dot"
        status_text = "Connected to Azure MCP Server"
        tools_html = ", ".join(t["name"] for t in _cached_tools)
        tools_list = "".join(
            f'<li><b>{t["name"]}</b> — {t["description"]}</li>' for t in _cached_tools
        )
    else:
        dot_class = "status-dot err"
        status_text = "Disconnected"
        tools_html = "none"
        tools_list = "<li>Could not load tools</li>"

    return f"""<!DOCTYPE html>
<html>
<head>
  <title>Registry MCP Server - Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Arial,sans-serif;background:#f5f6fa;height:100vh;display:flex;flex-direction:column}}
    .header{{background:#2d3436;color:white;padding:16px 24px;display:flex;align-items:center;gap:16px;flex-shrink:0}}
    .header h1{{font-size:20px}}
    .status-dot{{width:10px;height:10px;border-radius:50%;background:#00b894;display:inline-block}}
    .status-dot.err{{background:#d63031}}
    .tabs{{display:flex;background:white;border-bottom:2px solid #e0e0e0;flex-shrink:0}}
    .tab{{padding:12px 28px;cursor:pointer;font-weight:bold;color:#636e72;border-bottom:3px solid transparent;margin-bottom:-2px}}
    .tab.active{{color:#0984e3;border-bottom-color:#0984e3}}
    .tab-content{{display:none;flex:1;overflow:hidden}}
    .tab-content.active{{display:flex;flex-direction:column}}
    .chat-wrap{{display:flex;flex-direction:column;height:100%;padding:16px;gap:12px}}
    .tools-bar{{background:white;border-radius:8px;padding:12px 16px;font-size:13px;color:#636e72;flex-shrink:0}}
    .tools-bar b{{color:#0984e3}}
    .messages{{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding:4px 0}}
    .msg{{max-width:75%;padding:12px 16px;border-radius:12px;line-height:1.5;font-size:14px;white-space:pre-wrap}}
    .msg.user{{background:#0984e3;color:white;align-self:flex-end;border-bottom-right-radius:4px}}
    .msg.assistant{{background:white;color:#2d3436;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
    .msg.tool{{background:#dfe6e9;color:#2d3436;align-self:flex-start;font-family:monospace;font-size:12px;border-radius:8px}}
    .msg.thinking{{background:#ffeaa7;color:#2d3436;align-self:flex-start;font-style:italic;font-size:13px}}
    .input-row{{display:flex;gap:8px;flex-shrink:0}}
    .input-row input{{flex:1;padding:12px 16px;border:1px solid #ddd;border-radius:24px;font-size:14px;outline:none}}
    .input-row input:focus{{border-color:#0984e3}}
    .input-row button{{padding:12px 24px;background:#0984e3;color:white;border:none;border-radius:24px;cursor:pointer;font-size:14px;font-weight:bold}}
    .input-row button:hover{{background:#0768b3}}
    .input-row button:disabled{{background:#b2bec3;cursor:not-allowed}}
    .tools-wrap{{padding:24px;overflow-y:auto}}
    .card{{background:white;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
    .card h2{{margin-bottom:16px;color:#2d3436}}
    label{{display:block;margin-top:10px;font-weight:bold;font-size:13px;color:#636e72}}
    input[type=text]{{width:100%;padding:8px 12px;margin-top:4px;border:1px solid #ddd;border-radius:6px;font-size:14px}}
    .run-btn{{margin-top:14px;padding:10px 24px;background:#0984e3;color:white;border:none;border-radius:6px;cursor:pointer;font-size:14px}}
    .run-btn:hover{{background:#0768b3}}
    pre{{background:#2d3436;color:#dfe6e9;padding:14px;border-radius:6px;overflow-x:auto;font-size:13px;margin-top:8px;white-space:pre-wrap}}
  </style>
</head>
<body>
<div class="header">
  <span class="{dot_class}"></span>
  <h1>Registry MCP Server</h1>
  <span style="font-size:13px;color:#b2bec3">{status_text}</span>
</div>
<div class="tabs">
  <div class="tab active" onclick="switchTab('chat')">Chat</div>
  <div class="tab" onclick="switchTab('tools')">Test Tools</div>
</div>

<div class="tab-content active" id="tab-chat">
  <div class="chat-wrap">
    <div class="tools-bar">Available tools: <b>{tools_html}</b></div>
    <div class="messages" id="messages">
      <div class="msg assistant">Hi! I'm connected to your Azure MCP server. Ask me anything — I can run UOM conversions, update sales orders, or answer questions about your tools.

Available tools:
{chr(10).join(f"- {t['name']}: {t['description']}" for t in _cached_tools)}</div>
    </div>
    <div class="input-row">
      <input id="chat-input" type="text" placeholder="e.g. Convert item 100123 for org MAS..." onkeydown="if(event.key==='Enter')sendChat()"/>
      <button id="send-btn" onclick="sendChat()">Send</button>
    </div>
  </div>
</div>

<div class="tab-content" id="tab-tools">
  <div class="tools-wrap">
    <div class="card">
      <h2>Available Tools (live from registry)</h2>
      <ul>{tools_list}</ul>
    </div>
    <div class="card">
      <h2>Test: UOM Conversion</h2>
      <form onsubmit="runTool(event,'uom_conversion',['itemNumber','orgCode'])">
        <label>Item Number</label><input type="text" name="itemNumber" placeholder="e.g. 100123" required>
        <label>Org Code</label><input type="text" name="orgCode" placeholder="e.g. MAS" required>
        <button class="run-btn" type="submit">Run Live on Azure</button>
      </form>
      <pre id="result-uom_conversion" style="display:none"></pre>
    </div>
    <div class="card">
      <h2>Test: Update Order Request</h2>
      <form onsubmit="runTool(event,'update_order_request',['SO_NUMBER','REASON_CODE','REQUEST_DATE','APPOINTMENT_TYPE'])">
        <label>SO Number</label><input type="text" name="SO_NUMBER" placeholder="e.g. SO12345" required>
        <label>Reason Code</label><input type="text" name="REASON_CODE" placeholder="e.g. 02-Customer-CPU Carrier" required>
        <label>Request Date (ISO 8601)</label><input type="text" name="REQUEST_DATE" placeholder="e.g. 2026-06-20T10:00:00" required>
        <label>Appointment Type</label><input type="text" name="APPOINTMENT_TYPE" placeholder="e.g. NP" required>
        <button class="run-btn" type="submit">Run Live on Azure</button>
      </form>
      <pre id="result-update_order_request" style="display:none"></pre>
    </div>
  </div>
</div>

<script>
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(function(t,i) {{
    t.classList.toggle('active', ['chat','tools'][i] === name);
  }});
  document.querySelectorAll('.tab-content').forEach(function(t) {{
    t.classList.remove('active');
  }});
  document.getElementById('tab-' + name).classList.add('active');
}}

function addMsg(text, cls) {{
  var el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  var m = document.getElementById('messages');
  m.appendChild(el);
  m.scrollTop = m.scrollHeight;
  return el;
}}

function sendChat() {{
  var inp = document.getElementById('chat-input');
  var btn = document.getElementById('send-btn');
  var text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  btn.disabled = true;
  addMsg(text, 'user');
  var thinking = addMsg('Thinking...', 'thinking');

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/chat');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.timeout = 60000;
  xhr.onload = function() {{
    thinking.parentNode.removeChild(thinking);
    try {{
      var d = JSON.parse(xhr.responseText);
      if (d.tool_calls) {{
        d.tool_calls.forEach(function(tc) {{
          addMsg('Called tool: ' + tc.tool + '\\nInput: ' + JSON.stringify(tc.input, null, 2) + '\\nResult: ' + JSON.stringify(tc.result, null, 2), 'tool');
        }});
      }}
      addMsg(d.reply, 'assistant');
    }} catch(e) {{
      addMsg('Error parsing response', 'assistant');
    }}
    btn.disabled = false;
    inp.focus();
  }};
  xhr.onerror = function() {{
    thinking.textContent = 'Network error — please try again';
    btn.disabled = false;
  }};
  xhr.ontimeout = function() {{
    thinking.textContent = 'Request timed out — please try again';
    btn.disabled = false;
  }};
  xhr.send(JSON.stringify({{message: text}}));
}}

function runTool(e, name, fields) {{
  e.preventDefault();
  var form = e.target;
  var args = {{}};
  fields.forEach(function(f) {{ args[f] = form[f].value; }});
  var pre = document.getElementById('result-' + name);
  pre.style.display = 'block';
  pre.textContent = 'Running...';

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/tool/' + name);
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.timeout = 30000;
  xhr.onload = function() {{
    try {{
      pre.textContent = JSON.stringify(JSON.parse(xhr.responseText), null, 2);
    }} catch(e) {{
      pre.textContent = xhr.responseText;
    }}
  }};
  xhr.onerror = function() {{ pre.textContent = 'Network error'; }};
  xhr.ontimeout = function() {{ pre.textContent = 'Request timed out'; }};
  xhr.send(JSON.stringify(args));
}}
</script>
</body>
</html>"""


async def call_mcp_tool(tool_name, arguments):
    async with asyncio.timeout(MCP_TIMEOUT):
        async with sse_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return "\n".join(getattr(c, "text", str(c)) for c in result.content)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(build_html())


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_message = body.get("message", "")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]
    tool_calls_log = []

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            tools=_cached_tool_schemas,
            system="You are a helpful assistant with access to business tools on an Azure MCP server. When a user asks something that requires a tool, call it and explain the result clearly. Be concise.",
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            reply = " ".join(b.text for b in response.content if hasattr(b, "text"))
            return JSONResponse({"reply": reply, "tool_calls": tool_calls_log})

        if response.stop_reason == "tool_use":
            assistant_content = []
            for block in response.content:
                if hasattr(block, "text"):
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})

            messages.append({"role": "assistant", "content": assistant_content})
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    try:
                        raw = await call_mcp_tool(block.name, block.input)
                        result = json.loads(raw) if raw.strip().startswith("{") else raw
                    except Exception as e:
                        result = {"error": str(e)}

                    tool_calls_log.append({"tool": block.name, "input": block.input, "result": result})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result) if isinstance(result, dict) else str(result),
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            reply = " ".join(b.text for b in response.content if hasattr(b, "text"))
            return JSONResponse({"reply": reply or "No response", "tool_calls": tool_calls_log})


@app.post("/tool/{tool_name}")
async def run_tool(tool_name: str, request: Request):
    args = await request.json()
    try:
        raw = await call_mcp_tool(tool_name, args)
        return JSONResponse(json.loads(raw) if raw.strip().startswith("{") else {"result": raw})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
