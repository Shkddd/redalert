# config/train_unified_sft.py
"""
使用统一词汇表的 SFT 配置
"""
init_from="resume"
# 数据集
dataset = "daily_dialog_unified"
data_dir = "data/daily_dialog_unified"

# 模型结构 (与莎士比亚模型完全一致)
n_layer = 6
n_head = 6
n_embd = 384
dropout = 0.2
bias = False
block_size = 256

# 微调参数
batch_size = 32
gradient_accumulation_steps = 1
max_iters = 2000
learning_rate = 5e-5  # 小学习率，防止灾难性遗忘
decay_lr = True
warmup_iters = 50
lr_decay_iters = 2000
min_lr = 1e-6

# 评估
eval_interval = 100
eval_iters = 50

# 输出
out_dir = "out-shakespeare-sft-unified"
wandb_log = False
always_save_checkpoint = True