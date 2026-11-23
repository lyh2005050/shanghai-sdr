#!/usr/bin/env python3
"""
上海 SDR（KiwiSDR）状态分析脚本。

职责：
1. 解析 data/status.txt 的 key=value 状态文本；
2. 生成人类可读的 data/report.md；
3. 把本次关键指标追加到 data/history.csv，供趋势对比；
4. 任何字段缺失 / 站点离线 / 文件异常都安全兜底，不抛异常中断工作流。
"""
import csv
import os
from datetime import datetime

DATA_DIR = "data"
STATUS = os.path.join(DATA_DIR, "status.txt")
REPORT = os.path.join(DATA_DIR, "report.md")
HISTORY = os.path.join(DATA_DIR, "history.csv")

HISTORY_FIELDS = ["time", "online", "users", "users_max", "snr", "gps_good", "uptime_days", "antenna"]


def parse_status(text):
    """把 key=value 文本解析成字典；忽略空行与非键值行。"""
    info = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def to_int(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt_uptime(seconds):
    if seconds is None:
        return "?"
    days, rem = divmod(seconds, 86400)
    hours, _ = divmod(rem, 3600)
    return f"{days} 天 {hours} 小时"


def load_history():
    rows = []
    if os.path.exists(HISTORY):
        with open(HISTORY, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows


def append_history(record):
    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(HISTORY)
    with open(HISTORY, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(record)


def main():
    current = {}
    if os.path.exists(STATUS):
        with open(STATUS, encoding="utf-8") as f:
            current = parse_status(f.read())

    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    offline = current.get("offline")
    online = offline == "no"

    # 关键指标（全部带兜底）
    users = current.get("users") or "?"
    users_max = current.get("users_max") or "?"
    snr = current.get("snr") or "?"
    gps_good = current.get("gps_good") or "?"
    uptime = to_int(current.get("uptime"))
    antenna = current.get("antenna") or "?"
    hw = current.get("sdr_hw") or "?"
    sw = current.get("sw_version") or "?"
    gps = current.get("gps") or "?"
    asl = current.get("asl") or "?"
    ant_connected = current.get("ant_connected")
    ant_state = "已连接" if ant_connected == "1" else ("未连接" if ant_connected == "0" else "?")

    # 写历史趋势（仅在有有效状态时）
    if current:
        append_history({
            "time": now,
            "online": "yes" if online else "no",
            "users": users,
            "users_max": users_max,
            "snr": snr,
            "gps_good": gps_good,
            "uptime_days": (uptime // 86400) if uptime is not None else "",
            "antenna": antenna,
        })

    history = load_history()
    online_count = sum(1 for r in history if r.get("online") == "yes")
    total = len(history)

    with open(REPORT, "w", encoding="utf-8") as out:
        out.write("# 上海 SDR 站运行报告\n\n")
        out.write(f"更新时间：{now}\n\n")

        if not current:
            out.write("## 当前状态\n\n")
            out.write("- ⚠️ 暂无有效状态数据（站点可能离线或本次抓取失败）\n")
            return

        out.write("## 当前状态\n\n")
        out.write(f"- 在线：{'✅ 在线' if online else '❌ 离线'}（offline={offline or '?'}）\n")
        out.write(f"- 用户：{users}/{users_max}\n")
        out.write(f"- SNR：{snr}\n")
        out.write(f"- GPS 卫星：{gps_good} 颗，坐标 {gps}\n")
        out.write(f"- 运行时间：{fmt_uptime(uptime)}\n")
        out.write(f"- 硬件：{hw}\n")
        out.write(f"- 固件：{sw}\n")
        out.write(f"- 天线：{antenna}（{ant_state}）\n")
        out.write(f"- 海拔：{asl} 米\n\n")

        out.write("## 近期趋势\n\n")
        if total:
            out.write(f"- 历史记录：{total} 次，其中在线 {online_count} 次，在线率 {online_count / total * 100:.0f}%\n")
            recent = history[-5:]
            out.write("\n| 时间 | 状态 | 用户 | SNR | GPS |\n|---|---|---|---|---|\n")
            for r in reversed(recent):
                state_txt = "✅" if r.get("online") == "yes" else "❌"
                out.write(f"| {r.get('time', '?')} | {state_txt} | {r.get('users', '?')}/{r.get('users_max', '?')} | {r.get('snr', '?')} | {r.get('gps_good', '?')} |\n")
        else:
            out.write("- 暂无历史记录\n")


if __name__ == "__main__":
    main()
