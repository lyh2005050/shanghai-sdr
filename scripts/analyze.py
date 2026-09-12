#!/usr/bin/env python3
"""分析 SDR 状态历史，生成报告"""
import os
import re
from datetime import datetime

DATA_DIR = "data"
REPORT = "data/report.md"

def parse_status(text):
    info = {}
    for line in text.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info

def main():
    # 读当前状态
    with open(os.path.join(DATA_DIR, "status.txt")) as f:
        current = parse_status(f.read())

    with open(REPORT, "w") as out:
        out.write("# SDR 站运行报告\n\n")
        out.write(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n")

        out.write("## 当前状态\n\n")
        out.write(f"- 在线：{'✅' if current.get('offline') == 'no' else '❌'} {current.get('offline')}\n")
        out.write(f"- 用户：{current.get('users', '?')}/{current.get('users_max', '?')}\n")
        out.write(f"- SNR：{current.get('snr', '?')}\n")
        out.write(f"- GPS 卫星：{current.get('gps_good', '?')}\n")
        out.write(f"- 运行时间：{int(current.get('uptime', 0))//86400} 天\n")
        out.write(f"- 硬件：{current.get('sdr_hw', '?')}\n")
        out.write(f"- 天线：{current.get('antenna', '?')}\n")

if __name__ == "__main__":
    main()
