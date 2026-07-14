# config/train_law.py
"""
训练法律问答模型
"""

# ============ 初始化模式 ============
init_from = "resume"  # 从检查点继续训练

# ============ 数据集配置 ============
dataset = "law_unified"
data_dir = "data/law_unified"

# ============ 模型结构 ============
n_layer = 6          # Transformer 层数
n_head = 6           # 注意力头数
n_embd = 384         # 嵌入维度
dropout = 0.2        # Dropout 比率
bias = False         # 是否使用偏置
block_size = 256     # 上下文长度

# ============ 训练参数 ============
batch_size = 32
gradient_accumulation_steps = 1
max_iters = 3000
learning_rate = 3e-4
decay_lr = True
warmup_iters = 100
lr_decay_iters = 3000
min_lr = 1e-5

# ============ 优化器参数 ============
beta1 = 0.9
beta2 = 0.999
weight_decay = 0.1
grad_clip = 1.0

# ============ 评估配置 ============
eval_interval = 100
eval_iters = 50
log_interval = 10

# ============ 输出配置 ============
in_dir = "out-qa"
out_dir = "out-law"
wandb_log = False
always_save_checkpoint = True

# ============ 设备配置 ============
device = 'mps'
compile = False