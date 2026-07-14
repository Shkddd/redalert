#!/usr/bin/env python3
"""
轻量级多模态模型训练脚本
支持训练中断后恢复 (resume)
"""

import os
import sys
import json
from typing import List, Tuple, Optional
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import transforms
from PIL import Image
import numpy as np
from tqdm import tqdm
import glob
import random
import time

from lightweight_multimodal import LightweightMultimodalModel, UltraLightweightMultimodal


class MultimodalDataset(torch.utils.data.Dataset):
    """多模态数据集"""

    def __init__(self, data_dir: str = None, img_size: int = 224, max_length: int = 64):
        self.img_size = img_size
        self.max_length = max_length

        # 自动查找数据目录
        if data_dir is None:
            data_dir = self._find_data_dir()

        self.data_dir = data_dir
        captions_path = os.path.join(data_dir, "captions.json")

        if not os.path.exists(captions_path):
            raise FileNotFoundError(f"找不到 {captions_path}")

        with open(captions_path, 'r') as f:
            self.data = json.load(f)

        # 过滤有效数据
        self.valid_data = []
        for item in self.data:
            image_path = os.path.join(data_dir, "images", item['image'])
            if os.path.exists(image_path):
                self.valid_data.append(item)

        print(f"✅ 加载了 {len(self.valid_data)} 条有效数据")

        # 数据增强
        self.transform = transforms.Compose([
            transforms.Resize((img_size, img_size)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomRotation(degrees=10),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

    def _find_data_dir(self):
        """自动查找数据目录"""
        possible_dirs = ["synthetic_data", "synthetic_data_enhanced"]
        for d in possible_dirs:
            if os.path.exists(os.path.join(d, "captions.json")):
                return d
        raise FileNotFoundError("找不到数据目录")

    def __len__(self):
        return len(self.valid_data)

    def __getitem__(self, idx):
        item = self.valid_data[idx]
        image_path = os.path.join(self.data_dir, "images", item['image'])

        # 随机选择描述
        if 'all_captions' in item:
            caption = random.choice(item['all_captions'])
        else:
            caption = item['caption']

        image = Image.open(image_path).convert('RGB')
        image = self.transform(image)

        return {
            'image': image,
            'caption': caption
        }


def collate_fn(batch):
    images = torch.stack([item['image'] for item in batch])
    captions = [item['caption'] for item in batch]
    return {'images': images, 'captions': captions}


def find_latest_checkpoint(output_dir: str) -> Optional[str]:
    """查找最新的检查点 - 优先使用 latest_checkpoint.pt"""
    # 1. 优先使用 latest_checkpoint.pt（如果有）
    latest = os.path.join(output_dir, "latest_checkpoint.pt")
    if os.path.exists(latest):
        return latest

    # 2. 查找 checkpoint_epoch_*.pt
    checkpoint_files = glob.glob(os.path.join(output_dir, "checkpoint_epoch_*.pt"))
    if not checkpoint_files:
        return None

    # 按 epoch 数字排序，取最大的
    def get_epoch_num(path):
        try:
            # 提取 epoch_数字
            import re
            match = re.search(r'epoch_(\d+)', path)
            if match:
                return int(match.group(1))
        except:
            pass
        return 0

    checkpoint_files.sort(key=get_epoch_num, reverse=True)
    return checkpoint_files[0]


def train_multimodal(
        model_type: str = "lightweight",
        data_dir: str = None,
        output_dir: str = "multimodal_checkpoints",
        epochs: int = 100,
        batch_size: int = 16,
        learning_rate: float = 1e-4,
        embed_dim: int = 256,
        img_size: int = 224,
        save_interval: int = 10,
        resume: bool = False,
        resume_path: str = None,
):
    """训练多模态模型（支持 resume）"""

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "samples"), exist_ok=True)

    # 创建模型
    if model_type == "ultra":
        model = UltraLightweightMultimodal(
            embed_dim=min(embed_dim, 128),
            image_size=img_size
        )
    else:
        model = LightweightMultimodalModel(
            embed_dim=embed_dim,
            image_size=img_size
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    # 创建数据集
    dataset = MultimodalDataset(data_dir, img_size)
    dataloader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,
        collate_fn=collate_fn,
        drop_last=True
    )

    # 优化器
    optimizer = optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=0.01
    )

    # 学习率调度器
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=epochs * len(dataloader),
        eta_min=1e-6
    )

    # ============ Resume 逻辑 ============
    start_epoch = 0
    best_loss = float('inf')
    history = []
    checkpoint = None  # 初始化 checkpoint 变量，避免 NameError

    if resume:
        # 如果指定了 resume_path，使用指定的
        if resume_path and os.path.exists(resume_path):
            checkpoint_path = resume_path
        else:
            # 否则自动查找最新的检查点
            checkpoint_path = find_latest_checkpoint(output_dir)

        if checkpoint_path:
            # 加载检查点
            print(f"📂 从检查点恢复: {checkpoint_path}")
            checkpoint = torch.load(checkpoint_path, map_location=device)

            # 加载模型权重
            if 'model_state_dict' in checkpoint:
                model.load_state_dict(checkpoint['model_state_dict'], strict=False)
                print("   ✅ 加载模型权重")
            else:
                model.load_state_dict(checkpoint, strict=False)
                print("   ✅ 加载模型权重")

            # 加载优化器状态
            if 'optimizer_state_dict' in checkpoint:
                optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                print("   ✅ 加载优化器状态")

            # 加载调度器状态
            if 'scheduler_state_dict' in checkpoint:
                scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
                print("   ✅ 加载调度器状态")

            # 加载训练状态
            start_epoch = checkpoint.get('epoch', 0)
            best_loss = checkpoint.get('best_loss', float('inf'))
            history = checkpoint.get('history', [])

            print(f"   ✅ 从 Epoch {start_epoch} 继续")
            print(f"   ✅ 最佳损失: {best_loss:.4f}")
            print(f"   ✅ 历史记录: {len(history)} 条")
            print(f"   📊 从 Epoch {start_epoch} 继续训练 {epochs - start_epoch} 轮")
        else:
            print("⚠️ 没有找到检查点，从头开始训练")
            resume = False  # 没有检查点，从头开始

    # 重新创建调度器（如果从中间恢复，调整 T_max）
    if resume and start_epoch > 0 and checkpoint is not None:
        remaining_steps = (epochs - start_epoch) * len(dataloader)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=remaining_steps,
            eta_min=1e-6
        )
        # 如果有调度器状态，恢复
        if 'scheduler_state_dict' in checkpoint:
            scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
            print("   ✅ 恢复调度器状态")

    print(f"\n📊 训练配置")
    print(f"   - 模型类型: {model_type}")
    print(f"   - 设备: {device}")
    print(f"   - 总轮数: {epochs}")
    print(f"   - 起始轮数: {start_epoch + 1}")
    print(f"   - 剩余轮数: {epochs - start_epoch}")
    print(f"   - 批次大小: {batch_size}")
    print(f"   - 学习率: {learning_rate}")
    print(f"   - 数据量: {len(dataset)}")
    if resume:
        print(f"   - 恢复训练: ✅ 是")
    print("=" * 60)

    for epoch in range(start_epoch, epochs):
        model.train()
        epoch_loss = 0
        num_batches = 0

        progress_bar = tqdm(dataloader, desc=f"Epoch {epoch + 1}/{epochs}")

        for batch in progress_bar:
            images = batch['images'].to(device)
            captions = batch['captions']

            # 前向传播
            logits, loss = model.forward_with_loss(images, captions)

            # 反向传播
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            num_batches += 1

            # 更新进度条
            current_lr = scheduler.get_last_lr()[0]
            progress_bar.set_postfix({
                'loss': f'{loss.item():.4f}',
                'lr': f'{current_lr:.2e}'
            })

        avg_loss = epoch_loss / num_batches

        # 记录历史
        history.append({
            'epoch': epoch + 1,
            'loss': avg_loss,
            'temperature': model.get_temperature(),
            'lr': scheduler.get_last_lr()[0]
        })

        # 打印结果
        print(f"\n✅ Epoch {epoch + 1}/{epochs} 完成")
        print(f"   Loss: {avg_loss:.4f}")
        print(f"   Temperature: {model.get_temperature():.4f}")
        print(f"   LR: {scheduler.get_last_lr()[0]:.2e}")
        print("-" * 60)

        # 保存最佳模型
        if avg_loss < best_loss:
            best_loss = avg_loss
            model.save(os.path.join(output_dir, "best_model.pt"))
            print(f"  ⭐ 保存最佳模型 (Loss: {best_loss:.4f})")

        # 保存检查点（包含完整训练状态）
        if (epoch + 1) % save_interval == 0:
            checkpoint_path = os.path.join(output_dir, f"checkpoint_epoch_{epoch + 1}.pt")
            torch.save({
                'epoch': epoch + 1,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'scheduler_state_dict': scheduler.state_dict(),
                'best_loss': best_loss,
                'history': history,
                'model_type': model_type,
                'embed_dim': embed_dim,
            }, checkpoint_path)
            print(f"  💾 保存检查点: {checkpoint_path}")

        # 保存历史
        with open(os.path.join(output_dir, "history.json"), 'w') as f:
            json.dump(history, f, indent=2)

        # 保存最新的检查点（用于快速恢复）
        latest_checkpoint = os.path.join(output_dir, "latest_checkpoint.pt")
        torch.save({
            'epoch': epoch + 1,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'scheduler_state_dict': scheduler.state_dict(),
            'best_loss': best_loss,
            'history': history,
            'model_type': model_type,
            'embed_dim': embed_dim,
        }, latest_checkpoint)

    # 保存最终模型
    model.save(os.path.join(output_dir, "final_model.pt"))

    print("\n" + "=" * 60)
    print("🎉 训练完成！")
    print(f"最佳损失: {best_loss:.4f}")
    print(f"模型保存在: {output_dir}/")
    print("=" * 60)

    return model, history


# ============ 测试功能 ============

class ModelTester:
    """模型测试器"""

    def __init__(self, model_path: str, model_type: str = "lightweight"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"📱 使用设备: {self.device}")

        # 加载模型
        self.model = self._load_model(model_path, model_type)
        self.model.eval()

        # 图像预处理
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        # 加载标签
        self.label_map = self._load_label_map()

        print("✅ 测试器初始化完成")

    def _load_model(self, model_path: str, model_type: str):
        """加载模型"""
        print(f"📂 加载模型: {model_path}")

        if model_type == "ultra":
            model = UltraLightweightMultimodal()
        else:
            model = LightweightMultimodalModel()

        checkpoint = torch.load(model_path, map_location=self.device)

        if 'model_state_dict' in checkpoint:
            state_dict = checkpoint['model_state_dict']
        else:
            state_dict = checkpoint

        model.load_state_dict(state_dict, strict=False)
        model = model.to(self.device)

        print(f"✅ 模型加载成功")
        return model

    def _load_label_map(self):
        """加载标签映射"""
        possible_paths = [
            "synthetic_data/captions.json",
            "synthetic_data_enhanced/captions.json"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    labels = list(set([item['caption'] for item in data]))
                    return labels
        return None

    def load_image(self, image_path: str) -> torch.Tensor:
        """加载图像"""
        try:
            image = Image.open(image_path).convert('RGB')
            image_tensor = self.transform(image).unsqueeze(0)
            return image_tensor.to(self.device)
        except Exception as e:
            print(f"❌ 加载图片失败: {e}")
            return None

    def test_single_image(self, image_path: str, top_k: int = 10):
        """测试单张图像"""
        print("\n" + "=" * 60)
        print(f"📷 测试图像: {image_path}")
        print("=" * 60)

        # 获取标签
        if self.label_map is None:
            texts = [
                "a red circle", "a blue circle", "a green circle",
                "a red square", "a blue square", "a green square",
                "a red triangle", "a blue triangle", "a green triangle",
                "a red star", "a blue star", "a green star",
                "a red diamond", "a blue diamond", "a green diamond",
                "a red heart", "a blue heart", "a green heart"
            ]
        else:
            texts = self.label_map

        print(f"📝 候选文本: {len(texts)} 个")

        # 加载图像
        image_tensor = self.load_image(image_path)
        if image_tensor is None:
            return

        # 编码图像
        with torch.no_grad():
            image_embed = self.model.encode_image(image_tensor)
            image_embed = torch.nn.functional.normalize(image_embed, dim=-1)

        # 批量编码文本
        print("🧮 计算相似度...")
        start_time = time.time()

        # 分批处理文本
        batch_size = 32
        all_scores = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            with torch.no_grad():
                text_embeds = self.model.encode_text(batch_texts)
                text_embeds = torch.nn.functional.normalize(text_embeds, dim=-1)
                scores = (image_embed @ text_embeds.T).squeeze(0).cpu().numpy()
                all_scores.extend(scores)

        elapsed = time.time() - start_time
        print(f"⏱️  耗时: {elapsed:.3f}s")

        # 排序结果
        results = sorted(zip(texts, all_scores), key=lambda x: x[1], reverse=True)

        # 显示结果
        print("\n📊 匹配结果 (Top {})".format(min(top_k, len(results))))
        print("-" * 60)

        for i, (text, score) in enumerate(results[:top_k]):
            if i == 0:
                emoji = "🥇"
            elif i == 1:
                emoji = "🥈"
            elif i == 2:
                emoji = "🥉"
            else:
                emoji = f"{i + 1:2d}."

            bar_length = int(score * 30)
            bar = "█" * max(0, min(bar_length, 30)) + "░" * (30 - max(0, min(bar_length, 30)))

            print(f"  {emoji} {score:.4f} {bar} {text}")

        # 获取真实标签
        real_label = self._get_real_label(image_path)
        if real_label:
            print(f"\n📌 真实标签: {real_label}")
            for i, (text, _) in enumerate(results):
                if text == real_label:
                    print(f"   排名: 第 {i + 1} 名")
                    break

    def _get_real_label(self, image_path: str) -> str:
        """获取真实标签"""
        possible_paths = [
            "synthetic_data/captions.json",
            "synthetic_data_enhanced/captions.json"
        ]

        image_name = os.path.basename(image_path)

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        for item in data:
                            if item['image'] == image_name:
                                return item['caption']
                except:
                    pass
        return None

    def test_batch(self, image_dir: str, max_samples: int = 20):
        """批量测试"""
        print("\n" + "=" * 60)
        print(f"📸 批量测试: {image_dir}")
        print("=" * 60)

        image_files = sorted(
            glob.glob(os.path.join(image_dir, "*.jpg")) +
            glob.glob(os.path.join(image_dir, "*.png"))
        )

        if not image_files:
            print("❌ 没有找到图像")
            return

        image_files = image_files[:max_samples]
        print(f"📂 找到 {len(image_files)} 张图像")

        # 获取标签
        if self.label_map is None:
            print("❌ 没有标签数据，无法计算准确率")
            return

        correct = 0
        total = 0

        for i, img_path in enumerate(image_files):
            print(f"\n[{i + 1}/{len(image_files)}] {os.path.basename(img_path)}")

            # 获取真实标签
            real_label = self._get_real_label(img_path)
            if not real_label:
                print("  ⚠️ 没有真实标签，跳过")
                continue

            # 测试
            image_tensor = self.load_image(img_path)
            if image_tensor is None:
                continue

            with torch.no_grad():
                image_embed = self.model.encode_image(image_tensor)
                image_embed = torch.nn.functional.normalize(image_embed, dim=-1)

                text_embeds = self.model.encode_text(self.label_map)
                text_embeds = torch.nn.functional.normalize(text_embeds, dim=-1)

                scores = (image_embed @ text_embeds.T).squeeze(0).cpu().numpy()
                results = sorted(zip(self.label_map, scores), key=lambda x: x[1], reverse=True)

                top_pred = results[0][0]

            print(f"  真实: {real_label}")
            print(f"  预测: {top_pred}")

            if top_pred == real_label:
                correct += 1
                print("  ✅ 正确!")
            else:
                print("  ❌ 错误")
                # 显示真实标签的排名
                for j, (text, _) in enumerate(results):
                    if text == real_label:
                        print(f"  真实标签排名: 第 {j + 1} 名")
                        break

            total += 1

        if total > 0:
            print("\n" + "=" * 60)
            print(f"🎯 准确率: {correct}/{total} = {correct / total * 100:.1f}%")
            print("=" * 60)


def te_model(model_path: str, model_type: str = "lightweight", image_path: str = None):
    """测试模型"""
    tester = ModelTester(model_path, model_type)

    if image_path:
        tester.test_single_image(image_path)
    else:
        # 自动查找测试图像
        test_images = glob.glob("synthetic_data/images/*.jpg") + \
                      glob.glob("synthetic_data/images/*.png")
        if test_images:
            tester.test_single_image(sorted(test_images)[0])
        else:
            print("❌ 没有找到测试图像，请使用 --image 指定")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='训练/测试轻量级多模态模型（支持恢复训练）')
    parser.add_argument('--mode', type=str, default='train', choices=['train', 'test'],
                        help='运行模式')
    parser.add_argument('--model_type', type=str, default='lightweight',
                        choices=['lightweight', 'ultra'],
                        help='模型类型 (lightweight: ~15M, ultra: ~5M)')
    parser.add_argument('--data_dir', type=str, default='synthetic_data',
                        help='数据目录')
    parser.add_argument('--output_dir', type=str, default='multimodal_checkpoints',
                        help='输出目录')
    parser.add_argument('--model_path', type=str, default=None,
                        help='模型路径 (测试模式)')
    parser.add_argument('--image', type=str, default=None,
                        help='测试图像路径 (测试模式)')
    parser.add_argument('--epochs', type=int, default=100,
                        help='训练轮数')
    parser.add_argument('--batch_size', type=int, default=32,
                        help='批次大小')
    parser.add_argument('--embed_dim', type=int, default=64,
                        help='嵌入维度')
    parser.add_argument('--top_k', type=int, default=10,
                        help='显示前K个结果')
    parser.add_argument('--learning_rate', type=float, default=1e-4,
                        help='学习率')

    # ============ Resume 相关参数 ============
    parser.add_argument('--resume', action='store_true',
                        help='是否恢复训练')
    parser.add_argument('--resume_path', type=str, default=None,
                        help='指定检查点路径 (默认自动查找最新)')
    parser.add_argument('--no_resume', action='store_true',
                        help='强制从头开始训练（忽略已有检查点）')

    args = parser.parse_args()

    if args.mode == 'train':
        # 如果指定了 no_resume，强制从头开始
        if args.no_resume:
            args.resume = False
            print("⚠️ 强制从头开始训练")

        train_multimodal(
            model_type=args.model_type,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            embed_dim=args.embed_dim,
            learning_rate=args.learning_rate,
            resume=args.resume,
            resume_path=args.resume_path,
        )
    else:  # test mode
        if args.model_path is None:
            # 自动查找模型
            possible_paths = [
                os.path.join(args.output_dir, "best_model.pt"),
                os.path.join(args.output_dir, "final_model.pt"),
                "multimodal_checkpoints/best_model.pt",
                "multimodal_checkpoints/final_model.pt"
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    args.model_path = path
                    break

        if args.model_path is None:
            print("❌ 找不到模型文件")
            print("请使用 --model_path 指定模型路径")
            print("或先运行训练: python train_multimodal.py --mode train")
            sys.exit(1)

        te_model(args.model_path, args.model_type, args.image)