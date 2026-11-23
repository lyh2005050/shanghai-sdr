#!/usr/bin/env python3
"""
独立 SDR 常驻监控程序（第二套）。

以常驻进程方式高频探测 KiwiSDR 状态端点（默认每 1 秒一轮），职责：
1. 判定在线 / 离线 / 抓取失败；
2. 用 data/monitor_state.json 记录上次状态，检测“掉线”“恢复”事件并告警；
3. 指标写入 data/monitor_metrics.csv（可通过 SAMPLE_EVERY 降采样，避免每秒刷爆文件）；
4. 状态变化时通过 Webhook 推送通知（WEBHOOK_URL 未配置则跳过）；
5. 全程容错：单轮异常不退出进程，写日志后继续下一轮。

用法：
  python3 monitor.py              # 常驻循环，间隔 INTERVAL 秒（默认 1）
  python3 monitor.py --once       # 只跑一轮就退出（兼容 CI / 定时任务）

环境变量：
  SDR_URL       状态端点，默认 http://sdr.bh4dts.site:8073/status
  WEBHOOK_URL   可选，掉线 / 恢复时推送的 Webhook 地址
  TIMEOUT       单次抓取超时秒数，默认 5（高频探测建议短超时）
  INTERVAL      常驻轮询间隔秒数，默认 1
  SAMPLE_EVERY  每多少轮落一条指标到 CSV，默认 1（=每轮都记）；
                设为 60 表示约每分钟记一条，其余轮次只判状态不写文件
"""
import csv
import json
import os
import signal
import sys
import time
import urllib.request
from datetime import datetime

DATA_DIR = os.environ.get("DATA_DIR", "data")
STATE_FILE = os.path.join(DATA_DIR, "monitor_state.json")
METRICS_FILE = os.path.join(DATA_DIR, "monitor_metrics.csv")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")

METRIC_FIELDS = ["time", "online", "reachable", "users", "users_max", "snr", "gps_good", "latency_ms"]

SDR_URL = os.environ.get("SDR_URL", "http://sdr.bh4dts.site:8073/status")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
TIMEOUT = int(os.environ.get("TIMEOUT", "5"))
INTERVAL = float(os.environ.get("INTERVAL", "1"))
SAMPLE_EVERY = max(1, int(os.environ.get("SAMPLE_EVERY", "1")))

_running = True


def _handle_signal(signum, frame):
    global _running
    _running = False
    log("收到退出信号，准备停止监控…")


def log(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
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
        return
    payload = json.dumps({"text": text, "level": level,
                          "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}).encode()
    try:
        req = urllib.request.Request(
            WEBHOOK_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"Webhook 推送成功 HTTP {resp.status}")
    except Exception as e:
        log(f"Webhook 推送失败：{type(e).__name__}: {e}")


def poll_once(round_no, sample):
    reachable, status, latency, err = fetch_status()
    online = reachable and status.get("offline") == "no"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    users = status.get("users") or "?"
    users_max = status.get("users_max") or "?"
    snr = status.get("snr") or "?"
    gps_good = status.get("gps_good") or "?"

    if not reachable:
        log(f"[#{round_no}] 抓取失败：{err}（{latency}ms）")
    else:
        log(f"[#{round_no}] online={online} users={users}/{users_max} snr={snr} gps={gps_good} latency={latency}ms")

    if sample:
        append_metrics({
            "time": now, "online": "yes" if online else "no",
            "reachable": "yes" if reachable else "no",
            "users": users, "users_max": users_max, "snr": snr,
            "gps_good": gps_good, "latency_ms": latency,
        })

    prev = load_state()
    prev_online = prev.get("online")
    event = "none"

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

    save_state({"online": online, "reachable": reachable, "time": now, "event": event})


def main():
    once = "--once" in sys.argv
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log(f"监控启动｜url={SDR_URL} interval={INTERVAL}s sample_every={SAMPLE_EVERY} once={once}")
    round_no = 0

    while _running:
        round_no += 1
        sample = (round_no % SAMPLE_EVERY == 0)
        try:
            poll_once(round_no, sample)
        except Exception as e:
            log(f"第 {round_no} 轮异常：{type(e).__name__}: {e}")
        if once:
            break
        # 分段睡眠，保证收到信号能较快退出
        slept = 0.0
        while _running and slept < INTERVAL:
            time.sleep(min(0.2, INTERVAL - slept))
            slept += 0.2

    log("监控已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
