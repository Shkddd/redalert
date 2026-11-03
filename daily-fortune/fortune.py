#!/usr/bin/env python3
"""
每日运势推送 - 中式星座+八字风格
纯随机，无 LLM 调用，本地秒出
"""
import random
from datetime import datetime

# 12生肖
ZODIAC = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

# 每日宜忌
DO_LIST = [
    "谈合作", "见客户", "签合同", "吃火锅", "早睡早起",
    "给父母打电话", "整理桌面", "运动30分钟", "学习新东西", "喝8杯水",
    "买一张彩票", "夸身边人", "写日记", "冥想10分钟", "拒绝无效社交",
]
DONT_LIST = [
    "冲动消费", "熬夜", "跟人吵架", "随便借钱", "点外卖吃垃圾食品",
    "拖延重要工作", "刷短视频超过1小时", "发朋友圈发牢骚", "吃生冷食物",
    "轻信陌生人", "在气头上做决定", "忘记喝水", "久坐不动", "胡思乱想",
]

# 幸运元素
LUCKY_COLORS = ["朱红", "靛蓝", "明黄", "墨黑", "月白", "青绿", "橙红", "灰紫", "檀棕", "藕粉"]
LUCKY_NUMBERS = list(range(1, 10))
LUCKY_DIRECTIONS = ["正东", "正南", "正西", "正北", "东南", "东北", "西南", "西北"]

# 运势等级
GRADES = ["大吉", "中吉", "小吉", "平", "小凶", "中凶"]

def generate_fortune():
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hash(today) % 10000  # 同一天结果固定

    rng = random.Random(seed)

    work = rng.choice(GRADES)
    money = rng.choice(GRADES)
    love = rng.choice(GRADES)
    health = rng.choice(GRADES)

    do = rng.sample(DO_LIST, 3)
    dont = rng.sample(DONT_LIST, 3)
    color = rng.choice(LUCKY_COLORS)
    number = rng.choice(LUCKY_NUMBERS)
    direction = rng.choice(LUCKY_DIRECTIONS)

    # 总评
    all_grades = [work, money, love, health]
    good_count = sum(1 for g in all_grades if "吉" in g)
    if good_count >= 3:
        summary = "今日诸事顺遂，宜主动出击，把握机会。"
    elif good_count >= 2:
        summary = "今日平稳中带小喜，按部就班即可。"
    elif good_count >= 1:
        summary = "今日宜守不宜攻，稳扎稳打为上。"
    else:
        summary = "今日诸事不宜大事，低调蛰伏，蓄力待发。"

    print(f"""
╔══════════════════════════════════════╗
║     每 日 运 势  ·  {today}
╚══════════════════════════════════════╝

📊 今日评级
   事业运: {work}    财运: {money}
   感情运: {love}    健康运: {health}

✨ 幸运指南
   幸运色: {color}
   幸运数字: {number}
   幸运方位: {direction}

✅ 今日宜
   1. {do[0]}
   2. {do[1]}
   3. {do[2]}

❌ 今日忌
   1. {dont[0]}
   2. {dont[1]}
   3. {dont[2]}

💬 总评
   {summary}
""")

if __name__ == "__main__":
    generate_fortune()
