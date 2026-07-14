# merge_vocab.py
import os
import pickle
import json

print("=" * 60)
print("📚 合并多个数据集的词汇表")
print("=" * 60)

# 所有数据集路径
datasets = {
    "qa": "data/qa_data/input.txt",
    "law": "data/law_data/input.txt",
    "daily_dialog": "data/daily_dialog/input.txt",
    "dailyreport": "data/dailyreport/input.txt",
    "shakespeare": "data/shakespeare/input.txt",
    "shakespeare_char": "data/shakespeare_char/input.txt",
}

# 1. 收集所有字符
all_chars = set()

for name, path in datasets.items():
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        chars = set(text)
        all_chars.update(chars)
        print(f"✅ {name}: {len(chars)} 个字符")
    else:
        print(f"⚠️ {name}: 文件不存在 {path}")

print(f"\n📊 合并后总字符数: {len(all_chars)}")

# 2. 生成统一词汇表
chars = sorted(list(all_chars))
stoi = {ch: i for i, ch in enumerate(chars)}
itos = {i: ch for i, ch in enumerate(chars)}
vocab_size = len(chars)

unified_meta = {
    "stoi": stoi,
    "itos": itos,
    "vocab_size": vocab_size
}

# 3. 保存统一词汇表
os.makedirs("data/unified", exist_ok=True)
with open("data/unified/meta.pkl", "wb") as f:
    pickle.dump(unified_meta, f)

print(f"✅ 统一词汇表已保存: data/unified/meta.pkl")
print(f"📊 词汇表大小: {vocab_size}")


# 4. 重新编码所有数据集
def reencode_dataset(input_path, output_dir, meta):
    """使用统一词汇表重新编码数据集"""
    stoi = meta['stoi']

    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    import numpy as np
    data = np.array([stoi.get(ch, 0) for ch in text], dtype=np.uint16)

    n = len(data)
    split_idx = int(n * 0.9)
    train_data = data[:split_idx]
    val_data = data[split_idx:]

    os.makedirs(output_dir, exist_ok=True)
    train_data.tofile(os.path.join(output_dir, "train.bin"))
    val_data.tofile(os.path.join(output_dir, "val.bin"))

    # 复制 meta.pkl
    with open(os.path.join(output_dir, "meta.pkl"), "wb") as f:
        pickle.dump(meta, f)

    print(f"✅ 已编码: {output_dir} ({len(data):,} 字符)")


# 5. 重新编码所有数据集
for name, path in datasets.items():
    if os.path.exists(path):
        output_dir = f"data/{name}_unified"
        reencode_dataset(path, output_dir, unified_meta)