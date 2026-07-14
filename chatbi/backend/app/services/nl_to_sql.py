"""LLM-driven NL-to-SQL service using OpenAI-compatible API."""

from __future__ import annotations
import json
import re
from openai import OpenAI
from openai import Timeout as OpenAITimeout
from .data_context import SCHEMA_DESCRIPTION, FEW_SHOT_EXAMPLES, SYSTEM_PROMPT

_LLM_TIMEOUT_SECONDS = 45


def _build_system_prompt(schema_text: str | None = None) -> str:
    schema = schema_text if schema_text else SCHEMA_DESCRIPTION
    return SYSTEM_PROMPT.format(SCHEMA=schema, FEW_SHOT=FEW_SHOT_EXAMPLES)


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences and extra text."""
    # Try to find ```json ... ``` block
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    # Try direct JSON parse
    text = text.strip()
    # Find first { and last }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def generate_sql(
    question: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-chat",
    conversation_history: list[dict] | None = None,
    schema_text: str | None = None,
) -> dict:
    """
    Convert natural language to SQL using LLM.

    Returns:
        dict with keys: sql, explanation, visualization
    """
    if not api_key:
        return {
            "sql": "",
            "explanation": "未配置LLM API key。请在.env中设置LLM_API_KEY。",
            "visualization": None,
        }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=OpenAITimeout(_LLM_TIMEOUT_SECONDS))

        messages = [
            {"role": "system", "content": _build_system_prompt(schema_text)},
        ]

        # Add conversation context if available
        if conversation_history:
            for msg in conversation_history[-6:]:  # Last 3 turns
                messages.append(msg)

        messages.append({"role": "user", "content": question})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content or ""
        result = _extract_json(raw)

        # Validate
        if "sql" not in result:
            result["sql"] = ""
        if "explanation" not in result:
            result["explanation"] = raw[:500]
        if "visualization" not in result:
            result["visualization"] = None

        return result

    except json.JSONDecodeError as e:
        return {
            "sql": "",
            "explanation": f"LLM返回格式异常，无法解析: {str(e)}",
            "visualization": None,
            "_raw": text if 'text' in dir() else "",
        }
    except Exception as e:
        return {
            "sql": "",
            "explanation": f"LLM调用失败: {str(e)}。请检查LLM_BASE_URL和LLM_API_KEY配置。",
            "visualization": None,
        }
