# SDR 常驻监控部署说明

第二套监控 `scripts/monitor.py` 是**本地常驻进程**，可按秒级间隔探测站点（GitHub Actions 定时任务最短只能 5 分钟，无法做到每秒，所以高频监控要跑在自己的服务器/VPS 上）。

## 一、手动试运行

在仓库目录下：

```bash
# 只跑一轮（适合先验证连通性）
python3 scripts/monitor.py --once

# 常驻，每 1 秒探测一次
INTERVAL=1 python3 scripts/monitor.py
```

可用环境变量调整：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SDR_URL` | `http://sdr.bh4dts.site:8073/status` | 状态端点 |
| `INTERVAL` | `1` | 轮询间隔（秒），高频可设 1 |
| `TIMEOUT` | `5` | 单次抓取超时（秒） |
| `SAMPLE_EVERY` | `1` | 每多少轮写一条指标到 CSV；设 60 ≈ 每分钟一条，避免文件膨胀 |
| `WEBHOOK_URL` | 空 | 掉线/恢复通知地址，不配则不推送 |

## 二、用 systemd 常驻（推荐）

1. 把仓库放到服务器，例如 `/opt/shanghai-sdr`：

```bash
git clone https://github.com/lyh2005050/shanghai-sdr.git /opt/shanghai-sdr
```

2. 复制并按需修改服务文件 `deploy/sdr-monitor.service`（重点改 `User`、`WorkingDirectory`、`ExecStart` 路径，以及 `WEBHOOK_URL`）：

```bash
cp deploy/sdr-monitor.service /etc/systemd/system/sdr-monitor.service
# 编辑路径与环境变量
vim /etc/systemd/system/sdr-monitor.service
```

3. 启用并启动：

```bash
systemctl daemon-reload
systemctl enable --now sdr-monitor
systemctl status sdr-monitor
journalctl -u sdr-monitor -f      # 查看实时日志
```

## 三、产物文件（data/ 目录）

- `monitor_state.json`：上次在线状态，用于掉线/恢复判定
- `monitor_metrics.csv`：指标趋势（按 `SAMPLE_EVERY` 降采样）
- `monitor.log`：运行与告警日志

## 四、说明

- 进程异常退出会被 systemd `Restart=always` 自动拉起。
- 掉线只会在「在线 → 离线」跳变时通知一次，恢复时再通知一次，不会每秒重复轰炸。
- 若站点在国内服务器上、网络访问 `sdr.bh4dts.site:8073` 不通，先在该机器上 `curl -I http://sdr.bh4dts.site:8073/status` 验证连通性。
