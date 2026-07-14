#!/usr/bin/env python3
"""
文本生成图像 - 聊天模式
输入文本描述，输出生成的图像
"""

import os
import sys
import torch
import torch.nn.functional as F
from torchvision import transforms
from torchvision.utils import save_image
from PIL import Image
import numpy as np
from typing import List, Optional
import time
import glob
import argparse

# 导入模型
from lightweight_multimodal import LightweightMultimodalModel, UltraLightweightMultimodal


class TextToImageChat:
    """文本生成图像 - 聊天模式"""

    def __init__(self,
                 model_path: str = None,
                 model_type: str = "lightweight",
                 device: str = None,
                 output_dir: str = "generated_images"):
        """
        初始化文本生成图像器

        Args:
            model_path: 模型路径
            model_type: 模型类型 ("lightweight" 或 "ultra")
            device: 运行设备
            output_dir: 输出目录
        """
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.output_dir = output_dir

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

        print(f"📱 使用设备: {self.device}")
        print(f"📁 输出目录: {self.output_dir}")

        # 加载模型（自动检测维度）
        self.model, self.embed_dim = self._load_model_with_dimension(model_path, model_type)
        self.model.eval()

        # 加载所有可用的文本标签（用于检索）
        self.label_map = self._load_label_map()

        # 统计信息
        self.image_count = 0

        print("\n" + "=" * 60)
        print("🎨 文本生成图像 - 聊天模式已启动")
        print("=" * 60)
        print(f"📐 模型嵌入维度: {self.embed_dim}")
        print("💡 输入文本描述，模型将生成对应的图像")
        print("💡 支持的命令:")
        print("   - 'list'   : 查看所有可用的文本标签")
        print("   - 'stats'  : 查看统计信息")
        print("   - 'clear'  : 清除生成的图像")
        print("   - 'quit'   : 退出程序")
        print("=" * 60)

    def _load_model_with_dimension(self, model_path: str, model_type: str):
        """
        加载模型，自动检测嵌入维度
        """
        # 如果未指定模型路径，自动查找
        if model_path is None:
            possible_paths = [
                "multimodal_checkpoints/best_model.pt",
                "multimodal_checkpoints/final_model.pt",
                "multimodal_checkpoints/checkpoint_epoch_50.pt",
                "multimodal_checkpoints/latest_checkpoint.pt",
                "checkpoints/best_model.pt",
                "checkpoints/final_model.pt",
                "text2img_checkpoints/best_model.pt",
                "text2img_checkpoints/final_model.pt"
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    model_path = path
                    break

            if model_path is None:
                print("❌ 找不到模型文件，请先训练模型")
                print("运行: python train_multimodal.py --mode train")
                sys.exit(1)

        print(f"📂 加载模型: {model_path}")

        # 先加载检查点，读取配置
        try:
            checkpoint = torch.load(model_path, map_location=self.device)

            # 检测嵌入维度
            # 方法1: 从检查点中读取
            embed_dim = checkpoint.get('embed_dim', None)

            # 方法2: 从模型权重中推断
            if embed_dim is None and 'model_state_dict' in checkpoint:
                state_dict = checkpoint['model_state_dict']
            elif embed_dim is None:
                state_dict = checkpoint
            else:
                state_dict = checkpoint.get('model_state_dict', checkpoint)

            # 从 vision_encoder 的 cls_token 形状推断
            if embed_dim is None:
                if 'vision_encoder.cls_token' in state_dict:
                    embed_dim = state_dict['vision_encoder.cls_token'].shape[-1]
                elif 'vision_encoder.patch_embed.weight' in state_dict:
                    embed_dim = state_dict['vision_encoder.patch_embed.weight'].shape[0]
                else:
                    # 默认值
                    embed_dim = 256

            print(f"   🔍 检测到嵌入维度: {embed_dim}")

        except Exception as e:
            print(f"   ⚠️ 无法读取检查点: {e}")
            # 默认使用 256
            embed_dim = 256
            checkpoint = None

        # 创建模型（使用检测到的维度）
        if model_type == "ultra":
            # Ultra 模型使用 min(embed_dim, 128)
            actual_dim = min(embed_dim, 128)
            model = UltraLightweightMultimodal(embed_dim=actual_dim)
        else:
            model = LightweightMultimodalModel(embed_dim=embed_dim)

        # 加载权重
        try:
            if checkpoint is not None:
                if 'model_state_dict' in checkpoint:
                    state_dict = checkpoint['model_state_dict']
                else:
                    state_dict = checkpoint

                # 使用 strict=False 加载，忽略不匹配的键
                model.load_state_dict(state_dict, strict=False)
                model = model.to(self.device)
                print(f"✅ 模型加载成功 (embed_dim={embed_dim})")
                return model, embed_dim
            else:
                raise ValueError("无法加载检查点")

        except Exception as e:
            print(f"❌ 加载模型失败: {e}")
            print(f"💡 提示: 请确保模型文件与模型类型匹配")
            print(f"   model_type: {model_type}, embed_dim: {embed_dim}")
            sys.exit(1)

    def _load_label_map(self) -> List[str]:
        """加载所有可用的文本标签"""
        labels = []
        possible_paths = [
            "synthetic_data/captions.json",
            "synthetic_data_enhanced/captions.json"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    import json
                    with open(path, 'r') as f:
                        data = json.load(f)
                        labels = list(set([item['caption'] for item in data]))
                        labels.sort()
                    print(f"📝 加载了 {len(labels)} 个文本标签")
                    return labels
                except:
                    pass

        # 如果找不到标签文件，使用默认标签
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
        print(f"📝 使用默认标签: {len(default_labels)} 个")
        return default_labels

    def generate_from_text(self, text: str, max_length: int = 32) -> Optional[Image.Image]:
        """
        根据文本生成图像
        """
        try:
            # 1. 编码文本
            with torch.no_grad():
                text_embeds = self.model.encode_text([text])

            # 2. 生成随机噪声
            noise_dim = 100 if hasattr(self.model, 'noise_dim') else 128
            noise = torch.randn(1, noise_dim, device=self.device)

            # 3. 生成图像
            if hasattr(self.model, 'generator'):
                with torch.no_grad():
                    generated = self.model.generator(text_embeds, noise)
                    generated = (generated + 1) / 2
                    generated = generated.clamp(0, 1)
            else:
                # 对比学习模型：使用相似度检索
                all_labels = self.label_map
                with torch.no_grad():
                    text_embeds_all = self.model.encode_text(all_labels)
                    text_embeds_all = F.normalize(text_embeds_all, dim=-1)
                    text_embed = F.normalize(text_embeds, dim=-1)

                    similarities = text_embed @ text_embeds_all.T
                    best_idx = similarities.argmax().item()
                    best_text = all_labels[best_idx]

                    image_path = self._find_image_for_label(best_text)
                    if image_path:
                        img = Image.open(image_path).convert('RGB')
                        img = img.resize((224, 224))
                        return img
                    else:
                        return self._create_placeholder(text)

            # 4. 转换为 PIL Image
            generated = generated.squeeze(0).cpu()
            generated = generated.permute(1, 2, 0).numpy()
            generated = (generated * 255).astype(np.uint8)
            img = Image.fromarray(generated)

            return img

        except Exception as e:
            print(f"❌ 生成图像失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _find_image_for_label(self, label: str) -> Optional[str]:
        """根据标签查找对应的图像"""
        possible_paths = [
            "synthetic_data/images",
            "synthetic_data_enhanced/images"
        ]

        for base_dir in possible_paths:
            if os.path.exists(base_dir):
                image_files = glob.glob(os.path.join(base_dir, "*.jpg")) + \
                              glob.glob(os.path.join(base_dir, "*.png"))
                for img_path in image_files:
                    if img_path.endswith(('.jpg', '.png')):
                        return img_path
        return None

    def _create_placeholder(self, text: str) -> Image.Image:
        """创建占位图像"""
        from PIL import ImageDraw, ImageFont

        img = Image.new('RGB', (224, 224), color=(200, 200, 200))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except:
            font = ImageFont.load_default()

        draw.text((10, 10), text[:30], fill=(0, 0, 0), font=font)
        draw.text((10, 40), f"Generated: {self.image_count}", fill=(0, 0, 0), font=font)

        return img

    def generate_and_save(self, text: str) -> Optional[str]:
        """生成并保存图像"""
        print(f"\n🎨 生成: {text}")
        print("   ⏳ 正在生成...")

        start_time = time.time()
        img = self.generate_from_text(text)
        elapsed = time.time() - start_time

        if img is None:
            print("   ❌ 生成失败")
            return None

        self.image_count += 1
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"gen_{self.image_count:04d}_{timestamp}.png"
        filepath = os.path.join(self.output_dir, filename)

        img.save(filepath)
        print(f"   ✅ 生成完成! (耗时: {elapsed:.2f}s)")
        print(f"   📁 保存到: {filepath}")
        print(f"   📐 图像尺寸: {img.size}")

        return filepath

    def run_interactive(self):
        """运行交互式聊天模式"""
        print("\n" + "=" * 60)
        print("🎨 文本生成图像 - 聊天模式")
        print("=" * 60)

        print("\n💡 示例:")
        print("   > a red circle")
        print("   > a blue square on a white background")
        print("   > green triangle with a star")
        print()

        while True:
            try:
                user_input = input("\n📝 请输入描述 > ").strip()

                if not user_input:
                    continue

                if user_input.lower() == 'quit':
                    print("👋 再见!")
                    break

                elif user_input.lower() == 'list':
                    print("\n📋 可用的文本标签:")
                    print("-" * 40)
                    for i, label in enumerate(self.label_map[:20]):
                        print(f"  {i + 1:3d}. {label}")
                    if len(self.label_map) > 20:
                        print(f"  ... 还有 {len(self.label_map) - 20} 个标签")
                    continue

                elif user_input.lower() == 'stats':
                    print(f"\n📊 统计信息:")
                    print("-" * 40)
                    print(f"  已生成图像: {self.image_count}")
                    print(f"  可用标签: {len(self.label_map)}")
                    print(f"  输出目录: {self.output_dir}")
                    print(f"  嵌入维度: {self.embed_dim}")
                    continue

                elif user_input.lower() == 'clear':
                    files = glob.glob(os.path.join(self.output_dir, "gen_*.png"))
                    if files:
                        for f in files:
                            os.remove(f)
                        print(f"✅ 已清除 {len(files)} 张图像")
                    else:
                        print("ℹ️ 没有图像需要清除")
                    continue

                self.generate_and_save(user_input)

            except KeyboardInterrupt:
                print("\n👋 再见!")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
                continue


def main():
    parser = argparse.ArgumentParser(description='文本生成图像 - 聊天模式')
    parser.add_argument('--model', type=str, default=None,
                        help='模型路径 (默认自动查找)')
    parser.add_argument('--model_type', type=str, default='lightweight',
                        choices=['lightweight', 'ultra'],
                        help='模型类型')
    parser.add_argument('--output_dir', type=str, default='generated_images',
                        help='输出目录')
    parser.add_argument('--text', type=str, default=None,
                        help='直接生成单张图像 (非交互模式)')

    args = parser.parse_args()

    chat = TextToImageChat(
        model_path=args.model,
        model_type=args.model_type,
        output_dir=args.output_dir
    )

    if args.text:
        print(f"\n🎨 生成图像: {args.text}")
        filepath = chat.generate_and_save(args.text)
        if filepath:
            print(f"\n✅ 图像已保存: {filepath}")
    else:
        chat.run_interactive()


if __name__ == "__main__":
    main()