# """
# 简化版文本编码器 - 不依赖外部模型
# 使用随机初始化的 Embedding + Transformer
# """
#
# import torch
# import torch.nn as nn
# import torch.nn.functional as F
# from typing import List
# import math
#
#
# class SimpleTextEncoder(nn.Module):
#     """
#     简化版文本编码器 - 从头训练
#     完全不依赖预训练模型
#     """
#
#     def __init__(self,
#                  vocab_size: int = 30522,  # BERT 词汇表大小
#                  embed_dim: int = 256,
#                  max_length: int = 64,
#                  num_heads: int = 4,
#                  num_layers: int = 4):
#         super().__init__()
#
#         self.max_length = max_length
#         self.embed_dim = embed_dim
#
#         # 词嵌入
#         self.token_embed = nn.Embedding(vocab_size, embed_dim)
#         self.position_embed = nn.Parameter(torch.randn(1, max_length, embed_dim) * 0.02)
#
#         # Transformer 编码器
#         self.layers = nn.ModuleList([
#             TransformerBlockSimple(embed_dim, num_heads)
#             for _ in range(num_layers)
#         ])
#
#         self.norm = nn.LayerNorm(embed_dim)
#
#         # 简单的 tokenizer (只支持英文小写)
#         self.vocab = self._build_vocab()
#
#         print(f"   ✅ 简化版文本编码器初始化完成 (参数量: {sum(p.numel() for p in self.parameters()):,})")
#
#     def _build_vocab(self):
#         """构建简单词汇表"""
#         # 基础词汇
#         chars = "abcdefghijklmnopqrstuvwxyz0123456789 .,!?"
#         vocab = {char: i + 1 for i, char in enumerate(chars)}
#         vocab['<PAD>'] = 0
#         vocab['<UNK>'] = len(vocab)
#         return vocab
#
#     def tokenize(self, texts: List[str], max_length: int = None) -> torch.Tensor:
#         """简单分词"""
#         if max_length is None:
#             max_length = self.max_length
#
#         batch_size = len(texts)
#         tokens = torch.zeros(batch_size, max_length, dtype=torch.long)
#
#         for i, text in enumerate(texts):
#             text = text.lower()
#             for j, char in enumerate(text[:max_length]):
#                 if char in self.vocab:
#                     tokens[i, j] = self.vocab[char]
#                 else:
#                     tokens[i, j] = self.vocab['<UNK>']
#
#         return tokens
#
#     def forward(self, texts: List[str], max_length: int = None):
#         if max_length is None:
#             max_length = self.max_length
#
#         # Tokenize
#         tokens = self.tokenize(texts, max_length)
#         device = next(self.parameters()).device
#         tokens = tokens.to(device)
#
#         # Embedding
#         x = self.token_embed(tokens)  # (B, L, D)
#         x = x + self.position_embed[:, :max_length, :]
#
#         # Transformer
#         for layer in self.layers:
#             x = layer(x)
#
#         x = self.norm(x)
#
#         # 使用平均池化
#         return x.mean(dim=1)  # (B, D)
#
#
# class TransformerBlockSimple(nn.Module):
#     """简单的 Transformer Block"""
#
#     def __init__(self, dim: int, num_heads: int):
#         super().__init__()
#         self.norm1 = nn.LayerNorm(dim)
#         self.attn = nn.MultiheadAttention(dim, num_heads, batch_first=True)
#         self.norm2 = nn.LayerNorm(dim)
#         self.ffn = nn.Sequential(
#             nn.Linear(dim, dim * 4),
#             nn.GELU(),
#             nn.Linear(dim * 4, dim)
#         )
#
#     def forward(self, x):
#         x = x + self.attn(self.norm1(x), self.norm1(x), self.norm1(x))[0]
#         x = x + self.ffn(self.norm2(x))
#         return x

"""
轻量级多模态模型 - 完全本地版本
不依赖预训练模型下载
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Tuple, Optional
import numpy as np


class VisionEncoder(nn.Module):
    """简单但有效的视觉编码器"""

    def __init__(self, embed_dim: int = 256):
        super().__init__()

        # 使用轻量级 CNN
        self.conv_layers = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),

            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),

            nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),

            nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),

            nn.AdaptiveAvgPool2d((1, 1))
        )

        self.proj = nn.Linear(256, embed_dim)

    def forward(self, x):
        x = self.conv_layers(x)
        x = x.view(x.size(0), -1)
        x = self.proj(x)
        return F.normalize(x, dim=-1)


class SimpleTextEncoder(nn.Module):
    """简化版文本编码器 - 使用 LSTM"""

    def __init__(self, embed_dim: int = 256, vocab_size: int = 1000, max_length: int = 32):
        super().__init__()

        self.max_length = max_length
        self.embed_dim = embed_dim

        # 词嵌入
        self.embedding = nn.Embedding(vocab_size, embed_dim)
        self.lstm = nn.LSTM(embed_dim, embed_dim, num_layers=2, batch_first=True, bidirectional=True)
        self.proj = nn.Linear(embed_dim * 2, embed_dim)

        # 简单词汇表
        self._build_vocab()

    def _build_vocab(self):
        """构建词汇表"""
        self.vocab = {}
        self.vocab['<PAD>'] = 0
        self.vocab['<UNK>'] = 1

        # 常用词
        words = [
            'a', 'an', 'the', 'red', 'blue', 'green', 'yellow', 'purple', 'orange',
            'circle', 'square', 'triangle', 'star', 'diamond', 'heart', 'hexagon',
            'on', 'in', 'at', 'with', 'color', 'shape', 'background'
        ]

        for i, word in enumerate(words, start=2):
            self.vocab[word] = i

        self.vocab_size = len(self.vocab)
        print(f"   📝 词汇表大小: {len(self.vocab)}")

    def tokenize(self, texts: List[str]) -> torch.Tensor:
        """简单分词"""
        batch_size = len(texts)
        tokens = torch.zeros(batch_size, self.max_length, dtype=torch.long)

        for i, text in enumerate(texts):
            words = text.lower().split()
            for j, word in enumerate(words[:self.max_length]):
                tokens[i, j] = self.vocab.get(word, self.vocab['<UNK>'])

        return tokens

    def forward(self, texts: List[str]):
        tokens = self.tokenize(texts)
        device = next(self.parameters()).device
        tokens = tokens.to(device)

        # 词嵌入
        x = self.embedding(tokens)  # (B, L, D)

        # LSTM
        lstm_out, _ = self.lstm(x)  # (B, L, D*2)

        # 使用最后一个时间步
        x = lstm_out[:, -1, :]  # (B, D*2)

        # 投影
        x = self.proj(x)  # (B, D)

        return F.normalize(x, dim=-1)


class LightweightMultimodal(nn.Module):
    """完全本地的轻量级多模态模型"""

    def __init__(self, embed_dim: int = 256):
        super().__init__()

        self.embed_dim = embed_dim

        # 视觉编码器
        self.vision_encoder = VisionEncoder(embed_dim)

        # 文本编码器
        self.text_encoder = SimpleTextEncoder(embed_dim)

        # 温度参数
        self.log_temperature = nn.Parameter(torch.ones(1) * np.log(1.0 / 0.07))

        total_params = sum(p.numel() for p in self.parameters())
        print(f"\n✅ 本地轻量级多模态模型初始化完成")
        print(f"   - 嵌入维度: {embed_dim}")
        print(f"   - 总参数量: {total_params:,}")

    def encode_image(self, images: torch.Tensor) -> torch.Tensor:
        return self.vision_encoder(images)

    def encode_text(self, texts: List[str]) -> torch.Tensor:
        return self.text_encoder(texts)

    def forward_contrastive(self, images: torch.Tensor, texts: List[str]) -> torch.Tensor:
        image_embeds = self.encode_image(images)
        text_embeds = self.encode_text(texts)

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
            'embed_dim': self.embed_dim
        }, path)
        print(f"✅ 模型已保存到: {path}")

    def load(self, path: str):
        checkpoint = torch.load(path, map_location='cpu')
        self.load_state_dict(checkpoint['model_state_dict'])
        print(f"✅ 模型已从 {path} 加载")