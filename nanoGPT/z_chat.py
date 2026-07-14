# z_chat.py
import torch
import pickle
from types import SimpleNamespace
from model import GPT

out_dir = 'out-qa'
# out_dir = 'out-law'

meta_path = '/Users/lix/PycharmProjects/nanoGPT/data/unified/meta.pkl'

device = 'mps'

# 加载检查点
checkpoint = torch.load(f'{out_dir}/ckpt.pt', map_location=device)
config_dict = checkpoint['model_args']
config = SimpleNamespace(**config_dict)

# 加载字符映射
with open(meta_path, 'rb') as f:
    meta = pickle.load(f)
    stoi = meta['stoi']
    itos = meta['itos']


def encode(s):
    return [stoi.get(c, 0) for c in s]


def decode(idx_list):
    return ''.join([itos[i] for i in idx_list])


# 创建模型并加载权重
model = GPT(config)
model.load_state_dict(checkpoint['model'])
model.to(device)
model.eval()

print(f"📊 模型: {out_dir}")
print(f"📊 词汇表: {config.vocab_size}")
print(f"📊 训练步数: {checkpoint.get('iter_num', 'N/A')}")
print("=" * 50)


def chat_response(prompt, max_new_tokens=200, temperature=0.3, top_k=150, top_p=0.9):
    start_ids = encode(prompt)
    if not start_ids:
        start_ids = [0]

    x = torch.tensor(start_ids, dtype=torch.long, device=device).unsqueeze(0)

    with torch.no_grad():
        y = model.generate(x, max_new_tokens, temperature=temperature, top_k=top_k, top_p=top_p)

    full_text = decode(y[0].tolist())
    response = full_text[len(prompt):]

    # ============ 关键修复：截断多余内容 ============
    # 截断 <|endoftext|>
    if '<|endoftext|>' in response:
        response = response.split('<|endoftext|>')[0]

    # 截断 User: (防止模型继续对话)
    if '\nUser:' in response:
        response = response.split('\nUser:')[0]

    # 截断 Assistant: (防止重复)
    if '\nAssistant:' in response:
        response = response.split('\nAssistant:')[0]

    # 在换行处截断（如果有多行）
    if '\n' in response and response.count('\n') > 1:
        response = response.split('\n')[0]

    return response.strip()


print("💬 对话模式 (输入 'quit' 退出)")
print("=" * 50)

while True:
    user_input = input("\nYou: ")
    if user_input.lower() in ['quit', 'exit', 'q']:
        print("再见！👋")
        break

    # 正确构造 prompt
    prompt = f"User: {user_input}\nAssistant: "
    response = chat_response(prompt, max_new_tokens=150, temperature=0.6, top_k=50)

    if not response:
        print("AI: 抱歉，我无法回答这个问题。")
    else:
        print(f"AI: {response}")