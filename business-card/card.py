#!/usr/bin/env python3
"""
水墨名片生成器 - 输出 SVG 名片
输入：姓名、职位、联系方式
输出：水墨风格横版 SVG
"""
import sys, os

def make_card(name, title, contact, output_path):
    # 水墨背景随机元素
    import random
    rng = random.Random(hash(name))

    # 远山
    m1 = rng.randint(20, 80)
    m2 = rng.randint(30, 100)
    m3 = rng.randint(10, 50)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 500" width="900" height="500">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f5f1e8"/>
      <stop offset="100%" stop-color="#e8e0d0"/>
    </linearGradient>
    <radialGradient id="sun" cx="0.85" cy="0.2" r="0.15">
      <stop offset="0%" stop-color="#c97b63" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="#c97b63" stop-opacity="0"/>
    </radialGradient>
    <filter id="blur">
      <feGaussianBlur stdDeviation="3"/>
    </filter>
  </defs>

  <!-- 背景 -->
  <rect width="900" height="500" fill="url(#bg)"/>
  <rect width="900" height="500" fill="url(#sun)"/>

  <!-- 远山三层 -->
  <path d="M0 {200+m1} Q150 {120+m1} 300 {180+m1} T600 {160+m1} T900 {200+m1} L900 500 L0 500 Z" fill="#2d2d44" opacity="0.15"/>
  <path d="M0 {250+m2} Q200 {180+m2} 400 {240+m2} T800 {220+m2} T900 {260+m2} L900 500 L0 500 Z" fill="#2d2d44" opacity="0.25"/>
  <path d="M0 {300+m3} Q250 {240+m3} 500 {290+m3} T900 {280+m3} L900 500 L0 500 Z" fill="#1a1a2e" opacity="0.35"/>

  <!-- 松枝 -->
  <g fill="#0f0f1f" opacity="0.6">
    <path d="M80 150 L70 220 L90 220 Z"/>
    <path d="M70 140 L55 210 L95 210 Z"/>
    <rect x="75" y="210" width="10" height="30"/>
  </g>

  <!-- 印章（红色方块） -->
  <rect x="780" y="350" width="60" height="60" fill="#b33a3a" opacity="0.85" rx="3"/>
  <text x="810" y="390" font-family="serif" font-size="28" fill="#f5f1e8" text-anchor="middle" font-weight="bold">印</text>

  <!-- 姓名 -->
  <text x="450" y="220" font-family="serif" font-size="72" fill="#1a1a2e" text-anchor="middle" font-weight="bold" letter-spacing="10">{name}</text>

  <!-- 职位 -->
  <text x="450" y="280" font-family="serif" font-size="28" fill="#3d3d55" text-anchor="middle">{title}</text>

  <!-- 分隔线 -->
  <line x1="350" y1="310" x2="550" y2="310" stroke="#3d3d55" stroke-width="1" opacity="0.5"/>

  <!-- 联系方式 -->
  <text x="450" y="360" font-family="serif" font-size="22" fill="#3d3d55" text-anchor="middle">{contact}</text>

  <!-- 底部小字 -->
  <text x="450" y="460" font-family="serif" font-size="14" fill="#666" text-anchor="middle" opacity="0.6">青云 · 水墨名片</text>
</svg>
'''
    with open(output_path, "w") as f:
        f.write(svg)
    print(f"✅ 名片已生成: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        name = input("姓名: ").strip()
        title = input("职位: ").strip()
        contact = input("联系方式: ").strip()
    else:
        name = sys.argv[1]
        title = sys.argv[2]
        contact = sys.argv[3]

    output = os.path.expanduser(f"~/Desktop/名片_{name}.svg")
    make_card(name, title, contact, output)
