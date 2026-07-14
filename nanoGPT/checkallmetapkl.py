# check_all_meta.py
import os
import pickle
import glob

print("=" * 70)
print("🔍 查找并检查所有 meta.pkl 文件")
print("=" * 70)

# 递归查找所有 meta.pkl
meta_files = []
for root, dirs, files in os.walk('data'):
    if 'meta.pkl' in files:
        meta_files.append(os.path.join(root, 'meta.pkl'))

if not meta_files:
    print("❌ 没有找到任何 meta.pkl 文件")
    exit()

print(f"\n📂 找到 {len(meta_files)} 个 meta.pkl 文件:\n")

# 存储结果
results = []

for f in meta_files:
    try:
        with open(f, 'rb') as file:
            meta = pickle.load(file)

        vocab_size = meta.get('vocab_size', 'N/A')
        num_stoi = len(meta.get('stoi', {}))
        num_itos = len(meta.get('itos', {}))

        results.append({
            'path': f,
            'dir': os.path.dirname(f),
            'vocab_size': vocab_size,
            'num_stoi': num_stoi,
            'num_itos': num_itos
        })

    except Exception as e:
        print(f"❌ 读取失败: {f} ({e})")

# 显示结果
print("📊 详细结果:")
print("-" * 70)
print(f"{'目录':<40} {'vocab_size':<12} {'stoi':<8} {'itos':<8}")
print("-" * 70)

for r in results:
    dir_name = r['dir'][:40]
    print(f"{dir_name:<40} {r['vocab_size']:<12} {r['num_stoi']:<8} {r['num_itos']:<8}")

print("-" * 70)

# 统计
vocab_sizes = [r['vocab_size'] for r in results if r['vocab_size'] != 'N/A']
if vocab_sizes:
    print(f"\n📊 统计:")
    print(f"   文件总数: {len(results)}")
    print(f"   不同的 vocab_size: {len(set(vocab_sizes))}")
    print(f"   vocab_size 列表: {sorted(set(vocab_sizes))}")

    # 检查是否一致
    if len(set(vocab_sizes)) == 1:
        print(f"\n✅ 所有 meta.pkl 的 vocab_size 一致: {vocab_sizes[0]}")
    else:
        print(f"\n❌ vocab_size 不一致！")
        # 按 vocab_size 分组
        from collections import defaultdict

        groups = defaultdict(list)
        for r in results:
            groups[r['vocab_size']].append(r['dir'])
        for size, dirs in groups.items():
            print(f"\n   vocab_size={size}:")
            for d in dirs:
                print(f"      - {d}")

# 找出哪些目录用了相同词汇表（通过 MD5）
print("\n" + "=" * 70)
print("🔍 检查文件内容是否相同 (MD5)")
print("=" * 70)

import hashlib

md5_groups = {}
for r in results:
    with open(r['path'], 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    md5_groups[r['path']] = md5

# 按 MD5 分组
from collections import defaultdict

md5_grouped = defaultdict(list)
for path, md5 in md5_groups.items():
    md5_grouped[md5].append(path)

print(f"\n📊 MD5 分组:")
for i, (md5, paths) in enumerate(md5_grouped.items()):
    print(f"\n   组 {i + 1} (MD5: {md5[:16]}...):")
    for p in paths:
        print(f"      - {p}")

if len(md5_grouped) == 1:
    print(f"\n✅ 所有文件内容完全相同！")
else:
    print(f"\n❌ 有 {len(md5_grouped)} 种不同的内容")