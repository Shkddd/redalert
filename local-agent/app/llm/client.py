"""LLM 客户端(OpenAI 兼容,支持流式 + LangSmith trace)"""
import os
import json
import time
from typing import List, Dict, Iterator
from openai import OpenAI

from app.core.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, MAX_TOKENS, TEMPERATURE
from app.core.observability import obs


_client: OpenAI = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=60.0,
        )
    return _client


def _make_langsmith_trace(name, run_type, inputs):
    """Lazy 创建 LangSmith trace context manager.

    setup() 之前 langsmith_enabled=False, 这里返回 None (no-op).
    """
    if not obs.langsmith_enabled:
        return None
    try:
        from langsmith import trace as _lst
        ts = _lst(name=name, run_type=run_type, inputs=inputs)
        ts.__enter__()
        return ts
    except Exception:
        return None


def _end_langsmith_trace(ts, error=None):
    if ts is None:
        return
    try:
        if error is not None:
            ts.__exit__(type(error), error, error.__traceback__)
        else:
            ts.__exit__(None, None, None)
    except Exception:
        pass


def chat(messages: List[Dict], tools: List[Dict] = None,
         temperature: float = TEMPERATURE, max_tokens: int = MAX_TOKENS) -> Dict:
    """同步调用,返回完整响应字典

    Trace 行为:
      - obs.langsmith_enabled=True 时, 用 langsmith.trace 包裹整个 LLM 调用
      - inputs 包含 messages + model + has_tools
      - error/exception 通过 __exit__ 上报
      - 即使 @obs.trace 装饰器失败, 函数体内部 trace 仍生效
    """
    c = get_client()
    kwargs = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        kwargs["tool_choice"] = "auto"

    ts = _make_langsmith_trace(
        name="llm_chat",
        run_type="llm",
        inputs={"messages": messages, "model": LLM_MODEL, "has_tools": bool(tools)},
    )

    t0 = time.time()
    try:
        resp = c.chat.completions.create(**kwargs)
    except Exception as e:
        latency = time.time() - t0
        obs.record_llm(
            model=LLM_MODEL, latency=latency, ok=False,
            prompt_tokens=0, completion_tokens=0,
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
        _end_langsmith_trace(ts, error=e)
        raise

    latency = time.time() - t0
    msg = resp.choices[0].message
    out = {
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [],
    }
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            out["tool_calls"].append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            })
    p_tok = resp.usage.prompt_tokens if resp.usage else 0
    c_tok = resp.usage.completion_tokens if resp.usage else 0
    out["_usage"] = {
        "prompt_tokens": p_tok,
        "completion_tokens": c_tok,
    }
    obs.record_llm(
        model=LLM_MODEL, latency=latency, ok=True,
        prompt_tokens=p_tok, completion_tokens=c_tok,
    )
    _end_langsmith_trace(ts)
    return out


def chat_stream(messages: List[Dict], tools: List[Dict] = None,
                temperature: float = TEMPERATURE, max_tokens: int = MAX_TOKENS) -> Iterator[str]:
    """流式,只 yield content 增量(忽略 tool_call 流)"""
    c = get_client()
    kwargs = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
    stream = c.chat.completions.create(**kwargs)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content