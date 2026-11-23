#!/usr/bin/env python3
"""
SDR 监控面板后端（标准库，无第三方依赖）。

职责：
1. /api/status  读取本地 monitor_state.json（掉线/恢复状态机结果），
   并实时回源 KiwiSDR 状态端点，拼装前端需要的当前指标；
2. /api/metrics 读取 monitor_metrics.csv，返回最近 N 条趋势；
3. /api/health   存活探测；
4. 静态托管 web/ 目录下的 index.html。

环境变量：
  SDR_URL   状态端点，默认 http://sdr.bh4dts.site:8073/status
  DATA_DIR  数据目录，默认 ../data（相对脚本所在目录）
  HOST      监听地址，默认 127.0.0.1
  PORT      监听端口，默认 8090
  TIMEOUT   回源超时秒数，默认 5
"""
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
DATA_DIR = os.path.abspath(DATA_DIR)
STATIC_DIR = BASE_DIR

SDR_URL = os.environ.get("SDR_URL", "http://sdr.bh4dts.site:8073/status")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8090"))
TIMEOUT = int(os.environ.get("TIMEOUT", "5"))

STATE_FILE = os.path.join(DATA_DIR, "monitor_state.json")
METRICS_FILE = os.path.join(DATA_DIR, "monitor_metrics.csv")


def parse_kv(text):
    info = {}
    for line in text.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def fetch_remote():
    """回源 KiwiSDR 状态端点。返回 (ok, dict, latency_ms, error)。"""
    start = time.time()
    try:
        req = urllib.request.Request(SDR_URL, headers={"User-Agent": "sdr-dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        latency = int((time.time() - start) * 1000)
        if "<html" in body[:200].lower() or "<doctype" in body[:200].lower():
            return False, {}, latency, "返回 HTML 而非状态文本"
        return True, parse_kv(body), latency, None
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


def read_metrics(limit=120):
    rows = []
    if os.path.exists(METRICS_FILE):
        with open(METRICS_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    return rows[-limit:]


def to_int(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def build_status():
    state = load_state()
    reachable, kv, latency, err = fetch_remote()
    online = reachable and kv.get("offline") == "no"

    gps = kv.get("gps", "")
    gps_lat = gps_lon = None
    if gps and gps.startswith("("):
        parts = gps.strip("()").split(",")
        if len(parts) == 2:
            try:
                gps_lat = float(parts[0]); gps_lon = float(parts[1])
            except ValueError:
                pass

    uptime = to_int(kv.get("uptime"))
    uptime_str = "?"
    if uptime is not None:
        d, rem = divmod(uptime, 86400)
        h, _ = divmod(rem, 3600)
        uptime_str = f"{d} 天 {h} 小时"

    return {
        "online": bool(online),
        "reachable": bool(reachable),
        "source": "remote" if reachable else "state",
        "error": err,
        "latency_ms": latency,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "state_event": state.get("event"),
        "state_time": state.get("time"),
        "info": {
            "name": kv.get("name", "—"),
            "users": to_int(kv.get("users")),
            "users_max": to_int(kv.get("users_max")),
            "snr": kv.get("snr", "?"),
            "gps_good": to_int(kv.get("gps_good")),
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "asl": to_int(kv.get("asl")),
            "antenna": kv.get("antenna", "?"),
            "ant_connected": kv.get("ant_connected"),
            "sdr_hw": kv.get("sdr_hw", "?"),
            "sw_version": kv.get("sw_version", "?"),
            "uptime": uptime_str,
            "bands": kv.get("bands", "?"),
            "op_email": kv.get("op_email", ""),
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(404, "not found")

    def do_GET(self):
        path = self.path.split("?")[0]
        # 兼容子路径前缀，如 /sdr/api/status -> /api/status
        if path.startswith("/sdr/"):
            path = path[4:]
        if path in ("/", "/index.html"):
            self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send_json(build_status())
        elif path == "/api/metrics":
            self._send_json({"metrics": read_metrics()})
        elif path == "/api/health":
            self._send_json({"ok": True, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        else:
            self.send_error(404, "not found")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SDR dashboard listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
