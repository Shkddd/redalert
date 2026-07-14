"""FastAPI 入口 + 流式 + 简单聊天 UI"""
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.agent.loop import run, to_dict, AgentRun
from app.core.metrics import metrics
from app.core.observability import obs
from app.skills.registry import get_skill_names

# 启动时 observability 初始化 (用 global flag 防 reload / 多进程时重复)
import os as _os_setup
if not _os_setup.environ.get("_OBS_SETUP_DONE"):
    _os_setup.environ["_OBS_SETUP_DONE"] = "1"
    print("[MAIN] local-agent starting...")
    obs.setup(tags=["local-agent", "v5"])
    # 动态 patch chat() 函数 (因为 @obs.trace 装饰器在 import 时已执行)
    obs.patch_chat_function()



app = FastAPI(title="Local Agent", version="0.2.0")


# 简易内存会话存储(实际可换 Redis)
_sessions: dict = {}


class AskReq(BaseModel):
    question: str
    session_id: Optional[str] = None
    framework: Optional[str] = "v1"   # v1=手写ReAct / v2=LangGraph / v3=autogen


class AskResp(BaseModel):
    session_id: str
    framework: str
    final_answer: str
    iterations: int
    duration_s: float
    steps: List[dict]


def _run_with_framework(req: AskReq) -> Dict:
    """根据 framework 字段选不同的 loop"""
    fw = (req.framework or "v1").lower()
    history = _sessions.get(req.session_id or "default", [])

    if fw in ("v1", "react", ""):
        result = run(req.question, history=history)
        d = to_dict(result)
        d["framework"] = "v1-react"
    elif fw in ("v2", "langgraph", "lg"):
        from app.agent.loop_langgraph import run as run_lg
        d = run_lg(req.question, history=history)
    elif fw in ("v3", "autogen", "ag"):
        from app.agent.loop_autogen import run as run_ag
        d = run_ag(req.question, history=history)
    elif fw in ("v4", "langchain", "lc"):
        from app.agent.loop_langchain import run as run_lc
        d = run_lc(req.question, history=history)
    elif fw in ("v5", "plan", "plan-execute-verify"):
        from app.agent.loop_plan import run as run_plan, to_dict as to_dict_plan
        result = run_plan(req.question, history=history)
        d = to_dict_plan(result)
        d["framework"] = "v5-plan-execute-verify"
    else:
        raise HTTPException(400, f"unknown framework: {fw}. use v1/v2/v3/v4/v5")

    return d


@app.post("/api/ask", response_model=AskResp)
def api_ask(req: AskReq):
    """同步:跑完一次 agent 循环,返回完整 trace"""
    sid = req.session_id or "default"
    d = _run_with_framework(req)
    # 更新会话历史(只保留 user/assistant 简短摘要)
    history = _sessions.get(sid, [])
    history.append({"role": "user", "content": req.question})
    history.append({"role": "assistant", "content": d.get("final_answer", "")[:500]})
    _sessions[sid] = history[-20:]  # 最多 20 轮
    return AskResp(
        session_id=sid,
        framework=d.get("framework", "v1-react"),
        final_answer=d.get("final_answer", ""),
        iterations=d.get("iterations", 0),
        duration_s=d.get("duration_s", 0.0),
        steps=d.get("steps", []),
    )


@app.post("/api/ask/stream")
def api_ask_stream(req: AskReq):
    """流式:逐步 yield 事件,前端能看到 trace 实时展开

    v1/v2/v4 走统一 generator (有 thought/action/observation/final 事件)
    v3 autogen 走它自己的事件流,前端按 messages 类型渲染
    """
    sid = req.session_id or "default"
    history = _sessions.get(sid, [])

    def gen():
        from app.agent.loop import AgentStep, run as run_v1, to_dict
        from app.skills.registry import execute_skill, get_tool_schemas
        from app.llm.client import chat
        from app.core.config import MAX_ITERATIONS
        from app.agent.loop import _extract_pseudo_tool_calls

        fw = (req.framework or "v1").lower()

        # ============== v3 autogen 走它自己的事件流 ==============
        if fw in ("v3", "autogen", "ag"):
            yield f"event: framework\ndata: {json.dumps({'framework': 'v3-autogen'})}\n\n"
            try:
                from app.agent.loop_autogen import run as run_ag
                d = run_ag(req.question, history=history)
                # autogen 的 raw_messages 是 list[dict],把它当流式事件逐条 yield
                for i, msg in enumerate(d.get("raw_messages", [])):
                    yield f"event: message\ndata: {json.dumps({'i': i, 'msg': msg}, ensure_ascii=False, default=str)}\n\n"
                # 把所有 messages 收尾塞进 history
                yield f"event: final\ndata: {json.dumps({'answer': d.get('final_answer', ''), 'iterations': d.get('iterations', 0), 'duration_s': d.get('duration_s', 0)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"event: error\ndata: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"
            history.append({"role": "user", "content": req.question})
            history.append({"role": "assistant", "content": d.get("final_answer", "")[:500]})
            _sessions[sid] = history[-20:]
            yield "event: done\ndata: {}\n\n"
            return

        # ============== v4 LangChain AgentExecutor 走它自己的 invoke ==============
        if fw in ("v4", "langchain", "lc"):
            yield f"event: framework\ndata: {json.dumps({'framework': 'v4-langchain'})}\n\n"
            try:
                from app.agent.loop_langchain import run as run_lc
                d = run_lc(req.question, history=history)
                # LangChain 也有中间步骤
                for s in d.get("steps", []):
                    yield f"event: step\ndata: {json.dumps({'thought': s.get('thought', ''), 'action': s.get('action', ''), 'action_input': s.get('action_input', {}), 'observation_preview': s.get('observation_preview', '')}, ensure_ascii=False)}\n\n"
                yield f"event: final\ndata: {json.dumps({'answer': d.get('final_answer', ''), 'iterations': d.get('iterations', 0), 'duration_s': d.get('duration_s', 0)}, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"event: error\ndata: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"
            history.append({"role": "user", "content": req.question})
            history.append({"role": "assistant", "content": d.get("final_answer", "")[:500]})
            _sessions[sid] = history[-20:]
            yield "event: done\ndata: {}\n\n"
            return

        # ============== v5 Plan-Execute-Verify 走它自己的事件流 ==============
        if fw in ("v5", "plan", "plan-execute-verify"):
            yield f"event: framework\ndata: {json.dumps({'framework': 'v5-plan-execute-verify'})}\n\n"
            try:
                from app.agent.loop_plan import (
                    run as run_plan, to_dict as to_dict_plan,
                    _plan, _execute_subtask, _verify, _synthesize,
                    AgentPlanRun,
                )
                # Phase 1: Plan
                reasoning, subtasks = _plan(req.question)
                yield f"event: plan\ndata: {json.dumps({'reasoning': reasoning, 'subtasks': [{'id': s.id, 'name': s.name, 'intent': s.intent} for s in subtasks]}, ensure_ascii=False)}\n\n"
                # Phase 2: Execute first pass
                for st in subtasks:
                    yield f"event: subtask_start\ndata: {json.dumps({'id': st.id, 'name': st.name, 'intent': st.intent}, ensure_ascii=False)}\n\n"
                    _execute_subtask(st, req.question, history)
                    yield f"event: subtask_done\ndata: {json.dumps({'id': st.id, 'completed': st.completed, 'attempt': st.attempt, 'result_preview': (st.result or st.error)[:300], 'phase': 'first'}, ensure_ascii=False)}\n\n"
                # Phase 3: Verify + retry
                plan_run = AgentPlanRun(question=req.question, subtasks=subtasks)
                plan_run.plan_reasoning = reasoning
                for retry_round in range(2):
                    verdict = _verify(req.question, subtasks)
                    plan_run.verdict = verdict
                    yield f"event: verdict\ndata: {json.dumps(verdict, ensure_ascii=False)}\n\n"
                    if verdict.get("pass") is True or not verdict.get("failed"):
                        break
                    for r in verdict["failed"]:
                        idx = next((i for i, s in enumerate(subtasks) if s.id == r.get("id")), None)
                        if idx is None:
                            continue
                        # 限制 retry_intent 长度,避免 minimax 再次因 input 过长 422
                        retry_intent = (r.get("retry_intent") or subtasks[idx].intent)[:300]
                        subtasks[idx].intent = retry_intent
                        subtasks[idx].completed = False
                        yield f"event: subtask_retry\ndata: {json.dumps({'id': subtasks[idx].id, 'new_intent': retry_intent}, ensure_ascii=False)}\n\n"
                        _execute_subtask(subtasks[idx], req.question, history)
                        yield f"event: subtask_done\ndata: {json.dumps({'id': subtasks[idx].id, 'completed': subtasks[idx].completed, 'attempt': subtasks[idx].attempt, 'result_preview': (subtasks[idx].result or subtasks[idx].error)[:300], 'phase': 'retry'}, ensure_ascii=False)}\n\n"
                # Phase 4: Synthesize
                plan_run.final_answer = _synthesize(req.question, subtasks)
                yield f"event: final\ndata: {json.dumps({'answer': plan_run.final_answer, 'iterations': sum(s.attempt for s in subtasks), 'duration_s': 0.0}, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield f"event: error\ndata: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"
            history.append({"role": "user", "content": req.question})
            _sessions[sid] = history[-20:]
            yield "event: done\ndata: {}\n\n"
            return

        # ============== v1/v2 手写 ReAct (有 step-by-step trace) ==============
        framework_name = "v2-langgraph" if fw in ("v2", "langgraph", "lg") else "v1-react"
        yield f"event: framework\ndata: {json.dumps({'framework': framework_name})}\n\n"

        run_obj = AgentRun(question=req.question)
        messages = [
            {"role": "system", "content": "你是一个 Agentic 助手,通过循环调用工具解决问题。直接用自然语言回答。"},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": req.question})
        tool_schemas = get_tool_schemas()

        try:
            for it in range(1, MAX_ITERATIONS + 1):
                yield f"event: iteration_start\ndata: {json.dumps({'iteration': it})}\n\n"

                resp = chat(messages, tools=tool_schemas)
                assistant_msg = {"role": "assistant", "content": resp.get("content", "") or ""}
                if resp.get("tool_calls"):
                    assistant_msg["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        for tc in resp["tool_calls"]
                    ]
                messages.append(assistant_msg)

                thought = resp.get("content", "")
                pseudo = _extract_pseudo_tool_calls(thought, tool_schemas)
                all_calls = (resp.get("tool_calls") or []) + pseudo
                if all_calls:
                    assistant_msg["tool_calls"] = [
                        {"id": tc.get("id", f"pseudo_{it}_{i}"), "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        for i, tc in enumerate(all_calls)
                    ]
                if thought:
                    yield f"event: thought\ndata: {json.dumps({'iteration': it, 'thought': thought}, ensure_ascii=False)}\n\n"

                if not all_calls:
                    run_obj.final_answer = thought
                    run_obj.steps.append(AgentStep(iteration=it, thought=thought, action="final", action_input={}))
                    break

                for tc in all_calls:
                    yield f"event: action\ndata: {json.dumps({'iteration': it, 'action': tc['name'], 'input': tc['arguments']}, ensure_ascii=False)}\n\n"
                    obs = execute_skill(tc["name"], tc["arguments"])
                    obs_text = json.dumps(obs, ensure_ascii=False)[:3000]
                    yield f"event: observation\ndata: {json.dumps({'iteration': it, 'output': obs_text[:500]}, ensure_ascii=False)}\n\n"
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"pseudo_{it}_0"), "content": obs_text})
                    run_obj.steps.append(AgentStep(iteration=it, thought=thought, action=tc["name"],
                                                   action_input=tc["arguments"], observation=obs_text[:500]))
            else:
                run_obj.final_answer = f"[已达 {MAX_ITERATIONS} 轮上限]"
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"

        yield f"event: final\ndata: {json.dumps({'answer': run_obj.final_answer, 'iterations': len(run_obj.steps)}, ensure_ascii=False)}\n\n"
        history.append({"role": "user", "content": req.question})
        history.append({"role": "assistant", "content": run_obj.final_answer[:500]})
        _sessions[sid] = history[-20:]
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/skills")
def list_skills():
    return {"skills": get_skill_names()}


@app.get("/api/sessions")
def list_sessions():
    return {"sessions": list(_sessions.keys()), "count": len(_sessions)}


INDEX_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Local Agent</title>
<style>
body{font-family:-apple-system,monospace;max-width:1000px;margin:0 auto;padding:20px;background:#0d1117;color:#c9d1d9}
h1{color:#58a6ff;margin:0 0 16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin:10px 0}
input,button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:8px 12px;border-radius:6px;font-size:14px}
button{background:#238636;color:#fff;border:0;cursor:pointer}
button:hover{background:#2ea043}
input[type=text]{width:70%}
.thought{color:#d2a8ff}
.action{color:#ffa657}
.observation{color:#7ee787;white-space:pre-wrap;font-size:12px;background:#0d1117;padding:6px;border-radius:4px;margin:4px 0}
.final{color:#58a6ff;font-weight:bold;background:#0d1117;padding:10px;border-radius:6px;margin-top:10px}
.iter{color:#8b949e;font-size:11px}
#trace{max-height:500px;overflow-y:auto}
</style></head><body>
<h1>🤖 Local Agent</h1>

<div class="card">
<select id="fw" style="margin-right:10px">
  <option value="v1">v1 手写 ReAct</option>
  <option value="v2">v2 LangGraph StateGraph</option>
  <option value="v4">v4 LangChain AgentExecutor</option>
  <option value="v3">v3 autogen GroupChat (慢)</option>
  <option value="v5">v5 Plan-Execute-Verify (新,适合复杂多步)</option>
</select>
<input id="q" type="text" placeholder="问点什么,比如:列出 ~/local-rag 目录的文件,并告诉我 README 第一段说了什么" value="">
<button onclick="ask()">Ask</button>
<span class="iter" id="status"></span>
</div>

<div class="card">
<h3>Trace <span class="iter" id="fw_label"></span></h3>
<div id="trace"></div>
<div class="final" id="final" style="display:none"></div>
</div>

<script>
async function ask() {
  const q = document.getElementById('q').value.trim();
  const fw = document.getElementById('fw').value;
  if (!q) return;
  document.getElementById('trace').innerHTML = '';
  document.getElementById('final').style.display = 'none';
  document.getElementById('status').innerText = '⏳ ...';
  document.getElementById('fw_label').innerText = `[${fw}]`;
  const resp = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: q, framework: fw})
  });
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream: true});
    const lines = buf.split('\\n');
    buf = lines.pop();
    let evt = '', data = '';
    for (const l of lines) {
      if (l.startsWith('event:')) evt = l.slice(6).trim();
      else if (l.startsWith('data:')) data += l.slice(5).trim();
      else if (l === '' && evt) {
        try { handleEvent(evt, JSON.parse(data)); } catch(e) { console.warn(e); }
        evt = ''; data = '';
      }
    }
  }
  document.getElementById('status').innerText = '✓ done';
}
function handleEvent(evt, d) {
  const t = document.getElementById('trace');
  if (evt === 'framework') {
    document.getElementById('fw_label').innerText = `[${d.framework}]`;
    t.innerHTML += `<div class="iter">━━━ framework: ${d.framework} ━━━</div>`;
  } else if (evt === 'plan') {
    // v5 Plan-Execute-Verify
    t.innerHTML += `<div class="iter">━━━ PLAN ━━━</div>`;
    t.innerHTML += `<div class="thought">📋 推理: ${escapeHtml(d.reasoning || '')}</div>`;
    t.innerHTML += `<div class="iter">拆解为 ${d.subtasks.length} 个子任务:</div>`;
    d.subtasks.forEach((s, i) => {
      t.innerHTML += `<div class="action">  ${i+1}. [${s.id}] ${escapeHtml(s.name)} — ${escapeHtml((s.intent||'').slice(0,100))}</div>`;
    });
  } else if (evt === 'subtask_start') {
    t.innerHTML += `<div class="iter">▶ 开始: [${d.id}] ${escapeHtml(d.name)}</div>`;
  } else if (evt === 'subtask_retry') {
    t.innerHTML += `<div class="iter" style="color:#fa0">↻ 重试 [${d.id}] (新 intent: ${escapeHtml((d.new_intent||'').slice(0,80))})</div>`;
  } else if (evt === 'subtask_done') {
    // first/retry 用不同图标 + 颜色,让 retry 后是否真的修好一目了然
    const isRetry = d.phase === 'retry';
    let icon, color;
    if (isRetry) {
      // retry 之后: ✅=修好, ❌=仍未修好
      icon = d.completed ? '✅' : '❌';
      color = d.completed ? '#3fb950' : '#f85149';
    } else {
      // first: 用 ○ 表示"完成但 verifier 还没判定"
      icon = d.completed ? '○' : '❌';
      color = d.completed ? '#8b949e' : '#f85149';
    }
    t.innerHTML += `<div class="observation" style="color:${color}">${icon} [${d.id}] attempt=${d.attempt}${isRetry?' (retry)':''}: ${escapeHtml(d.result_preview || '')}</div>`;
  } else if (evt === 'verdict') {
    const passed = d.completed || [];
    const failed = (d.failed||[]).map(f=>f.id).join(',');
    // pass=true 显示绿色, false 显示黄色
    const vColor = d.pass ? '#3fb950' : '#d29922';
    const vIcon = d.pass ? '✓' : '⚠';
    t.innerHTML += `<div class="iter" style="color:${vColor};font-weight:600">━━━ VERIFIER ━━━ ${vIcon} pass=${d.pass} 通过=${passed.length} 失败=[${failed}]</div>`;
  } else if (evt === 'iteration_start') {
    t.innerHTML += `<div class="iter">[iter ${d.iteration} start]</div>`;
  } else if (evt === 'thought') {
    t.innerHTML += `<div class="thought">💭 [iter ${d.iteration}] ${escapeHtml(d.thought)}</div>`;
  } else if (evt === 'action') {
    t.innerHTML += `<div class="action">🔧 [iter ${d.iteration}] ${d.action}(${JSON.stringify(d.input)})</div>`;
  } else if (evt === 'observation') {
    t.innerHTML += `<div class="observation">📥 ${escapeHtml(d.output)}</div>`;
  } else if (evt === 'step') {
    // LangChain v4
    t.innerHTML += `<div class="thought">💭 ${escapeHtml(d.thought || '')}</div>`;
    t.innerHTML += `<div class="action">🔧 ${d.action}(${JSON.stringify(d.action_input)})</div>`;
    t.innerHTML += `<div class="observation">📥 ${escapeHtml(d.observation_preview || '')}</div>`;
  } else if (evt === 'message') {
    // autogen v3 逐条消息
    const m = d.msg;
    const role = (m && (m.source || m.role)) || 'agent';
    const content = (m && (m.content || m.body || '')) || '';
    t.innerHTML += `<div class="thought">💬 [${role}] ${escapeHtml(typeof content === 'string' ? content : JSON.stringify(content).slice(0, 300))}</div>`;
  } else if (evt === 'error') {
    t.innerHTML += `<div style="color:#f55">❌ ${escapeHtml(d.error)}</div>`;
  } else if (evt === 'final') {
    // v5 SYNTHESIZE 阶段分隔, 然后把答案放到 final div
    const f = document.getElementById('final');
    // strip LLM 自带的 ✓/✅ 前缀避免重复
    let ans = (d.answer || '').replace(/^[\s]*[✓✅]\s*/g, '');
    t.innerHTML += `<div class="iter" style="color:#58a6ff;font-weight:600">━━━ SYNTHESIZE ━━━ 最终答案</div>`;
    f.innerText = ans;
    f.style.display = 'block';
  }
  t.scrollTop = t.scrollHeight;
}
function escapeHtml(s) { return String(s).replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


@app.get("/monitor", response_class=HTMLResponse)
def monitor():
    """监控仪表盘"""
    html_path = Path(__file__).parent / "monitor.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/metrics")
def api_metrics():
    """JSON 快照,前端 /monitor 页 polling"""
    return metrics.snapshot()


@app.post("/api/metrics/reset")
def api_metrics_reset():
    """清空 metrics (测试用)"""
    from app.core import metrics as _m
    _m.metrics.__init__()
    return {"ok": True}


@app.get("/api/skills/{name}")
def get_skill(name: str):
    from app.skills.registry import SKILL_REGISTRY
    if name not in SKILL_REGISTRY:
        raise HTTPException(404, f"skill not found: {name}")


if __name__ == "__main__":
    """PyCharm Run/Debug 友好入口:右键本文件 → Run/Debug 'server'
    也可以: python -m app.api.server --port 8001
    """
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("app.api.server:app", host=args.host, port=args.port, reload=args.reload, log_level="info")