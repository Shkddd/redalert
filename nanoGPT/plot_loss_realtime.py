# plot_loss_realtime.py
import re
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from collections import deque
import os


class RealtimeLossPlotter:
    def __init__(self, log_file, max_points=1000, update_interval=2000):
        """
        实时 Loss 曲线绘制器

        Args:
            log_file: 日志文件路径
            max_points: 最大显示点数
            update_interval: 更新间隔（毫秒）
        """
        self.log_file = log_file
        self.max_points = max_points
        self.update_interval = update_interval

        self.steps = deque(maxlen=max_points)
        self.train_losses = deque(maxlen=max_points)
        self.val_losses = deque(maxlen=max_points)

        self.last_position = 0

        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        # 初始化图表
        self.fig, self.ax = plt.subplots(figsize=(14, 8))
        self.line_train, = self.ax.plot([], [], 'b-', linewidth=2, label='Train Loss', marker='o', markersize=3)
        self.line_val, = self.ax.plot([], [], 'r-', linewidth=2, label='Val Loss', marker='s', markersize=3)

        self.ax.set_xlabel('训练步数 (Steps)', fontsize=12)
        self.ax.set_ylabel('Loss 值', fontsize=12)
        self.ax.set_title('📈 实时 Loss 监控', fontsize=14, fontweight='bold')
        self.ax.legend(loc='upper right', fontsize=10)
        self.ax.grid(True, alpha=0.3)

        # 统计信息显示区域
        self.stats_text = self.ax.text(0.02, 0.98, '', transform=self.ax.transAxes,
                                       fontsize=10, verticalalignment='top',
                                       bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

        # 当前步数标注
        self.current_step_text = None

        print(f"📊 实时监控日志: {log_file}")
        print("⏳ 等待数据... (按 Ctrl+C 停止)")

    def read_new_data(self):
        """读取日志文件中的新数据"""
        if not os.path.exists(self.log_file):
            return

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                f.seek(self.last_position)
                lines = f.readlines()
                self.last_position = f.tell()

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # 匹配 "step X: train loss X.XXXX, val loss X.XXXX"
                    match = re.search(r'step\s+(\d+):.*train loss\s+([\d.]+).*val loss\s+([\d.]+)', line, re.IGNORECASE)
                    if match:
                        step = int(match.group(1))
                        train_loss = float(match.group(2))
                        val_loss = float(match.group(3))

                        # 避免重复添加
                        if not self.steps or step > self.steps[-1]:
                            self.steps.append(step)
                            self.train_losses.append(train_loss)
                            self.val_losses.append(val_loss)
                        continue

                    # 匹配 "iter X: loss X.XXXX"
                    match = re.search(r'iter\s+(\d+):.*loss\s+([\d.]+)', line, re.IGNORECASE)
                    if match:
                        step = int(match.group(1))
                        loss = float(match.group(2))

                        if not self.steps or step > self.steps[-1]:
                            self.steps.append(step)
                            self.train_losses.append(loss)
                            # 如果 val_losses 数量小于 train_losses，补 None
                            while len(self.val_losses) < len(self.train_losses):
                                self.val_losses.append(None)
                        continue

        except Exception as e:
            pass

    def update_plot(self, frame):
        """更新图表"""
        self.read_new_data()

        if not self.steps:
            return self.line_train, self.line_val, self.stats_text

        steps = list(self.steps)
        train_losses = [l for l in self.train_losses if l is not None]
        val_losses = [l for l in self.val_losses if l is not None]

        # 更新 Train Loss
        if train_losses:
            # 对齐步数
            valid_steps = steps[:len(train_losses)]
            self.line_train.set_data(valid_steps, train_losses)

        # 更新 Val Loss
        if val_losses:
            valid_steps = steps[:len(val_losses)]
            self.line_val.set_data(valid_steps, val_losses)

        # 调整坐标轴
        if steps:
            self.ax.relim()
            self.ax.autoscale_view()
            self.ax.set_xlim(steps[0] - 10, max(steps) + 50)

        # 更新统计信息
        if train_losses:
            stats = f"""
📊 训练统计
├── 初始 Loss: {train_losses[0]:.4f}
├── 当前 Loss: {train_losses[-1]:.4f}
├── Loss 下降: {train_losses[0] - train_losses[-1]:.4f}
├── 下降比例: {(train_losses[0] - train_losses[-1]) / train_losses[0] * 100:.1f}%
├── 数据点数: {len(steps)}
└── 当前步数: {steps[-1] if steps else 0}
"""
            if val_losses:
                stats += f"\n├── 验证 Loss: {val_losses[-1]:.4f}"

            self.stats_text.set_text(stats)

        return self.line_train, self.line_val, self.stats_text

    def run(self):
        """启动实时监控"""
        ani = animation.FuncAnimation(
            self.fig, self.update_plot,
            interval=self.update_interval,
            blit=False
        )

        try:
            plt.tight_layout()
            plt.show()
        except KeyboardInterrupt:
            print("\n✅ 监控已停止")
        finally:
            # 保存最终图片
            try:
                self.fig.savefig('loss_curve_realtime.png', dpi=150, bbox_inches='tight')
                print("📸 最终曲线已保存: loss_curve_realtime.png")
            except:
                pass


def main():
    """主函数"""
    print("=" * 60)
    print("📊 实时 Loss 曲线监控")
    print("=" * 60)

    # 默认日志文件
    log_file = "training_log.txt"

    # 如果文件不存在，尝试找最新的日志
    if not os.path.exists(log_file):
        print(f"⚠️ 未找到: {log_file}")

        # 查找带时间戳的日志文件
        import glob
        log_files = glob.glob("training_log_*.txt")
        if log_files:
            log_file = sorted(log_files)[-1]
            print(f"📂 自动选择: {log_file}")
        else:
            print("❌ 没有找到日志文件")
            print("请先运行训练并保存日志:")
            print("  python3 train.py config/train_qa.py --device=mps --compile=False 2>&1 | tee training_log.txt")
            return

    if not os.path.exists(log_file):
        print(f"❌ 文件不存在: {log_file}")
        return

    print(f"📖 监控文件: {log_file}")
    print(f"📏 最大显示点数: 1000")
    print("=" * 60)

    plotter = RealtimeLossPlotter(log_file, max_points=1000, update_interval=2000)
    plotter.run()


if __name__ == "__main__":
    main()