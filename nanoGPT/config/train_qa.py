# config/train_qa.py
"""
训练 QA 对话模型 - 基于问答数据集
"""

# ============ 数据集配置 ============
dataset = "qa_unified"
data_dir = "data/qa_unified"

init_from = "resume"  # resume: 从检查点继续训练

# ============ 模型结构 ============
n_layer = 12          # Transformer 层数
n_head = 12           # 注意力头数
n_embd = 768         # 嵌入维度
dropout = 0        # Dropout 比率
bias = False         # 是否使用偏置
block_size = 512     # 上下文长度 (最大 256 个字符)

# ============ 训练参数 ============
batch_size = 16              # 每批次样本数
gradient_accumulation_steps = 2  # 梯度累积步数
max_iters = 6000             # 最大训练步数
learning_rate = 3e-4         # 学习率
decay_lr = True              # 是否衰减学习率
warmup_iters = 100           # 预热步数
lr_decay_iters = 3000        # 学习率衰减步数
min_lr = 1e-5                # 最小学习率

# ============ 优化器参数 ============
beta1 = 0.9                  # AdamW beta1 (动量)
beta2 = 0.999                # AdamW beta2 (自适应)
weight_decay = 0.1           # 权重衰减
grad_clip = 1.0              # 梯度裁剪

# ============ 评估配置 ============
eval_interval = 100          # 每 100 步评估一次
eval_iters = 50              # 评估时使用的迭代次数
log_interval = 10            # 每 10 步打印一次日志

# ============ 输出配置 ============
in_dir = "out-qa"           # 模型保存目录
out_dir = "out-qa"           # 模型保存目录
wandb_log = False            # 不使用 wandb
always_save_checkpoint = True  # 总是保存检查点

# ============ 设备配置 ============
device = 'mps'               # 使用 MPS (Mac GPU)
compile = False              # 不编译 (MPS 不支持 torch.compile)
