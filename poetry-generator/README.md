# 七言绝句生成器

输入主题，输出一首古典风格七言绝句 + 白话赏析。

## 用法

```bash
# 交互式
python3 poem.py

# 直接传参
python3 poem.py "秋夜听雨"
python3 poem.py "登山望远"
python3 poem.py "思乡"
```

## 依赖

- Python 3.6+
- 火山方舟 Coding Plan API Key（从 `~/.hermes/.env` 自动读取）
- curl（系统自带）

## 说明

模型：doubao-seed-2-1-lite
响应时间：约 30-60 秒
