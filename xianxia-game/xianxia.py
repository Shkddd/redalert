#!/usr/bin/env python3
"""
青云录 - 修仙文字冒险游戏
基于"青云残玉"故事扩展
"""
import json, os, random, sys
from datetime import datetime

SAVE_FILE = os.path.expanduser("~/.xianxia_save.json")

CULTIVATION = ["炼气一层", "炼气二层", "炼气三层", "炼气四层", "炼气五层", "炼气六层",
               "炼气七层", "炼气八层", "炼气九层", "筑基初期", "筑基中期", "筑基后期",
               "金丹初期", "金丹中期", "金丹后期", "元婴期", "化神期"]

LOCATIONS = {
    "青云山外门": {
        "desc": "你站在青云山外门的青石牌坊下。远处云雾缭绕，偶尔有仙鹤掠过。",
        "actions": {
            "打坐修炼": {"type": "cultivate", "gain": (5, 15)},
            "下山赶集": {"type": "market"},
            "去后山断崖": {"type": "goto", "target": "后山断崖"},
            "去藏经阁": {"type": "goto", "target": "藏经阁"},
        }
    },
    "后山断崖": {
        "desc": "冷风呼啸，谷底是黑沉沉的老林。你怀中那枚残玉隐隐发热。",
        "actions": {
            "残玉引气": {"type": "jade_cultivate", "gain": (20, 40)},
            "眺望谷底": {"type": "event", "event": "crane"},
            "返回外门": {"type": "goto", "target": "青云山外门"},
        }
    },
    "藏经阁": {
        "desc": "书架上密密麻麻，落着薄灰。只有最基础的功法摆在最外层。",
        "actions": {
            "翻阅基础功法": {"type": "study", "gain": (10, 20)},
            "尝试偷进内室": {"type": "event", "event": "steal_book"},
            "返回外门": {"type": "goto", "target": "青云山外门"},
        }
    },
    "山下集市": {
        "desc": "人声鼎沸，摊贩吆喝着各种灵药和法器。你腰间的钱袋叮当响。",
        "actions": {
            "逛地摊": {"type": "event", "event": "stall"},
            "买丹药(10两)": {"type": "buy_pill", "cost": 10},
            "返回山门": {"type": "goto", "target": "青云山外门"},
        }
    }
}

EVENTS = {
    "crane": "一只雪白的老鹤从谷底飞起，唳鸣一声。你心中若有所悟，灵气微微涌动。",
    "steal_book": "你刚伸手碰向内室的门，一道剑气擦着耳边飞过！执事的声音从身后传来：「外门弟子，不得入内。」你被吓出一身冷汗，灵气反倒精进了几分。",
    "stall": random.choice([
        "你在地摊角落发现一块灰扑扑的石头，摊主说是废石。你花了2两银子买下——正是你的残玉！",
        "一个老道拉住你说：「道友，我看你骨骼清奇，这本《青云心法》只要5两。」你翻了翻，发现是盗版。",
        "你看到一个小偷偷了一位师姐的钱袋。追还是不追？",
    ])
}

def new_game():
    return {
        "name": "林砚",
        "location": "青云山外门",
        "spirit": 0,          # 灵气值
        "cultivation_level": 0,  # 索引 CULTIVATION
        "gold": 20,
        "items": ["残玉"],
        "hp": 100,
        "day": 1,
    }

def save(state):
    with open(SAVE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE) as f:
            return json.load(f)
    return None

def show_status(s):
    print("\n" + "="*50)
    print(f"【{s['name']}】  {CULTIVATION[s['cultivation_level']]}")
    print(f"  灵气: {s['spirit']}  |  气血: {s['hp']}  |  银两: {s['gold']} 两")
    print(f"  物品: {', '.join(s['items']) if s['items'] else '无'}")
    print(f"  时间: 第 {s['day']} 天")
    print("="*50)

def cultivate(s, gain):
    actual = random.randint(*gain)
    s["spirit"] += actual
    print(f"\n你盘膝坐下，引气入体。灵气增长 {actual} 点。")
    # check breakthrough
    needed = (s["cultivation_level"] + 1) * 50
    if s["spirit"] >= needed:
        s["cultivation_level"] += 1
        s["spirit"] = 0
        print(f"\n✨ 突破！你进入了【{CULTIVATION[s['cultivation_level']]}】！")

def handle_action(s, action_key):
    loc = LOCATIONS[s["location"]]
    act = loc["actions"][action_key]

    if act["type"] == "cultivate":
        cultivate(s, act["gain"])
        s["day"] += 1

    elif act["type"] == "jade_cultivate":
        print("\n你将灵气引入残玉，青光沿掌心蜿蜒而上，如小龙入体！")
        cultivate(s, act["gain"])
        s["day"] += 1

    elif act["type"] == "study":
        cultivate(s, act["gain"])
        s["day"] += 1

    elif act["type"] == "goto":
        s["location"] = act["target"]
        print(f"\n你来到了【{s['location']}】。")

    elif act["type"] == "market":
        s["location"] = "山下集市"
        print(f"\n你来到了【山下集市】。")

    elif act["type"] == "event":
        ev = EVENTS.get(act["event"], "什么也没发生。")
        print(f"\n{ev}")
        if act["event"] == "stall":
            s["spirit"] += random.randint(5, 15)
            print("你若有所悟，灵气 +5~15。")
        s["day"] += 1

    elif act["type"] == "buy_pill":
        if s["gold"] >= act["cost"]:
            s["gold"] -= act["cost"]
            s["hp"] += 30
            s["items"].append("聚气丹")
            print(f"\n你花了 {act['cost']} 两银子买了一枚聚气丹。气血 +30。")
        else:
            print("\n银两不够！")

def main():
    print("╔══════════════════════════════════════╗")
    print("║       青 云 录 · 修 仙 文 字 游 戏    ║")
    print("╚══════════════════════════════════════╝\n")

    s = load()
    if s:
        print("读取存档成功。")
    else:
        print("新游戏开始。你是青云山外门弟子林砚，已在外门三年，炼气三层。")
        s = new_game()
        s["cultivation_level"] = 2  # 故事设定：一开始炼气三层

    while True:
        show_status(s)
        loc = LOCATIONS[s["location"]]
        print(f"\n📍 当前地点: {s['location']}")
        print(f"   {loc['desc']}\n")

        actions = list(loc["actions"].keys())
        for i, a in enumerate(actions, 1):
            print(f"  {i}. {a}")
        print("  0. 存档并退出")

        choice = input("\n> 选择行动: ").strip()
        if choice == "0":
            save(s)
            print("已存档。后会有期，道友。")
            break

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(actions):
                handle_action(s, actions[idx])
            else:
                print("无效选择。")
        except ValueError:
            print("请输入数字。")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n\n已退出。")
