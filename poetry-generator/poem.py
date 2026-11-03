#!/usr/bin/env python3
"""
七言绝句生成器 - 基于豆包 LLM
输入：心情 / 场景 / 地点
输出：一首七言绝句 + 简单赏析
"""
import os, sys, json, subprocess

KEY_NAME = "VOLCENGINE_CODING_PLAN_API_KEY"

def get_key():
    with open(os.path.expanduser("~/.hermes/.env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith(KEY_NAME + "="):
                return line.split("=", 1)[1]
    return None

def generate(theme):
    key = get_key()
    prompt = f"""请以「{theme}」为主题，创作一首七言绝句（严格四句，每句七字，平水韵）。
要求：
1. 意境悠远，有古典韵味
2. 符合平仄规律
3. 最后附两句白话赏析

输出格式：
《诗题》
xxxxxxx，xxxxxxx。
xxxxxxx，xxxxxxx。

赏析：xxxxxxx。"""

    body = json.dumps({
        "model": "doubao-seed-2-1-lite-260915",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.8
    })

    cmd = [
        "curl", "-s", "-X", "POST",
        "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
        "-H", f"Authorization: Bearer {key}",
        "-H", "Content-Type: application/json",
        "-d", body
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    data = json.loads(result.stdout)
    return data["choices"][0]["message"]["content"]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        theme = input("请输入主题（如：秋夜听雨、登山望远、思乡）: ").strip()
    else:
        theme = " ".join(sys.argv[1:])

    print(f"\n✨ 以「{theme}」为题，作诗中...\n")
    poem = generate(theme)
    print(poem)
    print()
