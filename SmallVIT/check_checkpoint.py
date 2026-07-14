#!/usr/bin/env python3
"""
检查检查点文件内容
"""
import sys

import torch
import os
import glob


def check_checkpoint(checkpoint_path):
    """检查检查点文件内容"""
    print(f"📂 检查: {checkpoint_path}")

    if not os.path.exists(checkpoint_path):
        print("❌ 文件不存在")
        return

    checkpoint = torch.load(checkpoint_path, map_location='cpu')

    print("\n📊 检查点内容:")
    print("=" * 60)

    for key, value in checkpoint.items():
        if key == 'model_state_dict':
            print(f"  ✅ {key}: 模型权重 (共 {len(value)} 个参数)")
        elif key == 'optimizer_state_dict':
            print(f"  ✅ {key}: 优化器状态")
        elif key == 'scheduler_state_dict':
            print(f"  ✅ {key}: 调度器状态")
        elif key == 'epoch':
            print(f"  ✅ {key}: {value}")
        elif key == 'best_loss':
            print(f"  ✅ {key}: {value}")
        elif key == 'history':
            print(f"  ✅ {key}: {len(value)} 条记录")
            if len(value) > 0:
                print(f"     最后一条: {value[-1]}")
        else:
            print(f"  ✅ {key}: {type(value).__name__}")

    # 如果有历史记录，显示最后几条
    if 'history' in checkpoint and checkpoint['history']:
        print(f"\n📈 最近5条历史记录:")
        print("-" * 40)
        for h in checkpoint['history'][-5:]:
            print(f"  Epoch {h['epoch']:3d}: Loss={h['loss']:.4f}, Temp={h['temperature']:.4f}")

    print("=" * 60)


if __name__ == "__main__":
    # 查找所有检查点
    checkpoint_files = glob.glob("multimodal_checkpoints/checkpoint_epoch_*.pt")
    checkpoint_files += glob.glob("multimodal_checkpoints/latest_checkpoint.pt")
    checkpoint_files += glob.glob("multimodal_checkpoints/best_model.pt")

    if not checkpoint_files:
        print("❌ 没有找到检查点文件")
        sys.exit(1)

    # 按修改时间排序
    checkpoint_files.sort(key=os.path.getmtime, reverse=True)

    for cp in checkpoint_files[:5]:
        check_checkpoint(cp)
        print()