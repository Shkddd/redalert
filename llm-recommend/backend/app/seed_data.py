"""种子数据 - 电商商品 + 用户 + 交互"""
import json
import numpy as np
from app.database import get_db
from app.embedder import embed_texts


ITEMS = [
    # 电子产品
    {"name": "iPhone 16 Pro", "category": "电子", "subcategory": "手机", "price": 8999, "tags": "苹果,手机,旗舰,拍照", "description": "A18 Pro芯片，钛金属机身，4800万像素三摄系统"},
    {"name": "华为 Mate 70 Pro", "category": "电子", "subcategory": "手机", "price": 6999, "tags": "华为,手机,鸿蒙,国产", "description": "麒麟芯片，鸿蒙系统，卫星通信"},
    {"name": "小米15 Ultra", "category": "电子", "subcategory": "手机", "price": 5999, "tags": "小米,手机,性价比,拍照", "description": "骁龙8至尊版，徕卡影像，120W快充"},
    {"name": "AirPods Pro 3", "category": "电子", "subcategory": "耳机", "price": 1899, "tags": "苹果,耳机,降噪,无线", "description": "H3芯片，自适应降噪，空间音频"},
    {"name": "Sony WH-1000XM6", "category": "电子", "subcategory": "耳机", "price": 2499, "tags": "索尼,耳机,降噪,头戴", "description": "V2处理器，30小时续航，多点连接"},
    {"name": "MacBook Air M4", "category": "电子", "subcategory": "笔记本", "price": 9999, "tags": "苹果,笔记本,轻薄,办公", "description": "M4芯片，18小时续航，Liquid Retina显示屏"},
    {"name": "ThinkPad X1 Carbon", "category": "电子", "subcategory": "笔记本", "price": 8999, "tags": "联想,笔记本,商务,轻薄", "description": "Intel Ultra处理器，2.8K OLED屏，商务旗舰"},
    {"name": "iPad Pro M4", "category": "电子", "subcategory": "平板", "price": 7999, "tags": "苹果,平板,创作,画画", "description": "M4芯片，Ultra Retina XDR显示屏，Apple Pencil Pro"},
    {"name": "Steam Deck OLED", "category": "电子", "subcategory": "游戏机", "price": 4399, "tags": "游戏,掌机,Steam,便携", "description": "7.4寸OLED屏，SteamOS，512GB存储"},
    {"name": "PS5 Pro", "category": "电子", "subcategory": "游戏机", "price": 5299, "tags": "索尼,游戏,主机,4K", "description": "增强GPU，8K游戏支持，2TB SSD"},

    # 服装
    {"name": "优衣库 轻薄羽绒服", "category": "服装", "subcategory": "外套", "price": 499, "tags": "优衣库,羽绒服,保暖,轻便", "description": "高品质鹅绒填充，轻薄保暖，可收纳"},
    {"name": "Nike Air Max 270", "category": "服装", "subcategory": "运动鞋", "price": 999, "tags": "耐克,运动鞋,气垫,跑步", "description": "270度大气垫，网面透气，日常百搭"},
    {"name": "Lululemon Align 瑜伽裤", "category": "服装", "subcategory": "运动服", "price": 850, "tags": "瑜伽,运动裤,紧身,舒适", "description": "Nulu面料，裸感舒适，四向弹力"},
    {"name": "Canada Goose 远征派克大衣", "category": "服装", "subcategory": "外套", "price": 9800, "tags": "羽绒服,加拿大鹅,极寒,户外", "description": "抗寒-30°C，Arctic Tech面料，可拆卸兜帽"},

    # 食品
    {"name": "三顿半精品速溶咖啡", "category": "食品", "subcategory": "饮品", "price": 189, "tags": "咖啡,速溶,精品,提神", "description": "冷萃冻干技术，3秒速溶，12颗装"},
    {"name": "良品铺子坚果礼盒", "category": "食品", "subcategory": "零食", "price": 168, "tags": "坚果,礼盒,送礼,健康", "description": "每日坚果混合装，1.5kg礼盒"},
    {"name": "农夫山泉 东方树叶", "category": "食品", "subcategory": "饮品", "price": 5, "tags": "茶饮料,无糖,健康,日常", "description": "0糖0卡0脂，茉莉花茶口味"},

    # 家居
    {"name": "戴森 V15 Detect 吸尘器", "category": "家居", "subcategory": "清洁", "price": 4990, "tags": "戴森,吸尘器,无线,激光", "description": "激光探测灰尘，HEPA过滤，60分钟续航"},
    {"name": "米家 智能台灯 Pro", "category": "家居", "subcategory": "灯具", "price": 299, "tags": "小米,台灯,护眼,智能", "description": "无蓝光危害，色温调节，APP控制"},
    {"name": "网易严选 乳胶枕", "category": "家居", "subcategory": "寝具", "price": 199, "tags": "枕头,乳胶,泰国,睡眠", "description": "泰国天然乳胶，抗菌防螨，高低弧形设计"},

    # 运动
    {"name": "Garmin Forerunner 265", "category": "运动", "subcategory": "手表", "price": 3080, "tags": "运动手表,跑步,GPS,心率", "description": "AMOLED屏，跑步动态，13天续航"},
    {"name": "YOGA PRO 瑜伽垫", "category": "运动", "subcategory": "器材", "price": 299, "tags": "瑜伽垫,防滑,TPE,健身", "description": "6mm加厚，双面防滑，环保TPE材质"},
    {"name": "迪卡侬 登山包 40L", "category": "运动", "subcategory": "户外", "price": 399, "tags": "登山包,户外,徒步,大容量", "description": "40升容量，背负系统，防雨罩"},

    # 美妆
    {"name": "SK-II 神仙水 230ml", "category": "美妆", "subcategory": "护肤", "price": 1190, "tags": "SK-II,护肤,精华,保湿", "description": "Pitera精华，改善肤质，提亮肤色"},
    {"name": "兰蔻 小黑瓶精华", "category": "美妆", "subcategory": "护肤", "price": 980, "tags": "兰蔻,精华,抗老,修护", "description": "微生态科技，修护肌肤屏障"},

    # 图书
    {"name": "《深度学习》花书", "category": "图书", "subcategory": "技术", "price": 128, "tags": "深度学习,AI,机器学习,经典", "description": "Ian Goodfellow著，深度学习领域圣经"},
    {"name": "《置身事内》", "category": "图书", "subcategory": "社科", "price": 65, "tags": "经济,中国,政府,发展", "description": "兰小欢著，理解中国政府与经济发展"},
    {"name": "《三体》全集", "category": "图书", "subcategory": "小说", "price": 108, "tags": "科幻,刘慈欣,经典,宇宙", "description": "雨果奖获奖作品，中国科幻巅峰"},
]

USERS = [
    {"username": "alice", "display_name": "Alice", "preferences": "喜欢苹果产品，注重品质"},
    {"username": "bob", "display_name": "Bob", "preferences": "性价比优先，国产品牌偏好"},
    {"username": "carol", "display_name": "Carol", "preferences": "运动健身爱好者，户外探索"},
    {"username": "dave", "display_name": "Dave", "preferences": "科技数码发烧友，游戏爱好者"},
    {"username": "eve", "display_name": "Eve", "preferences": "美妆护肤，时尚穿搭"},
]

# 用户行为: (username, item_name, action)
INTERACTIONS = [
    ("alice", "iPhone 16 Pro", "purchase"),
    ("alice", "AirPods Pro 3", "purchase"),
    ("alice", "MacBook Air M4", "like"),
    ("alice", "iPad Pro M4", "view"),
    ("alice", "SK-II 神仙水 230ml", "purchase"),
    ("alice", "Lululemon Align 瑜伽裤", "like"),
    ("bob", "小米15 Ultra", "purchase"),
    ("bob", "米家 智能台灯 Pro", "purchase"),
    ("bob", "华为 Mate 70 Pro", "like"),
    ("bob", "三顿半精品速溶咖啡", "purchase"),
    ("bob", "网易严选 乳胶枕", "like"),
    ("bob", "《置身事内》", "purchase"),
    ("carol", "Garmin Forerunner 265", "purchase"),
    ("carol", "YOGA PRO 瑜伽垫", "purchase"),
    ("carol", "迪卡侬 登山包 40L", "like"),
    ("carol", "Nike Air Max 270", "purchase"),
    ("carol", "Lululemon Align 瑜伽裤", "purchase"),
    ("carol", "良品铺子坚果礼盒", "like"),
    ("dave", "PS5 Pro", "purchase"),
    ("dave", "Steam Deck OLED", "purchase"),
    ("dave", "iPhone 16 Pro", "like"),
    ("dave", "ThinkPad X1 Carbon", "view"),
    ("dave", "Sony WH-1000XM6", "purchase"),
    ("dave", "《深度学习》花书", "like"),
    ("dave", "《三体》全集", "purchase"),
    ("eve", "SK-II 神仙水 230ml", "purchase"),
    ("eve", "兰蔻 小黑瓶精华", "purchase"),
    ("eve", "Canada Goose 远征派克大衣", "like"),
    ("eve", "优衣库 轻薄羽绒服", "purchase"),
    ("eve", "AirPods Pro 3", "like"),
]


def seed(force: bool = False):
    """写入种子数据"""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if count > 0 and not force:
            return {"items": count, "users": "existing", "status": "skip"}

        if force:
            conn.execute("DELETE FROM interactions")
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM users")

        # 商品
        item_id_map = {}
        for item in ITEMS:
            cur = conn.execute(
                """INSERT INTO items (name, category, subcategory, description, price, tags)
                   VALUES (?,?,?,?,?,?)""",
                (item["name"], item["category"], item["subcategory"],
                 item["description"], item["price"], item["tags"]),
            )
            item_id_map[item["name"]] = cur.lastrowid

        # 生成 embedding
        texts = [f"{i['name']} {i['category']} {i['tags']} {i['description']}" for i in ITEMS]
        vecs = embed_texts(texts)
        for item, vec in zip(ITEMS, vecs):
            iid = item_id_map[item["name"]]
            conn.execute("UPDATE items SET embedding=? WHERE id=?",
                         (vec.astype(np.float32).tobytes(), iid))

        # 用户
        user_id_map = {}
        for user in USERS:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, preferences) VALUES (?,?,?)",
                (user["username"], user["display_name"], user["preferences"]),
            )
            user_id_map[user["username"]] = cur.lastrowid

        # 交互
        for username, item_name, action in INTERACTIONS:
            uid = user_id_map.get(username)
            iid = item_id_map.get(item_name)
            if uid and iid:
                conn.execute(
                    "INSERT INTO interactions (user_id, item_id, action) VALUES (?,?,?)",
                    (uid, iid, action),
                )

    return {"items": len(ITEMS), "users": len(USERS), "interactions": len(INTERACTIONS), "status": "ok"}
