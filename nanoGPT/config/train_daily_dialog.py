# config/train_daily_dialog.py
"""
训练配置：在 DailyDialog 上微调
"""
init_from="resume"
# 数据集
dataset = "daily_dialog"  # 自定义数据集名称
data_dir = "../data"  # 数据目录
train_file = "data/daily_dialog_train.txt"  # 训练数据

# 模型结构（与你现有的莎士比亚模型相同）
n_layer = 6
n_head = 6
n_embd = 384
dropout = 0.2
bias = False
block_size = 256

# 训练参数
batch_size = 32  # 可以调小一些，因为新数据格式不同
gradient_accumulation_steps = 1
max_iters = 3000  # 微调不需要太多步数
learning_rate = 5e-5  # 比从头训练低，防止遗忘莎士比亚
decay_lr = True
warmup_iters = 100
lr_decay_iters = 3000
min_lr = 5e-6

# 评估
eval_interval = 100
eval_iters = 50

# 输出
out_dir = "out-daily-dialog"
wandb_log = False  # 如果不想用 wandb
always_save_checkpoint = True