#!/usr/bin/env python3
"""
轻量级多模态模型测试脚本
支持单张测试、批量测试和交互式测试
"""

import os
import sys
import json
import torch
import torch.nn.functional as F
from torchvision import transforms
from PIL import Image
import numpy as np
from typing import List, Tuple, Dict
import glob
import argparse
import time

from lightweight_multimodal import LightweightMultimodalModel, UltraLightweightMultimodal


class MultimodalTester:
    """多模态模型测试器"""

    def __init__(self, model_path: str, model_type: str = "lightweight", device: str = None):
        """
        初始化测试器

        Args:
            model_path: 模型权重路径
            model_type: 模型类型 ("lightweight" 或 "ultra")
            device: 运行设备
        """
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
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

        # 加载标签映射（如果有）
        self.label_map = self._load_label_map()

        print("✅ 测试器初始化完成")

    def _load_model(self, model_path: str, model_type: str):
        """加载模型"""
        print(f"📂 加载模型: {model_path}")

        # 创建模型
        if model_type == "ultra":
            model = UltraLightweightMultimodal()
        else:
            model = LightweightMultimodalModel()

        # 加载权重
        checkpoint = torch.load(model_path, map_location=self.device)

        # 兼容不同保存格式
        if 'model_state_dict' in checkpoint:
            state_dict = checkpoint['model_state_dict']
        else:
            state_dict = checkpoint

        model.load_state_dict(state_dict, strict=False)
        model = model.to(self.device)

        print(f"✅ 模型加载成功")
        return model

    def _load_label_map(self) -> Dict:
        """加载标签映射"""
        # 尝试从数据目录加载
        possible_paths = [
            "synthetic_data/captions.json",
            "synthetic_data_enhanced/captions.json"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    # 提取所有唯一标签
                    labels = list(set([item['caption'] for item in data]))
                    return {i: label for i, label in enumerate(labels)}

        return None

    def load_image(self, image_path: str) -> torch.Tensor:
        """加载并预处理单张图像"""
        try:
            image = Image.open(image_path).convert('RGB')
            image_tensor = self.transform(image).unsqueeze(0)
            return image_tensor.to(self.device)
        except Exception as e:
            print(f"❌ 加载图片失败 {image_path}: {e}")
            return None

    def encode_image(self, image_path: str) -> torch.Tensor:
        """编码单张图像"""
        image_tensor = self.load_image(image_path)
        if image_tensor is None:
            return None

        with torch.no_grad():
            image_embed = self.model.encode_image(image_tensor)
            image_embed = F.normalize(image_embed, dim=-1)

        return image_embed

    def encode_texts(self, texts: List[str]) -> torch.Tensor:
        """编码文本列表"""
        with torch.no_grad():
            text_embeds = self.model.encode_text(texts)
            text_embeds = F.normalize(text_embeds, dim=-1)
        return text_embeds

    def compute_similarity(self, image_path: str, texts: List[str]) -> List[Tuple[str, float]]:
        """
        计算图像与文本列表的相似度

        Args:
            image_path: 图像路径
            texts: 文本列表

        Returns:
            List[(text, similarity)] 按相似度降序排列
        """
        image_embed = self.encode_image(image_path)
        if image_embed is None:
            return []

        text_embeds = self.encode_texts(texts)

        # 计算相似度
        similarities = image_embed @ text_embeds.T
        similarities = similarities.squeeze(0).cpu().numpy()

        # 排序
        results = sorted(zip(texts, similarities), key=lambda x: x[1], reverse=True)

        return results

    def test_single_image(self, image_path: str, top_k: int = 10):
        """测试单张图像"""
        print("\n" + "=" * 60)
        print(f"📷 测试图像: {image_path}")
        print("=" * 60)

        # 获取标签
        if self.label_map is None:
            # 使用默认标签
            default_labels = [
                "a red circle", "a blue circle", "a green circle",
                "a red square", "a blue square", "a green square",
                "a red triangle", "a blue triangle", "a green triangle",
                "a red star", "a blue star", "a green star",
                "a red diamond", "a blue diamond", "a green diamond",
                "a red heart", "a blue heart", "a green heart",
                "a yellow circle", "a yellow square", "a yellow triangle",
                "a purple circle", "a purple square", "a purple triangle",
                "a orange circle", "a orange square", "a orange triangle",
                "a pink circle", "a cyan square", "a red hexagon"
            ]
            texts = default_labels
            print(f"📝 使用默认标签: {len(texts)} 个")
        else:
            texts = list(self.label_map.values())
            print(f"📝 使用数据标签: {len(texts)} 个")

        # 计算相似度
        print("\n🧮 计算相似度...")
        start_time = time.time()
        results = self.compute_similarity(image_path, texts)
        elapsed = time.time() - start_time
        print(f"⏱️  耗时: {elapsed:.3f}s")

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

            # 置信度条
            bar_length = int(score * 30)
            bar = "█" * bar_length + "░" * (30 - bar_length)

            print(f"  {emoji} {score:.4f} {bar} {text}")

        # 计算置信度分布
        if len(results) > 1:
            scores = [s for _, s in results[:5]]
            if scores:
                print("\n📈 置信度分布 (Top 5):")
                print("-" * 60)
                for text, score in results[:5]:
                    percentage = score / sum(scores) * 100 if sum(scores) > 0 else 0
                    bar = "█" * int(percentage / 2)
                    print(f"  {text[:30]:30s} {percentage:6.1f}% {bar}")

        return results

    def test_batch(self, image_dir: str, max_samples: int = 20):
        """批量测试"""
        print("\n" + "=" * 60)
        print(f"📸 批量测试: {image_dir}")
        print("=" * 60)

        # 获取所有图像
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
        if self.label_map is not None:
            texts = list(self.label_map.values())
        else:
            texts = [
                "a red circle", "a blue circle", "a green circle",
                "a red square", "a blue square", "a green square",
                "a red triangle", "a blue triangle", "a green triangle"
            ]

        # 批量测试
        correct = 0
        total = 0
        results_list = []

        for i, img_path in enumerate(image_files):
            print(f"\n[{i + 1}/{len(image_files)}] {os.path.basename(img_path)}")

            results = self.compute_similarity(img_path, texts)
            if results:
                top_pred = results[0][0]
                results_list.append((img_path, top_pred, results))

                # 获取真实标签
                real_label = self._get_real_label(img_path)
                if real_label:
                    print(f"  真实: {real_label}")
                    print(f"  预测: {top_pred}")
                    if top_pred == real_label:
                        correct += 1
                        print("  ✅ 正确!")
                    else:
                        print("  ❌ 错误")
                    total += 1

        # 计算准确率
        if total > 0:
            print("\n" + "=" * 60)
            print(f"🎯 准确率: {correct}/{total} = {correct / total * 100:.1f}%")
            print("=" * 60)

        return results_list

    def _get_real_label(self, image_path: str) -> str:
        """获取图像的真实标签"""
        # 尝试从数据目录读取
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

    def interactive_mode(self):
        """交互式测试模式"""
        print("\n" + "=" * 60)
        print("🔄 交互式测试模式")
        print("=" * 60)
        print("输入图像路径进行测试，输入 'quit' 退出")
        print("示例: synthetic_data/images/shape_0000.jpg")
        print("-" * 60)

        while True:
            user_input = input("\n📷 图像路径 > ").strip()

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 退出测试")
                break

            if not os.path.exists(user_input):
                print(f"❌ 文件不存在: {user_input}")
                continue

            # 检查是否是图像文件
            if user_input.lower().endswith(('.jpg', '.png', '.jpeg')):
                self.test_single_image(user_input)
            else:
                # 尝试作为目录
                if os.path.isdir(user_input):
                    self.test_batch(user_input)
                else:
                    print("❌ 请输入图像路径或目录路径")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='轻量级多模态模型测试')
    parser.add_argument('--model', type=str, default=None,
                        help='模型路径 (默认自动查找)')
    parser.add_argument('--model_type', type=str, default='lightweight',
                        choices=['lightweight', 'ultra'],
                        help='模型类型')
    parser.add_argument('--mode', type=str, default='single',
                        choices=['single', 'batch', 'interactive'],
                        help='测试模式')
    parser.add_argument('--image', type=str, default=None,
                        help='图像路径 (单张测试)')
    parser.add_argument('--image_dir', type=str, default='synthetic_data/images',
                        help='图像目录 (批量测试)')
    parser.add_argument('--top_k', type=int, default=10,
                        help='显示前K个结果')
    parser.add_argument('--max_samples', type=int, default=20,
                        help='批量测试最大样本数')

    args = parser.parse_args()

    # 自动查找模型
    if args.model is None:
        possible_paths = [
            "multimodal_checkpoints/best_model.pt",
            "multimodal_checkpoints/final_model.pt",
            "checkpoints/best_model.pt",
            "checkpoints/final_model.pt"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                args.model = path
                break

        if args.model is None:
            print("❌ 找不到模型文件")
            print("请使用 --model 指定模型路径")
            print("或先运行训练: python train_multimodal.py")
            return

    # 创建测试器
    tester = MultimodalTester(args.model, args.model_type)

    # 运行测试
    if args.mode == 'single':
        if args.image is None:
            # 自动查找测试图像
            test_images = glob.glob("synthetic_data/images/*.jpg") + \
                          glob.glob("synthetic_data/images/*.png")
            if test_images:
                args.image = sorted(test_images)[0]
                print(f"📷 自动选择图像: {args.image}")
            else:
                print("❌ 请使用 --image 指定图像路径")
                return

        tester.test_single_image(args.image, args.top_k)

    elif args.mode == 'batch':
        tester.test_batch(args.image_dir, args.max_samples)

    else:  # interactive
        tester.interactive_mode()


if __name__ == "__main__":
    main()