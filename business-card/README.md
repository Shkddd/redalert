# 水墨名片生成器

生成中式水墨风格 SVG 名片，可直接预览或转 PNG。

## 用法

```bash
# 交互式
python3 card.py

# 直接传参
python3 card.py "张三" "产品经理" "138-0000-0000"
```

输出到桌面：`~/Desktop/名片_<姓名>.svg`

## 转 PNG（可选）

```bash
qlmanage -t -s 900 -o ~/Desktop ~/Desktop/名片_张三.svg
```

## 设计元素

- 宣纸底色渐变
- 三层远山（随机高度）
- 松枝剪影
- 红色印章
- 居中姓名 + 职位 + 联系方式
