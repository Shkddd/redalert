# 每日运势推送

中式风格每日运势生成器，纯本地运行，无 LLM 调用。

## 用法

```bash
python3 fortune.py
```

输出：事业/财运/感情/健康评级、幸运色/数字/方位、今日宜忌3条、总评。

同一天生成结果固定（基于日期哈希），不会早上看一个晚上变一个。

## 定时推送（可选）

用 Hermes cron job 每天早上 8 点推送给你：

```
cronjob action=create schedule="0 8 * * *" prompt="运行 python3 ~/projects/daily-fortune/fortune.py，把输出直接发给我"
```
