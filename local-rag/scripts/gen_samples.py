"""生成测试样本: PDF + Excel + Word + TXT + 图片(模拟多格式摄入)"""
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from openpyxl import Workbook


OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)


# 注册中文字体
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
ZH_FONT = "STSong-Light"


def make_pdf(filename: str, pages_text: list) -> Path:
    p = OUT / filename
    c = canvas.Canvas(str(p), pagesize=A4)
    width, height = A4
    for text in pages_text:
        c.setFont(ZH_FONT, 11)
        y = height - 60
        for line in text.split("\n"):
            c.drawString(60, y, line.strip())
            y -= 18
        c.showPage()
    c.save()
    return p


def make_pdf_with_image(filename: str, title: str, body_lines: list,
                         chart_caption: str = "销售趋势图") -> Path:
    """带嵌入图的 PDF - 用 reportlab 画一个简单柱状图占位"""
    p = OUT / filename
    c = canvas.Canvas(str(p), pagesize=A4)
    width, height = A4

    # 第一页:文本
    c.setFont(ZH_FONT, 14)
    c.drawString(60, height - 60, title)
    c.setFont(ZH_FONT, 11)
    y = height - 100
    for line in body_lines:
        for sub in line.split("\n"):
            c.drawString(60, y, sub.strip())
            y -= 18
        y -= 6
    c.showPage()

    # 第二页:画一张图(柱状图)
    c.setFont(ZH_FONT, 12)
    c.drawString(60, height - 60, chart_caption)
    ax_x = 100
    ax_y = 150
    c.line(ax_x, ax_y, ax_x + 380, ax_y)
    c.line(ax_x, ax_y, ax_x, ax_y + 320)
    bars = [80, 140, 100, 220, 180, 260]
    labels = ["1月", "2月", "3月", "4月", "5月", "6月"]
    bar_w = 35
    gap = 20
    for i, (h, lab) in enumerate(zip(bars, labels)):
        x0 = ax_x + 20 + i * (bar_w + gap)
        c.rect(x0, ax_y, bar_w, h, fill=1)
        c.setFont(ZH_FONT, 9)
        c.drawString(x0 + 5, ax_y - 15, lab)
    c.showPage()
    c.save()
    return p


def make_finance_pdf():
    return make_pdf("财务预算方案2024.pdf", [
        "本公司2024年财务预算方案,营业收入预计增长15%,达到30亿元。\n\n"
        "成本控制方面,运营成本预计下降3%,毛利率提升至42%。\n\n"
        "审计部门将重点审查关联交易和税务合规情况。税务筹划方面,公司将充分利用研发费用加计扣除政策。",
        "应收账款管理:加强客户信用评估,缩短账期。应付账款方面,与主要供应商协商延长付款周期至60天。\n\n"
        "现金流管理:维持3-6个月运营资金储备。投资活动方面,优先布局高ROI项目。\n\n"
        "财务报表披露将遵循企业会计准则,确保信息透明真实。",
    ])


def make_legal_pdf():
    return make_pdf("服务合同违约条款.pdf", [
        "技术服务合同违约责任条款\n\n"
        "第一条 违约情形:乙方未按合同约定时间交付技术成果,或交付的技术成果不符合约定的质量标准,均构成违约。\n\n"
        "第二条 违约责任:乙方应向甲方支付违约金,数额为合同总额的百分之十。情节严重的,甲方有权解除合同。\n\n"
        "第三条 不可抗力:因不可抗力导致一方无法履行合同的,根据影响程度部分或全部免除责任。\n\n"
        "第四条 争议解决:本合同适用中华人民共和国法律,争议由合同签订地人民法院管辖。知识产权归属、专利申请权等按约定执行。",
    ])


def make_tech_pdf():
    return make_pdf("系统架构设计文档.pdf", [
        "微服务架构设计原则\n\n"
        "系统采用前后端分离架构,后端使用 FastAPI 框架,前端使用 Vue.js。\n\n"
        "数据库采用 MySQL 主从复制,Redis 缓存热点数据。API 网关使用 Kong,实现限流、鉴权、灰度发布。\n\n"
        "服务间通过 gRPC 通信,消息队列使用 Kafka 异步解耦。\n\n"
        "部署使用 Docker + Kubernetes,实现弹性伸缩。监控系统采用 Prometheus + Grafana,日志通过 ELK 收集。",
    ])


def make_hr_excel():
    p = OUT / "员工花名册.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "基本信息"
    ws.append(["姓名", "部门", "职位", "入职日期", "月薪"])
    rows = [
        ["张伟", "财务部", "会计", "2022-03-15", 12000],
        ["李娜", "人力资源部", "HR经理", "2020-07-01", 18000],
        ["王强", "技术部", "后端工程师", "2023-01-10", 25000],
        ["赵敏", "法务部", "法务专员", "2021-05-20", 15000],
    ]
    for r in rows:
        ws.append(r)
    ws2 = wb.create_sheet("培训记录")
    ws2.append(["员工", "培训内容", "日期", "时长(小时)"])
    ws2.append(["张伟", "财务合规", "2024-01-15", 8])
    ws2.append(["李娜", "绩效管理", "2024-02-20", 16])
    wb.save(p)
    return p


def make_docx_sample():
    """生成一个带标题样式的 Word 样本"""
    from docx import Document
    from docx.shared import Pt
    p = OUT / "员工手册.docx"
    doc = Document()
    doc.add_heading("员工手册", level=1)
    doc.add_paragraph("本手册适用于全体员工,涵盖入职、考勤、薪酬、福利等内容。")
    doc.add_heading("第一章 入职流程", level=2)
    doc.add_paragraph("新员工入职需在 3 个工作日内完成劳动合同签订、社保办理、入职培训。")
    doc.add_paragraph("入职材料包括身份证、学历证书、离职证明、体检报告等。")
    doc.add_heading("第二章 考勤制度", level=2)
    doc.add_paragraph("公司实行弹性工作制,核心工作时间为 10:00-16:00。")
    doc.add_paragraph("事假需提前 1 天申请,病假需提供医院证明。年假按工龄计算。")
    doc.add_heading("第三章 薪酬福利", level=2)
    doc.add_paragraph("薪酬结构:基本工资 + 绩效奖金 + 股权激励。")
    doc.add_paragraph("福利包括五险一金、补充医疗保险、年度体检、节日福利等。")
    doc.save(p)
    return p


def make_txt_sample():
    """生成一个 TXT 样本"""
    p = OUT / "会议纪要.txt"
    p.write_text(
        "2024 年第三季度战略会议纪要\n\n"
        "时间:2024 年 10 月 15 日\n"
        "参会人员:CEO、CTO、CMO、COO\n\n"
        "议题一:产品路线图\n"
        "讨论 Q4 重点功能交付计划,确定优先开发 AI 助手 v2 版本。\n\n"
        "议题二:市场策略\n"
        "加强 B 端市场拓展,目标 Q4 新增企业客户 50 家。\n\n"
        "议题三:组织调整\n"
        "成立 AI 创新部,由 CTO 直接负责,招聘 5 名高级算法工程师。\n\n"
        "行动项:\n"
        "1. 产品部 11 月 1 日前提交 AI 助手 v2 详细方案\n"
        "2. 市场部 11 月 15 日前完成 B 端客户调研报告\n"
        "3. 人事部 12 月底前完成 AI 创新部组建\n",
        encoding="utf-8",
    )
    return p


def make_sample_jpg():
    """生成一个简单 JPG 样本 - 用 Pillow 画一张图"""
    from PIL import Image, ImageDraw, ImageFont
    p = OUT / "产品路线图.jpg"
    img = Image.new("RGB", (800, 500), color=(240, 240, 245))
    draw = ImageDraw.Draw(img)

    # 画 4 个阶段方块
    stages = ["Q1", "Q2", "Q3", "Q4"]
    colors = [(220, 100, 100), (100, 180, 220), (220, 180, 100), (100, 200, 100)]
    for i, (st, col) in enumerate(zip(stages, colors)):
        x0 = 50 + i * 180
        draw.rectangle([x0, 200, x0 + 140, 320], fill=col, outline=(50, 50, 50), width=2)
        draw.text((x0 + 50, 240), st, fill=(0, 0, 0))

    # 标题
    draw.text((200, 60), "2024 Product Roadmap", fill=(20, 20, 80))
    draw.text((180, 100), "Quarterly Milestones Overview", fill=(80, 80, 80))

    img.save(p, "JPEG", quality=85)
    return p


if __name__ == "__main__":
    files = [
        make_finance_pdf(),
        make_hr_excel(),
        make_legal_pdf(),
        make_tech_pdf(),
    ]

    try:
        files.append(make_docx_sample())
    except ImportError:
        print("  (skip docx: python-docx not installed)")
    except Exception as e:
        print(f"  (skip docx: {e})")

    try:
        files.append(make_txt_sample())
    except Exception as e:
        print(f"  (skip txt: {e})")

    try:
        files.append(make_pdf_with_image(
            "含图年报.pdf",
            "2024 年度报告",
            ["本报告涵盖公司全年的财务表现。营业收入达 30 亿元,同比增长 15%。",
             "研发投入持续加大,占营收 8%。下页展示销售趋势图。"],
            chart_caption="图 1: 上半年销售趋势",
        ))
    except Exception as e:
        print(f"  (skip 含图 PDF: {e})")

    try:
        files.append(make_sample_jpg())
    except ImportError:
        print("  (skip jpg: Pillow not installed)")
    except Exception as e:
        print(f"  (skip jpg: {e})")

    print("generated:")
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size} bytes)")
