#!/usr/bin/env python3
"""
独立 SDR 监控脚本（第二套）。

与 analyze.py 并行运行，职责：
1. 抓取 KiwiSDR 状态端点，判定在线 / 离线 / 抓取失败；
2. 用 data/monitor_state.json 记录上次状态，检测“掉线”和“恢复”事件；
3. 把用户数、SNR、GPS 等指标追加到 data/monitor_metrics.csv；
4. 状态变化时通过 Webhook 推送通知（地址从环境变量 WEBHOOK_URL 读取，未配置则跳过）；
5. 全程容错：任何异常都写日志并以 0 退出，避免工作流红色失败。

环境变量：
  SDR_URL       状态端点，默认 http://sdr.bh4dts.site:8073/status
  WEBHOOK_URL   可选，掉线 / 恢复时推送的 Webhook 地址
  TIMEOUT       抓取超时秒数，默认 15
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime

DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "monitor_state.json")
METRICS_FILE = os.path.join(DATA_DIR, "monitor_metrics.csv")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")

METRIC_FIELDS = ["time", "online", "reachable", "users", "users_max", "snr", "gps_good", "latency_ms"]

SDR_URL = os.environ.get("SDR_URL", "http://sdr.bh4dts.site:8073/status")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
TIMEOUT = int(os.environ.get("TIMEOUT", "15"))


def log(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def parse_status(text):
    info = {}
    for line in text.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def fetch_status():
    """返回 (reachable, status_dict, latency_ms, error)。"""
    import time
    start = time.time()
    try:
        req = urllib.request.Request(SDR_URL, headers={"User-Agent": "sdr-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        latency = int((time.time() - start) * 1000)
        if "<html" in body[:200].lower() or "<doctype" in body[:200].lower():
            return False, {}, latency, "返回 HTML 页面而非状态文本"
        return True, parse_status(body), latency, None
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return False, {}, latency, f"{type(e).__name__}: {e}"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def append_metrics(row):
    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(METRICS_FILE)
    with open(METRICS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=METRIC_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def send_webhook(text, level):
    if not WEBHOOK_URL:
        log("未配置 WEBHOOK_URL，跳过通知")
        return
    payload = json.dumps({"text": text, "level": level, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}).encode()
    try:
        req = urllib.request.Request(
            WEBHOOK_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"Webhook 推送成功 HTTP {resp.status}")
    except Exception as e:
        log(f"Webhook 推送失败：{type(e).__name__}: {e}")


def main():
    reachable, status, latency, err = fetch_status()
    online = reachable and status.get("offline") == "no"
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    users = status.get("users") or "?"
    users_max = status.get("users_max") or "?"
    snr = status.get("snr") or "?"
    gps_good = status.get("gps_good") or "?"

    if not reachable:
        log(f"抓取失败：{err}（{latency}ms）")
    else:
        log(f"抓取成功 online={online} users={users}/{users_max} snr={snr} gps={gps_good} latency={latency}ms")

    append_metrics({
        "time": now,
        "online": "yes" if online else "no",
        "reachable": "yes" if reachable else "no",
        "users": users,
        "users_max": users_max,
        "snr": snr,
        "gps_good": gps_good,
        "latency_ms": latency,
    })

    prev = load_state()
    prev_online = prev.get("online")
    event = "none"

    # 事件判定：仅在与上次状态不同时触发，避免重复告警
    if prev_online is None:
        event = "init"
        log(f"首次记录，当前状态：{'在线' if online else '离线/不可达'}")
    elif online and prev_online is False:
        event = "recovered"
        msg = f"✅ SDR 已恢复在线｜用户 {users}/{users_max}，SNR {snr}，GPS {gps_good}"
        log(msg); send_webhook(msg, "recovered")
    elif not online and prev_online is True:
        reason = err if not reachable else "站点上报 offline"
        event = "down"
        msg = f"❌ SDR 掉线｜原因：{reason}"
        log(msg); send_webhook(msg, "down")
    else:
        log("状态未变化，不触发告警")

    save_state({"online": online, "reachable": reachable, "time": now, "event": event})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"监控脚本异常：{type(e).__name__}: {e}")
        sys.exit(0)
