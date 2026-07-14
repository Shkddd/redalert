"""
轻量级多模态模型 - 支持本地缓存
"""

import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer
from typing import Optional, List, Tuple, Dict
import numpy as np
import math

# ============ 设置 Hugging Face 缓存目录 ============
# 设置环境变量，让模型下载到本地
os.environ['HF_HOME'] = os.path.expanduser('~/.cache/huggingface')
os.environ['TRANSFORMERS_CACHE'] = os.path.expanduser('~/.cache/huggingface/transformers')
os.environ['HF_DATASETS_CACHE'] = os.path.expanduser('~/.cache/huggingface/datasets')

# 创建缓存目录
os.makedirs(os.environ['TRANSFORMERS_CACHE'], exist_ok=True)
os.makedirs(os.environ['HF_HOME'], exist_ok=True)

print(f"📁 HuggingFace 缓存目录: {os.environ['TRANSFORMERS_CACHE']}")


class LightweightViT(nn.Module):
    """轻量级 Vision Transformer"""

    def __init__(self,
                 image_size: int = 224,
                 patch_size: int = 16,
                 embed_dim: int = 256,
                 num_heads: int = 4,
                 num_layers: int = 6,
                 mlp_ratio: float = 2.0,
                 dropout: float = 0.1):
        super().__init__()

        num_patches = (image_size // patch_size) ** 2
        patch_dim = 3 * patch_size * patch_size

        self.patch_embed = nn.Conv2d(3, embed_dim, kernel_size=patch_size, stride=patch_size)
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim))
        self.pos_embed = nn.Parameter(torch.randn(1, num_patches + 1, embed_dim))
        self.dropout = nn.Dropout(dropout)

        self.layers = nn.ModuleList([
            TransformerBlock(embed_dim, num_heads, mlp_ratio, dropout)
            for _ in range(num_layers)
        ])

        self.norm = nn.LayerNorm(embed_dim)

        nn.init.trunc_normal_(self.pos_embed, std=0.02)
        nn.init.trunc_normal_(self.cls_token, std=0.02)
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.trunc_normal_(m.weight, std=0.02)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.LayerNorm):
                nn.init.constant_(m.bias, 0)
                nn.init.constant_(m.weight, 1.0)

    def forward(self, x):
        B = x.shape[0]

        x = self.patch_embed(x)
        x = x.flatten(2).transpose(1, 2)

        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat([cls_tokens, x], dim=1)
        x = x + self.pos_embed
        x = self.dropout(x)

        for layer in self.layers:
            x = layer(x)

        x = self.norm(x)

        return x[:, 0, :], x[:, 1:, :]


class TransformerBlock(nn.Module):
    """Transformer Block"""

    def __init__(self, dim, num_heads, mlp_ratio=2.0, dropout=0.1):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, num_heads, dropout=dropout, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = nn.Sequential(
            nn.Linear(dim, int(dim * mlp_ratio)),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(int(dim * mlp_ratio), dim),
            nn.Dropout(dropout)
        )

    def forward(self, x):
        x = x + self.attn(self.norm1(x), self.norm1(x), self.norm1(x))[0]
        x = x + self.mlp(self.norm2(x))
        return x


class LightweightTextEncoder(nn.Module):
    """轻量级文本编码器 - 支持本地缓存"""

    def __init__(self,
                 model_name: str = "distilbert-base-uncased",
                 embed_dim: int = 256,
                 max_length: int = 64,
                 freeze_layers: int = 4):
        super().__init__()

        self.model_name = model_name
        self.max_length = max_length
        self.tokenizer = None
        self.bert = None

        # 尝试加载模型（使用本地缓存）
        self._load_model_with_cache(model_name)

        hidden_size = self.bert.config.hidden_size
        self.proj = nn.Linear(hidden_size, embed_dim)

        if freeze_layers > 0:
            self._freeze_layers(freeze_layers)

        print(f"   ✅ 文本编码器加载完成: {model_name}")
        print(f"   📁 缓存位置: {os.environ['TRANSFORMERS_CACHE']}")

    def _load_model_with_cache(self, model_name: str):
        """使用本地缓存加载模型"""
        try:
            # 设置离线模式，优先使用本地缓存
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=os.environ['TRANSFORMERS_CACHE'],
                local_files_only=False  # 如果本地没有则下载
            )
            self.bert = AutoModel.from_pretrained(
                model_name,
                cache_dir=os.environ['TRANSFORMERS_CACHE'],
                local_files_only=False
            )
            print(f"   📥 模型已加载 (缓存: {os.environ['TRANSFORMERS_CACHE']})")
        except Exception as e:
            print(f"   ⚠️ 加载失败: {e}")
            # 尝试仅使用本地文件
            try:
                print("   🔄 尝试仅使用本地缓存...")
                self.tokenizer = AutoTokenizer.from_pretrained(
                    model_name,
                    cache_dir=os.environ['TRANSFORMERS_CACHE'],
                    local_files_only=True
                )
                self.bert = AutoModel.from_pretrained(
                    model_name,
                    cache_dir=os.environ['TRANSFORMERS_CACHE'],
                    local_files_only=True
                )
                print("   ✅ 从本地缓存加载成功")
            except Exception as e2:
                print(f"   ❌ 本地缓存加载失败: {e2}")
                raise RuntimeError(f"无法加载模型 {model_name}")

    def _freeze_layers(self, num_layers: int):
        """冻结前几层"""
        if hasattr(self.bert, 'encoder'):
            if hasattr(self.bert.encoder, 'layer'):
                layers = self.bert.encoder.layer
                for i, layer in enumerate(layers):
                    if i < num_layers:
                        for param in layer.parameters():
                            param.requires_grad = False
                print(f"   ❄️ 冻结了前 {num_layers} 层")

    def forward(self, texts: List[str], max_length: int = None):
        if max_length is None:
            max_length = self.max_length

        tokens = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors='pt'
        )

        device = next(self.parameters()).device
        input_ids = tokens['input_ids'].to(device)
        attention_mask = tokens['attention_mask'].to(device)

        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_embed = outputs.last_hidden_state[:, 0, :]
        return self.proj(cls_embed)


class CrossModalFusion(nn.Module):
    """跨模态融合"""

    def __init__(self, embed_dim: int = 256, num_heads: int = 4):
        super().__init__()

        self.cross_attn = nn.MultiheadAttention(
            embed_dim, num_heads, batch_first=True
        )

        self.ffn = nn.Sequential(
            nn.Linear(embed_dim, embed_dim * 2),
            nn.GELU(),
            nn.Linear(embed_dim * 2, embed_dim)
        )

        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)

    def forward(self, image_features, text_features):
        if image_features.dim() == 2:
            image_features = image_features.unsqueeze(1)
        if text_features.dim() == 2:
            text_features = text_features.unsqueeze(1)

        attn_out = self.cross_attn(
            image_features, text_features, text_features
        )[0]

        x = self.norm1(image_features + attn_out)
        x = self.norm2(x + self.ffn(x))

        return x.mean(dim=1)


class LightweightMultimodalModel(nn.Module):
    """轻量级多模态模型"""

    def __init__(self,
                 embed_dim: int = 256,
                 image_size: int = 224,
                 vision_layers: int = 6,
                 vision_heads: int = 4,
                 text_model: str = "distilbert-base-uncased",
                 text_max_length: int = 64,
                 fusion_heads: int = 4,
                 temperature: float = 0.07):
        super().__init__()

        self.embed_dim = embed_dim

        self.vision_encoder = LightweightViT(
            image_size=image_size,
            embed_dim=embed_dim,
            num_heads=vision_heads,
            num_layers=vision_layers
        )

        self.text_encoder = LightweightTextEncoder(
            model_name=text_model,
            embed_dim=embed_dim,
            max_length=text_max_length
        )

        self.fusion = CrossModalFusion(embed_dim, fusion_heads)

        self.log_temperature = nn.Parameter(
            torch.ones(1) * np.log(1.0 / temperature)
        )

        self.output_proj = nn.Sequential(
            nn.Linear(embed_dim, embed_dim * 2),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(embed_dim * 2, embed_dim)
        )

        print(f"✅ 轻量级多模态模型初始化完成")
        print(f"   - 嵌入维度: {embed_dim}")
        print(f"   - 视觉编码器: LightweightViT (layers={vision_layers})")
        print(f"   - 文本编码器: {text_model}")
        print(f"   - 总参数量: {sum(p.numel() for p in self.parameters()):,}")

    def encode_image(self, images: torch.Tensor) -> torch.Tensor:
        cls_token, _ = self.vision_encoder(images)
        return cls_token

    def encode_text(self, texts: List[str]) -> torch.Tensor:
        return self.text_encoder(texts)

    def forward_contrastive(self, images: torch.Tensor, texts: List[str]) -> torch.Tensor:
        image_embeds = self.encode_image(images)
        text_embeds = self.encode_text(texts)

        image_embeds = F.normalize(image_embeds, dim=-1)
        text_embeds = F.normalize(text_embeds, dim=-1)

        logits = image_embeds @ text_embeds.T
        temperature = self.log_temperature.exp()
        logits = logits / temperature

        return logits

    def forward_with_loss(self, images: torch.Tensor, texts: List[str]) -> Tuple[torch.Tensor, torch.Tensor]:
        logits = self.forward_contrastive(images, texts)

        batch_size = logits.shape[0]
        device = logits.device
        labels = torch.arange(batch_size, device=device)

        loss_i2t = F.cross_entropy(logits, labels)
        loss_t2i = F.cross_entropy(logits.T, labels)
        loss = (loss_i2t + loss_t2i) / 2

        return logits, loss

    def compute_similarity(self, images: torch.Tensor, texts: List[str]) -> torch.Tensor:
        with torch.no_grad():
            image_embeds = self.encode_image(images)
            text_embeds = self.encode_text(texts)

            image_embeds = F.normalize(image_embeds, dim=-1)
            text_embeds = F.normalize(text_embeds, dim=-1)

            similarity = image_embeds @ text_embeds.T

        return similarity

    def get_temperature(self) -> float:
        return self.log_temperature.exp().item()

    def save(self, path: str):
        torch.save({
            'model_state_dict': self.state_dict(),
            'embed_dim': self.embed_dim,
            'log_temperature': self.log_temperature.item()
        }, path)
        print(f"✅ 模型已保存到: {path}")

    def load(self, path: str):
        checkpoint = torch.load(path, map_location='cpu')
        self.load_state_dict(checkpoint['model_state_dict'])
        print(f"✅ 模型已从 {path} 加载")


class UltraLightweightMultimodal(nn.Module):
    """超轻量级版本"""

    def __init__(self,
                 embed_dim: int = 128,
                 image_size: int = 224,
                 vision_layers: int = 4,
                 vision_heads: int = 2,
                 text_model: str = "distilbert-base-uncased",
                 text_max_length: int = 64):
        super().__init__()

        self.embed_dim = embed_dim

        self.vision_encoder = LightweightViT(
            image_size=image_size,
            embed_dim=embed_dim,
            num_heads=vision_heads,
            num_layers=vision_layers
        )

        self.text_encoder = LightweightTextEncoder(
            model_name=text_model,
            embed_dim=embed_dim,
            max_length=text_max_length,
            freeze_layers=4
        )

        self.log_temperature = nn.Parameter(
            torch.ones(1) * np.log(1.0 / 0.07)
        )

        print(f"✅ 超轻量级多模态模型初始化完成")
        print(f"   - 嵌入维度: {embed_dim}")
        print(f"   - 总参数量: {sum(p.numel() for p in self.parameters()):,}")

    def encode_image(self, images: torch.Tensor) -> torch.Tensor:
        cls_token, _ = self.vision_encoder(images)
        return cls_token

    def encode_text(self, texts: List[str]) -> torch.Tensor:
        return self.text_encoder(texts)

    def forward_contrastive(self, images: torch.Tensor, texts: List[str]) -> torch.Tensor:
        image_embeds = self.encode_image(images)
        text_embeds = self.encode_text(texts)

        image_embeds = F.normalize(image_embeds, dim=-1)
        text_embeds = F.normalize(text_embeds, dim=-1)

        logits = image_embeds @ text_embeds.T
        logits = logits / self.log_temperature.exp()

        return logits

    def forward_with_loss(self, images: torch.Tensor, texts: List[str]) -> Tuple[torch.Tensor, torch.Tensor]:
        logits = self.forward_contrastive(images, texts)

        batch_size = logits.shape[0]
        device = logits.device
        labels = torch.arange(batch_size, device=device)

        loss_i2t = F.cross_entropy(logits, labels)
        loss_t2i = F.cross_entropy(logits.T, labels)
        loss = (loss_i2t + loss_t2i) / 2

        return logits, loss

    def get_temperature(self) -> float:
        return self.log_temperature.exp().item()

    def save(self, path: str):
        torch.save({
            'model_state_dict': self.state_dict(),
            'embed_dim': self.embed_dim,
            'log_temperature': self.log_temperature.item()
        }, path)
        print(f"✅ 模型已保存到: {path}")

    def load(self, path: str):
        checkpoint = torch.load(path, map_location='cpu')
        self.load_state_dict(checkpoint['model_state_dict'])
        print(f"✅ 模型已从 {path} 加载")