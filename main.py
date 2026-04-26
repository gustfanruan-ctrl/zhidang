from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import jwt
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

app = FastAPI(title="智档", version="0.1.0")

STATE: dict[str, Any] = {
    "superadmin": None,
    "system_config": {
        "jiandaoyun_api_key_encrypted": "",
        "jiandaoyun_base_url": "https://api.jiandaoyun.com",
        "jiandaoyun_app_id": "",
        "main_entry_id": "",
        "field_mappings": {},
        "llm_provider": "dashscope",
        "llm_api_key_encrypted": "",
        "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "agent_a_model": "qwen-plus",
        "agent_b_model": "qwen-plus",
        "nl_chat_model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 4096,
        "agent_a_prompt": "你是一个专业的客户成功分析师。请从以下客户拜访会议转写中提取信息。",
        "agent_b_prompt": "你是一个客户档案管理专家。请将新提取的客户预期/场景与已有档案数据进行比对。",
        "nl_query_prompt": "你是一个客户档案查询助手。",
        "nl_modify_prompt": "你是一个客户档案修改助手。",
        "sso_shared_secret": "demo-secret",
        "sso_token_ttl_minutes": 5,
    },
    "transcripts": [],
    "operation_logs": [],
    "analytics_events": [],
}

SPEAKER_PATTERN = re.compile(r"^发言人\s*(\d+)\s+(\d{2}:\d{2}:\d{2})$")
JWT_SECRET = "zhidang-demo-jwt-secret"
DEFAULT_PROMPT_A = "你是一个专业的客户成功分析师。请从以下客户拜访会议转写中提取信息。"
DEFAULT_PROMPT_B = "你是一个客户档案管理专家。请将新提取的客户预期/场景与已有档案数据进行比对。"


class SuperadminInit(BaseModel):
    username: str
    password: str = Field(min_length=8)
    display_name: Optional[str] = None


class LoginPayload(BaseModel):
    username: str
    password: str


class SsoGeneratePayload(BaseModel):
    user_name: str
    user_id: str
    company_id: str


class ChatPayload(BaseModel):
    message: str
    session_id: str
    sso_user: dict[str, str] | None = None


class ReviewActionPayload(BaseModel):
    operation_id: str
    operation_type: str
    action: str
    agent_confidence: float = 0.0
    match_id: str | None = None
    edit_details: dict[str, Any] | None = None
    time_spent_seconds: int = 0
    card_position: int = 0
    total_cards: int = 0


class ReviewSessionPayload(BaseModel):
    transcript_id: str | None = None
    total_operations: int
    confirmed: int
    edited_then_confirmed: int
    deleted: int
    converted: int = 0
    final_action: str
    total_review_time_seconds: int
    avg_time_per_card_seconds: int


class TranscriptUploadResponse(BaseModel):
    transcript_id: str
    title: str
    segment_count: int
    status: str
    preview: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def hash_company_id(company_id: str) -> str:
    return hashlib.sha256(company_id.encode("utf-8")).hexdigest()


def parse_transcript(text: str) -> dict[str, Any]:
    lines = [l.rstrip() for l in text.strip().splitlines()]
    title = lines[0].strip() if lines else "未命名转写"
    segs = []
    current = None
    matched = False
    buf = []
    ts = None
    for line in lines[1:]:
        m = SPEAKER_PATTERN.match(line.strip())
        if m:
            matched = True
            if current is not None:
                segs.append({"speaker": f"发言人 {current}", "timestamp": ts, "text": "\n".join(buf).strip()})
            current = m.group(1)
            ts = m.group(2)
            buf = []
        elif line.strip():
            buf.append(line.strip())
    if current is not None:
        segs.append({"speaker": f"发言人 {current}", "timestamp": ts, "text": "\n".join(buf).strip()})
    if not matched:
        return {"title": title, "raw_text": text.strip(), "segments": []}
    return {"title": title, "raw_text": "\n".join(f"[{s['speaker']} {s['timestamp']}] {s['text']}" for s in segs), "segments": segs}


def track_event(event_type: str, operator: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]) -> None:
    STATE["analytics_events"].append({"event_id": str(uuid4()), "event_type": event_type, "timestamp": now_iso(), "operator": operator, "context": context, "payload": payload})


def log_operation(operation_type: str, payload: dict[str, Any], status: str = "success") -> None:
    STATE["operation_logs"].append({"id": str(uuid4()), "operation_type": operation_type, "request_payload": payload, "response_payload": {}, "status": status, "created_at": now_iso()})


def agent_a_mock(transcript: dict[str, Any]) -> dict[str, Any]:
    text = transcript.get("raw_text", "")
    return {"is_customer_visit": True, "confidence": 0.85, "company_name_guess": "某某科技有限公司" if ("科技" in text or "公司" in text) else "未知公司", "expectations": [{"summary": "实现质检自动化", "is_first_value": True, "description": "客户希望通过AI视觉识别实现产线质检自动化。", "estimated_start_time": "2026-06", "status": "未启动", "progress_note": "初步沟通需求", "source_quote": "我们希望能用AI来做质检", "speaker": "发言人 1", "timestamp": "00:00:03"}], "scenarios": [{"title": "质检缺陷识别", "is_first_value": True, "pain_point": "人工质检漏检率高、效率低", "core_metric_solution": "AI视觉识别，目标漏检率<1%", "value_quantification": "年节省质检人力成本约30万", "summary": "以AI替代人工质检", "source_quote": "目前质检全靠人工看", "speaker": "发言人 2", "timestamp": "00:01:23"}]}


def agent_b_mock(extraction_result: dict[str, Any]) -> dict[str, Any]:
    return {"company_id": "eb6dc9bc-a55c-11ea-ba0b-7cd30ab79bc4", "operations": [{"op_id": str(uuid4()), "type": "new_expectation", "data": extraction_result["expectations"][0], "source_quote": extraction_result["expectations"][0]["source_quote"], "confidence": 0.92}, {"op_id": str(uuid4()), "type": "new_scenario", "data": extraction_result["scenarios"][0], "source_quote": extraction_result["scenarios"][0]["source_quote"], "confidence": 0.88}]}


def shell(title: str, transcript_id: str = "") -> HTMLResponse:
    return HTMLResponse(f"""
<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8'/><meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>{title}</title>
  <style>
    body{{font-family:system-ui,Segoe UI,Arial;background:#f6f8fb;color:#0f172a;margin:0}} .wrap{{max-width:1400px;margin:0 auto;padding:20px}} .card{{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;margin-bottom:16px;box-shadow:0 10px 24px rgba(15,23,42,.05)}}
    .grid{{display:grid;gap:16px}} .g2{{grid-template-columns:1fr 1fr}} .g3{{grid-template-columns:1.1fr .9fr}} .g4{{grid-template-columns:repeat(4,1fr)}} .row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}} .btn{{padding:10px 14px;border:0;border-radius:12px;background:#e2e8f0;cursor:pointer}} .pri{{background:#2563eb;color:#fff}} .ok{{background:#10b981;color:#fff}} .danger{{background:#ef4444;color:#fff}} .input,textarea,select{{width:100%;padding:10px 12px;border:1px solid #dbe2ea;border-radius:12px;background:#fff}} textarea{{min-height:120px}} .hidden{{display:none}} .badge{{display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:12px}} .seg,.op{{border:1px solid #eef2f7;border-radius:14px;padding:12px;margin:10px 0}} .muted{{color:#64748b}} pre{{white-space:pre-wrap;word-break:break-word;background:#0b1220;color:#dbeafe;padding:12px;border-radius:12px;overflow:auto}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid #eef2f7;text-align:left}}
  </style>
</head>
<body>
<div class='wrap'>
  <div class='card'><div class='row' style='justify-content:space-between'><div><h1 style='margin:0 0 6px'>智档</h1><div class='muted'>审核页 / 简道云配置 / LLM 配置 / 埋点分析</div></div><div class='badge'>V0.1 Demo</div></div></div>
  <div class='grid g2'>
    <div class='card'>
      <div class='row'><button class='btn' onclick="showTab('review')">审核页</button><button class='btn' onclick="showTab('config')">简道云配置</button><button class='btn' onclick="showTab('llm')">LLM 配置</button><button class='btn' onclick="showTab('analytics')">埋点分析</button></div>
    </div>
    <div class='card row'><button class='btn pri' onclick="document.getElementById('upload-file').click()">上传转写</button><button class='btn' onclick='loadData()'>刷新</button><button class='btn' onclick='loadConfig()'>刷新配置</button><button class='btn' onclick='loadLlm()'>刷新LLM</button></div>
  </div>

  <div id='review' class='grid g3'>
    <div class='card'><h3>转写原文</h3><div class='muted' id='trans-meta'>请先选择转写</div><div id='trans-preview'></div></div>
    <div class='card'><h3>审核操作</h3><div id='ops'></div><div class='row'><button class='btn' onclick='saveDraft()'>保存草稿</button><button class='btn ok' id='submit-btn' onclick='submitAll()' disabled>全部确认并写入</button></div></div>
  </div>

  <div id='config' class='card hidden'>
    <h3>简道云配置</h3>
    <div class='grid g2'><div><label>API Key</label><input id='jdy-key' class='input' type='password'></div><div><label>Base URL</label><input id='jdy-url' class='input'></div><div><label>app_id</label><input id='jdy-app' class='input'></div><div><label>entry_id</label><input id='jdy-entry' class='input'></div></div>
    <div style='margin-top:10px'><label>字段映射 JSON</label><textarea id='jdy-map' class='input'></textarea></div>
    <div class='row' style='margin-top:10px'><button class='btn' onclick='testJdy()'>测试连接</button><button class='btn pri' onclick='saveConfig()'>保存配置</button><span id='config-msg' class='muted'></span></div>
  </div>

  <div id='llm' class='card hidden'>
    <h3>LLM 配置</h3>
    <div class='grid g2'><div><label>Provider</label><select id='llm-provider' class='input'><option value='dashscope'>dashscope</option><option value='openai_compatible'>openai_compatible</option></select></div><div><label>API Key</label><input id='llm-key' class='input' type='password'></div><div><label>Base URL</label><input id='llm-url' class='input'></div><div><label>Temperature</label><input id='llm-temp' class='input' type='number' step='0.1'></div><div><label>Max Tokens</label><input id='llm-max' class='input' type='number'></div><div><label>Agent-A 模型</label><input id='llm-a' class='input'></div><div><label>Agent-B 模型</label><input id='llm-b' class='input'></div><div><label>对话模型</label><input id='llm-chat' class='input'></div></div>
    <div style='margin-top:10px'><label>Agent-A Prompt</label><textarea id='prompt-a' class='input'></textarea></div>
    <div style='margin-top:10px'><label>Agent-B Prompt</label><textarea id='prompt-b' class='input'></textarea></div>
    <div style='margin-top:10px'><label>NL 查询 Prompt</label><textarea id='prompt-q' class='input'></textarea></div>
    <div style='margin-top:10px'><label>NL 修改 Prompt</label><textarea id='prompt-m' class='input'></textarea></div>
    <div class='row' style='margin-top:10px'><button class='btn' onclick='restorePrompts()'>恢复默认</button><button class='btn' onclick='testLlm()'>测试</button><button class='btn pri' onclick='saveLlm()'>保存配置</button><span id='llm-msg' class='muted'></span></div>
    <div class='row'><span class='badge' id='pv-a'>-</span><span class='badge' id='pv-b'>-</span></div>
  </div>

  <div id='analytics' class='card hidden'>
    <div class='grid g4'><div class='card'><div class='muted'>拜访次数</div><h2 id='kpi-v'>0</h2></div><div class='card'><div class='muted'>总采纳率</div><h2 id='kpi-a'>0%</h2></div><div class='card'><div class='muted'>质量得分</div><h2 id='kpi-q'>0%</h2></div><div class='card'><div class='muted'>Prompt 版本</div><h2 id='kpi-p'>-</h2></div></div>
    <div class='grid g2' style='margin-top:16px'><pre id='acc-json'></pre><pre id='biz-json'></pre></div>
  </div>

  <div class='card'>
    <h3>转写列表</h3>
    <input id='upload-file' type='file' accept='.txt,.md,.docx' class='hidden' onchange='uploadTranscript()'>
    <div class='row'><input id='company-hint' class='input' placeholder='公司名提示' style='max-width:280px'><button class='btn' onclick='fetchDingtalk()'>从钉钉拉取</button></div>
    <table><thead><tr><th>#</th><th>标题</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody id='tlist'><tr><td colspan='5' class='muted'>暂无</td></tr></tbody></table>
  </div>
</div>
<script>
const state = {{ transcript: null, operations: [], confirmed: new Set(), deleted: new Set(), edited: new Set() }};
const DEFAULT_A = {json.dumps(DEFAULT_PROMPT_A)};
const DEFAULT_B = {json.dumps(DEFAULT_PROMPT_B)};
function showTab(id){{['review','config','llm','analytics'].forEach(x=>document.getElementById(x).classList.toggle('hidden', x!==id));}}
async function api(url, method='GET', body=null){{const opt={{method,headers:{{}}}}; if(body instanceof FormData) opt.body=body; else if(body){{opt.headers['Content-Type']='application/json'; opt.body=JSON.stringify(body);}} const r=await fetch(url,opt); if(!r.ok) throw new Error(await r.text()); return r.json();}}
async function loadData(){{ const d=await api('/api/v1/transcripts'); const tb=document.getElementById('tlist'); tb.innerHTML=d.items.map((t,i)=>`<tr><td>${{i+1}}</td><td>${{t.title}}</td><td>${{t.source}}</td><td>${{t.status}}</td><td><a href='/transcripts/${{t.id}}/review'>审核</a></td></tr>`).join('')||'<tr><td colspan="5" class="muted">暂无</td></tr>'; if(d.items[0]) await loadTranscript(d.items[0].id); }}
async function loadTranscript(id){{ const t=await api(`/api/v1/transcripts/${{id}}`); state.transcript=t; document.getElementById('trans-meta').innerHTML=`<b>${{t.title}}</b><div class='muted'>${{t.source}} · ${{t.status}}</div>`; const segs=(t.segments&&t.segments.length)?t.segments:[{{speaker:'整段原文',timestamp:'-',text:t.raw_text||''}}]; document.getElementById('trans-preview').innerHTML=segs.map(s=>`<div class='seg'><div class='muted'>${{s.speaker}} · ${{s.timestamp}}</div><div style='margin-top:6px;line-height:1.65'>${{s.text||''}}</div></div>`).join(''); await runAgents(t); }}
async function runAgents(t){{ const ex=await api('/api/v1/agent/extraction/task','POST',{{task_id:crypto.randomUUID(),transcript:t,context:{{company_name_hint:t.company_name_hint||''}}}}); const cmp=await api('/api/v1/agent/comparison/task','POST',{{task_id:crypto.randomUUID(),extraction_result:ex.result,existing_record:{{company_name:t.company_name||t.company_name_hint||''}}}}); state.operations=cmp.result.operations.map(o=>({{...o,status:'pending'}})); renderOps(); document.getElementById('submit-btn').disabled=state.operations.length===0; }}
function renderOps(){{ const root=document.getElementById('ops'); const pending=state.operations.filter(o=>!state.confirmed.has(o.op_id)&&!state.deleted.has(o.op_id)).length; document.getElementById('submit-btn').disabled=pending!==0||state.operations.length===0; root.innerHTML=state.operations.map((op,idx)=>`<div class='op'><div class='row' style='justify-content:space-between'><b>${{op.type.includes('update')?'🔵 更新':'🟢 新增'}} · ${{op.type}}</b><span class='badge'>置信度 ${{Math.round(op.confidence*100)}}%</span></div><div style='margin:8px 0'><input class='input' value='${{op.data.summary||op.data.title||''}}' onchange="opEdit('${{op.op_id}}', this.value)"></div><div class='muted' style='font-size:12px'>原文引用：${{op.source_quote||'-'}}</div><div class='row' style='margin-top:10px'><button class='btn ok' onclick="confirmOp('${{op.op_id}}')">确认</button><button class='btn' onclick="deleteOp('${{op.op_id}}')">删除</button><button class='btn' onclick="convertOp('${{op.op_id}}')">转为新增/更新</button></div></div>`).join(''); }}
function getOp(id){{return state.operations.find(o=>o.op_id===id)}}
async function confirmOp(id){{state.confirmed.add(id);state.deleted.delete(id);renderOps();await api('/api/v1/operations/review-action','POST',{{operation_id:id,operation_type:getOp(id).type,action:'confirm',agent_confidence:getOp(id).confidence,time_spent_seconds:30,card_position:1,total_cards:state.operations.length}});}}
async function deleteOp(id){{state.deleted.add(id);state.confirmed.delete(id);renderOps();await api('/api/v1/operations/review-action','POST',{{operation_id:id,operation_type:getOp(id).type,action:'delete',agent_confidence:getOp(id).confidence,time_spent_seconds:20,card_position:1,total_cards:state.operations.length}});}}
async function convertOp(id){{const op=getOp(id);op.type=op.type.includes('update')?op.type.replace('update','new'):op.type.replace('new','update');renderOps();await api('/api/v1/operations/review-action','POST',{{operation_id:id,operation_type:op.type,action:op.type.includes('new')?'convert_to_new':'convert_to_update',agent_confidence:op.confidence,time_spent_seconds:35,card_position:1,total_cards:state.operations.length}});}}
async function opEdit(id,val){{const op=getOp(id); if(op.data.summary!==undefined) op.data.summary=val; if(op.data.title!==undefined) op.data.title=val; state.edited.add(id); await api('/api/v1/operations/review-action','POST',{{operation_id:id,operation_type:op.type,action:'edit_then_confirm',agent_confidence:op.confidence,edit_details:{{edited_fields:['summary']}},time_spent_seconds:60,card_position:1,total_cards:state.operations.length}});}}
async function saveDraft(){{await api('/api/v1/operations/review-session','POST',{{transcript_id:state.transcript?.id,total_operations:state.operations.length,confirmed:state.confirmed.size,edited_then_confirmed:state.edited.size,deleted:state.deleted.size,final_action:'save_draft',total_review_time_seconds:120,avg_time_per_card_seconds:30}});alert('草稿已保存');}}
async function submitAll(){{await api('/api/v1/operations/execute','POST',{{transcript_id:state.transcript?.id,company_id:'demo',operations:state.operations.filter(o=>!state.deleted.has(o.op_id)).map(o=>({{op_id:o.op_id,type:o.type,data:o.data}})),operator_name:'demo',operator_id:'demo'}});await api('/api/v1/operations/review-session','POST',{{transcript_id:state.transcript?.id,total_operations:state.operations.length,confirmed:state.confirmed.size,edited_then_confirmed:state.edited.size,deleted:state.deleted.size,final_action:'submit',total_review_time_seconds:180,avg_time_per_card_seconds:36}});alert('已写入成功');}}
async function uploadTranscript(){{const f=document.getElementById('upload-file').files[0]; if(!f) return; const fd=new FormData(); fd.append('file',f); fd.append('company_name_hint',document.getElementById('company-hint').value||''); const r=await api('/api/v1/transcript/upload','POST',fd); alert(`上传成功：${{r.title}}`); await loadData();}}
async function fetchDingtalk(){{const id=prompt('conference_id'); if(!id) return; await api('/api/v1/transcript/dingtalk-fetch','POST',{{conference_id:id}}); await loadData();}}
async function loadConfig(){{const c=await api('/api/v1/admin/config'); document.getElementById('jdy-url').value=c.jiandaoyun_base_url||''; document.getElementById('jdy-app').value=c.jiandaoyun_app_id||''; document.getElementById('jdy-entry').value=c.main_entry_id||''; document.getElementById('jdy-map').value=JSON.stringify(c.field_mappings||{{}},null,2);}}
async function saveConfig(){{const payload={{jiandaoyun_base_url:document.getElementById('jdy-url').value,jiandaoyun_app_id:document.getElementById('jdy-app').value,main_entry_id:document.getElementById('jdy-entry').value,field_mappings:JSON.parse(document.getElementById('jdy-map').value||'{{}}')}}; const r=await api('/api/v1/admin/config','PUT',payload); document.getElementById('config-msg').textContent='已保存：'+r.changed_fields.join(', ');}}
async function testJdy(){{const r=await api('/api/v1/admin/config/test','POST',{{}}); document.getElementById('config-msg').textContent=r.message;}}
async function loadLlm(){{const c=await api('/api/v1/admin/llm-config'); document.getElementById('llm-provider').value=c.provider||'dashscope'; document.getElementById('llm-url').value=c.base_url||''; document.getElementById('llm-a').value=c.agent_a_model||''; document.getElementById('llm-b').value=c.agent_b_model||''; document.getElementById('llm-chat').value=c.nl_chat_model||''; document.getElementById('llm-temp').value=c.temperature??0.3; document.getElementById('llm-max').value=c.max_tokens??4096; document.getElementById('prompt-a').value=c.agent_a_prompt||''; document.getElementById('prompt-b').value=c.agent_b_prompt||''; document.getElementById('prompt-q').value=c.nl_query_prompt||''; document.getElementById('prompt-m').value=c.nl_modify_prompt||''; document.getElementById('pv-a').textContent='Agent-A v'+(c.agent_a_prompt_version||'-'); document.getElementById('pv-b').textContent='Agent-B v'+(c.agent_b_prompt_version||'-'); }}
function restorePrompts(){{document.getElementById('prompt-a').value=DEFAULT_A;document.getElementById('prompt-b').value=DEFAULT_B;}}
async function saveLlm(){{const payload={{provider:document.getElementById('llm-provider').value,api_key:document.getElementById('llm-key').value,base_url:document.getElementById('llm-url').value,agent_a_model:document.getElementById('llm-a').value,agent_b_model:document.getElementById('llm-b').value,nl_chat_model:document.getElementById('llm-chat').value,temperature:Number(document.getElementById('llm-temp').value),max_tokens:Number(document.getElementById('llm-max').value),agent_a_prompt:document.getElementById('prompt-a').value,agent_b_prompt:document.getElementById('prompt-b').value,nl_query_prompt:document.getElementById('prompt-q').value,nl_modify_prompt:document.getElementById('prompt-m').value}}; const r=await api('/api/v1/admin/llm-config','PUT',payload); document.getElementById('llm-msg').textContent='已保存：'+r.changed_fields.join(', '); await loadLlm();}}
async function testLlm(){{const r=await api('/api/v1/admin/llm-config/test','POST',{{target:'agent_a',test_input:document.getElementById('prompt-a').value.slice(0,80)}}); document.getElementById('llm-msg').textContent=r.preview;}}
async function loadAnalytics(){{const a=await api('/api/v1/analytics/system/accuracy'); const b=await api('/api/v1/analytics/business/overview'); document.getElementById('acc-json').textContent=JSON.stringify(a,null,2); document.getElementById('biz-json').textContent=JSON.stringify(b,null,2); document.getElementById('kpi-v').textContent=b.visit_count; document.getElementById('kpi-a').textContent=Math.round((b.overall_adoption_rate||0)*100)+'%'; document.getElementById('kpi-q').textContent=Math.round((b.quality_score||0)*100)+'%'; document.getElementById('kpi-p').textContent=a.prompt_version_current.agent_a+' / '+a.prompt_version_current.agent_b; }}
window.addEventListener('load', async()=>{{showTab('review'); await Promise.all([loadData(), loadConfig(), loadLlm(), loadAnalytics()]);}});
</script>
</body></html>""")


@app.get("/")
def root(): return shell("智档")
@app.get("/init")
def init_page(): return shell("智档 · 初始化")
@app.get("/login")
def login_page(): return shell("智档 · 登录")
@app.get("/transcripts")
def transcript_page(): return shell("智档 · 转写管理")
@app.get("/transcripts/{transcript_id}/review")
def transcript_review_page(transcript_id: str): return shell("智档 · 审核页", transcript_id)
@app.get("/chat")
def chat_page(): return shell("智档 · 对话")
@app.get("/admin/config")
def admin_config_page(): return shell("智档 · 简道云配置")
@app.get("/admin/llm")
def admin_llm_page(): return shell("智档 · LLM配置")

@app.post("/api/v1/system/init")
def system_init(payload: SuperadminInit):
    if STATE["superadmin"]: raise HTTPException(status_code=403, detail="系统已初始化")
    STATE["superadmin"] = {"username": payload.username, "password_hash": hashlib.sha256(payload.password.encode()).hexdigest(), "display_name": payload.display_name or payload.username}
    return {"success": True}

@app.post("/api/v1/auth/login")
def auth_login(payload: LoginPayload):
    admin = STATE["superadmin"]
    if not admin: raise HTTPException(status_code=404, detail="请先初始化系统")
    if admin["username"] != payload.username or admin["password_hash"] != hashlib.sha256(payload.password.encode()).hexdigest(): raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = jwt.encode({"source": "superadmin", "username": admin["username"], "exp": datetime.now(timezone.utc) + timedelta(hours=24)}, JWT_SECRET, algorithm="HS256")
    return {"success": True, "token": token, "display_name": admin["display_name"]}

@app.post("/api/v1/sso/generate")
def sso_generate(payload: SsoGeneratePayload):
    secret = STATE["system_config"]["sso_shared_secret"]
    raw = f"{payload.user_name}|{payload.user_id}|{payload.company_id}|{int(datetime.now().timestamp())}"
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return {"token": f"{raw}|{sig}"}

@app.get("/api/v1/sso/entry")
def sso_entry(token: str, company_id: str):
    try: user_name, user_id, token_company_id, ts, sig = token.split("|")
    except ValueError as exc: raise HTTPException(status_code=400, detail="token 格式错误") from exc
    if token_company_id != company_id: raise HTTPException(status_code=403, detail="company_id 不匹配")
    raw = f"{user_name}|{user_id}|{token_company_id}|{ts}"
    expected_sig = hmac.new(STATE["system_config"]["sso_shared_secret"].encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig): raise HTTPException(status_code=403, detail="链接已失效")
    if datetime.now().timestamp() - int(ts) > STATE["system_config"]["sso_token_ttl_minutes"] * 60: raise HTTPException(status_code=403, detail="链接已失效")
    jwt_token = jwt.encode({"user_name": user_name, "user_id": user_id, "source": "sso", "exp": datetime.now(timezone.utc) + timedelta(hours=24)}, JWT_SECRET, algorithm="HS256")
    return RedirectResponse(url=f"/transcripts?token={jwt_token}&company_id={company_id}")

@app.post("/api/v1/transcript/upload")
async def transcript_upload(file: UploadFile = File(...), company_name_hint: str = Form(default="")):
    content = (await file.read()).decode("utf-8", errors="ignore")
    parsed = parse_transcript(content)
    tid = str(uuid4())
    STATE["transcripts"].insert(0, {"id": tid, "source": "upload", "source_id": file.filename, "title": parsed["title"], "raw_text": parsed["raw_text"], "segments": parsed["segments"], "status": "parsed", "company_name_hint": company_name_hint, "created_at": now_iso()})
    track_event("transcript.uploaded", {"user_name": "demo", "user_id": "demo", "source": "superadmin"}, {"transcript_id": tid, "company_id_hash": hash_company_id(company_name_hint or tid), "session_id": str(uuid4())}, {"source": "upload", "file_name": file.filename, "file_size_bytes": len(content), "segment_count": len(parsed["segments"]), "char_count": len(content)})
    return TranscriptUploadResponse(transcript_id=tid, title=parsed["title"], segment_count=len(parsed["segments"]), status="parsed", preview=parsed["raw_text"][:500])

@app.post("/api/v1/transcript/dingtalk-fetch")
def dingtalk_fetch(conference_id: str):
    tid = str(uuid4()); title = f"钉钉会议 {conference_id}"
    STATE["transcripts"].insert(0, {"id": tid, "source": "dingtalk_api", "source_id": conference_id, "title": title, "raw_text": "", "segments": [], "status": "parsed", "created_at": now_iso()})
    return {"transcript_id": tid, "title": title, "segment_count": 0, "status": "parsed", "preview": ""}

@app.get("/api/v1/transcripts")
def list_transcripts(): return {"items": STATE["transcripts"]}
@app.get("/api/v1/transcripts/{transcript_id}")
def get_transcript(transcript_id: str):
    for t in STATE["transcripts"]:
        if t["id"] == transcript_id: return t
    raise HTTPException(status_code=404, detail="转写不存在")

@app.post("/api/v1/agent/extraction/task")
def extraction_task(payload: dict[str, Any]): return {"task_id": payload.get("task_id", str(uuid4())), "status": "completed", "result": agent_a_mock(payload.get("transcript", {})), "message": None, "error": None}
@app.post("/api/v1/agent/comparison/task")
def comparison_task(payload: dict[str, Any]): return {"task_id": payload.get("task_id", str(uuid4())), "status": "completed", "result": agent_b_mock(payload.get("extraction_result", {})), "error": None}

@app.post("/api/v1/operations/execute")
def execute_operations(payload: dict[str, Any]):
    results = [{"op_id": op.get("op_id", str(uuid4())), "status": "success", "jiandaoyun_data_id": str(uuid4())} for op in payload.get("operations", [])]
    log_operation("operations.execute", payload)
    track_event("write.completed", {"user_name": payload.get("operator_name", "demo"), "user_id": payload.get("operator_id", "demo"), "source": "sso"}, {"transcript_id": payload.get("transcript_id"), "company_id_hash": hash_company_id(payload.get("company_id", "")), "session_id": payload.get("session_id", str(uuid4()))}, {"operations_submitted": len(payload.get("operations", [])), "operations_succeeded": len(results), "operations_failed": 0, "total_latency_ms": 1000})
    return {"success": True, "results": results, "failed": []}

@app.post("/api/v1/chat")
def chat(payload: ChatPayload):
    msg = payload.message.strip(); action = "query_expectation" if ("预期" in msg or "查询" in msg) else "modify_status"
    track_event("chat.query" if action == "query_expectation" else "chat.modify", {"user_name": payload.sso_user.get("user_name", "demo") if payload.sso_user else "demo", "user_id": payload.sso_user.get("user_id", "demo") if payload.sso_user else "demo", "source": "sso"}, {"transcript_id": None, "company_id_hash": hash_company_id("demo"), "session_id": payload.session_id}, {"intent": action, "query_text_length": len(msg), "result_count": 1, "latency_ms": 1200})
    return {"reply": f"已收到：{msg}", "intent": action, "needs_confirmation": action == "modify_status"}

@app.get("/api/v1/admin/config")
def get_admin_config(): return STATE["system_config"]
@app.put("/api/v1/admin/config")
def save_admin_config(payload: dict[str, Any]):
    before = dict(STATE["system_config"])
    STATE["system_config"].update(payload)
    changed = [k for k in payload if before.get(k) != payload.get(k)]
    track_event("config.changed", {"user_name": "admin", "user_id": "admin", "source": "superadmin"}, {"transcript_id": None, "company_id_hash": None, "session_id": str(uuid4())}, {"config_section": "jiandaoyun", "changed_fields": changed, "changed_by": "admin"})
    return {"success": True, "changed_fields": changed}
@app.post("/api/v1/admin/config/test")
def test_admin_config(): return {"success": True, "message": "连接正常（demo）"}

@app.get("/api/v1/admin/llm-config")
def get_llm_config():
    c = STATE["system_config"]
    return {"provider": c["llm_provider"], "api_key": "sk-****xxxx" if c["llm_api_key_encrypted"] else "", "base_url": c["llm_base_url"], "agent_a_model": c["agent_a_model"], "agent_b_model": c["agent_b_model"], "nl_chat_model": c["nl_chat_model"], "temperature": c["temperature"], "max_tokens": c["max_tokens"], "agent_a_prompt": c["agent_a_prompt"], "agent_b_prompt": c["agent_b_prompt"], "nl_query_prompt": c["nl_query_prompt"], "nl_modify_prompt": c["nl_modify_prompt"], "agent_a_prompt_version": prompt_version(c["agent_a_prompt"]), "agent_b_prompt_version": prompt_version(c["agent_b_prompt"])}
@app.put("/api/v1/admin/llm-config")
def save_llm_config(payload: dict[str, Any]):
    before = dict(STATE["system_config"])
    for k, v in payload.items():
        if k == "api_key" and v: STATE["system_config"]["llm_api_key_encrypted"] = f"enc:{v}"
        elif k != "api_key": STATE["system_config"][k] = v
    changed = [k for k in payload if k != "api_key" and before.get(k) != payload.get(k)] + (["api_key"] if payload.get("api_key") else [])
    track_event("config.changed", {"user_name": "admin", "user_id": "admin", "source": "superadmin"}, {"transcript_id": None, "company_id_hash": None, "session_id": str(uuid4())}, {"config_section": "llm", "changed_fields": changed, "changed_by": "admin"})
    return {"success": True, "changed_fields": changed, "agent_a_prompt_version": prompt_version(STATE["system_config"]["agent_a_prompt"]), "agent_b_prompt_version": prompt_version(STATE["system_config"]["agent_b_prompt"])}
@app.post("/api/v1/admin/llm-config/test")
def test_llm_config(payload: dict[str, Any]): return {"success": True, "target": payload.get("target"), "preview": f"mock response for {payload.get('target')}"}

@app.post("/api/v1/operations/review-action")
def review_action(payload: ReviewActionPayload): track_event("review.action", {"user_name": "demo", "user_id": "demo", "source": "sso"}, {"transcript_id": None, "company_id_hash": hash_company_id("demo"), "session_id": str(uuid4())}, payload.model_dump()); return {"success": True}
@app.post("/api/v1/operations/review-session")
def review_session(payload: ReviewSessionPayload): track_event("review.session", {"user_name": "demo", "user_id": "demo", "source": "sso"}, {"transcript_id": payload.transcript_id, "company_id_hash": hash_company_id(payload.transcript_id or "demo"), "session_id": str(uuid4())}, payload.model_dump()); return {"success": True}

@app.get("/api/v1/analytics/business/overview")
def analytics_business_overview(period: str = "7d"):
    visits = [e for e in STATE["analytics_events"] if e["event_type"] == "transcript.uploaded"]
    return {"period": period, "visit_count": len(visits), "active_operators": 1, "avg_visits_per_operator": float(len(visits)), "avg_meeting_duration_min": 35, "avg_expectations_per_visit": 1.0, "avg_scenarios_per_visit": 1.0, "empty_visit_rate": 0.0, "overall_adoption_rate": 0.75, "quality_score": 0.72, "top_operators": [{"name": "demo", "visits": len(visits), "adoption_rate": 0.75, "quality_score": 0.72}]}
@app.get("/api/v1/analytics/system/accuracy")
def analytics_system_accuracy(period: str = "7d"):
    return {"period": period, "agent_a": {"total_operations_generated": 2, "direct_confirm_rate": 0.52, "edit_then_confirm_rate": 0.22, "total_adoption_rate": 0.74, "delete_rate": 0.18, "minor_reword_rate": 0.65, "major_rewrite_rate": 0.25, "avg_confidence": 0.83, "by_type": {"expectation": {"adoption_rate": 0.78, "delete_rate": 0.15}, "scenario": {"adoption_rate": 0.70, "delete_rate": 0.22}}}, "agent_b": {"match_accuracy": 0.85, "false_update_rate": 0.10, "missed_match_rate": 0.05}, "prompt_version_current": {"agent_a": prompt_version(STATE["system_config"]["agent_a_prompt"]), "agent_b": prompt_version(STATE["system_config"]["agent_b_prompt"])}}
@app.get("/api/v1/analytics/system/prompt-compare")
def analytics_prompt_compare(agent: str = "agent_a", period: str = "30d"):
    return {"agent": agent, "period": period, "versions": [{"prompt_version": "a1b2c3d4", "active_period": "04-01 ~ 04-15", "sample_count": 45, "adoption_rate": 0.68, "delete_rate": 0.22, "avg_latency_ms": 9500, "avg_tokens": 2800}, {"prompt_version": "f9e8d7c6", "active_period": "04-16 ~ 04-23", "sample_count": 32, "adoption_rate": 0.74, "delete_rate": 0.18, "avg_latency_ms": 8800, "avg_tokens": 2650}], "improvement": {"adoption_rate_delta": "+0.06", "delete_rate_delta": "-0.04", "latency_delta_ms": "-700", "conclusion": "新版 Prompt 在采纳率和延迟上均有提升"}}
@app.get("/api/v1/analytics/export")
def analytics_export(): return JSONResponse(STATE["analytics_events"])
@app.get("/health")
def health(): return {"ok": True}
