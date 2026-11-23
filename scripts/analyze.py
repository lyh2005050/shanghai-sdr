#!/usr/bin/env python3
"""分析 SDR 状态历史，生成报告（缺字段时安全兜底，不抛异常）"""
import os
from datetime import datetime

DATA_DIR = "data"
REPORT = "data/report.md"
STATUS = os.path.join(DATA_DIR, "status.txt")


def parse_status(text):
    info = {}
    for line in text.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def main():
    current = {}
    if os.path.exists(STATUS):
        with open(STATUS, encoding="utf-8") as f:
            current = parse_status(f.read())

    offline = current.get("offline")
    online = offline == "no"

    with open(REPORT, "w", encoding="utf-8") as out:
        out.write("# SDR 站运行报告\n\n")
        out.write(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n")

        out.write("## 当前状态\n\n")
        if not current:
            out.write("- 状态：⚠️ 暂无有效状态数据（站点可能离线或抓取失败）\n")
            return

        out.write(f"- 在线：{'✅' if online else '❌'} {offline if offline else '?'}\n")
        out.write(f"- 用户：{current.get('users', '?')}/{current.get('users_max', '?')}\n")
        out.write(f"- SNR：{current.get('snr', '?')}\n")
        out.write(f"- GPS 卫星：{current.get('gps_good', '?')}\n")
        uptime = to_int(current.get("uptime"), -1)
        out.write(f"- 运行时间：{str(uptime // 86400) + ' 天' if uptime >= 0 else '?'}\n")
        out.write(f"- 硬件：{current.get('sdr_hw', '?')}\n")
        out.write(f"- 天线：{current.get('antenna', '?')}\n")


if __name__ == "__main__":
    main()
