# Production Paper-Trading Operations

This runbook deploys CryptoBrain as a continuously running **public-market-data
paper system**. It does not configure exchange credentials and cannot place an
exchange order.

The production loop is deliberately separated into three processes:

1. `cryptobrain-scan.timer` scans BTC, ETH and XAUUSD every 15 minutes and
   writes only review candidates. It never uses `--auto-approve`.
2. A human approves or rejects a candidate in the localhost-only dashboard.
3. `cryptobrain-paper.service` monitors approved plans and simulates entry,
   stop and TP1 against public candles.

## Safety model

- `PROGRESSION=simulator` is mandatory for unattended evidence collection.
- `python main.py preflight` fails closed unless every watchlist feed responds,
  live 15-minute candles are at most 30 minutes old, the SQLite store works,
  desk/risk/behavior gates are enabled, gold session blocking is enabled, and
  independent prices have no deviation above 1%.
- A closed risk gate is not a process failure: existing paper positions remain
  monitored, but new plans cannot enroll.
- The dashboard binds to `127.0.0.1`; remote access must use an SSH tunnel or
  an authenticated TLS reverse proxy.
- Binance/other exchange API keys are unnecessary. If exchange secret variable
  names are detected, preflight warns so they can be removed.

## 1. Prepare an Ubuntu/Debian VPS

Use a non-shared VPS with Python 3.11+ and outbound HTTPS access. Keep the host
clock synchronized because stale-candle checks depend on it.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv sqlite3
sudo timedatectl set-ntp true

sudo useradd --system --home /var/lib/cryptobrain \
  --shell /usr/sbin/nologin cryptobrain
sudo install -d -o cryptobrain -g cryptobrain -m 0750 /var/lib/cryptobrain
sudo install -d -o root -g cryptobrain -m 0750 /etc/cryptobrain
```

Install the application read-only under `/opt`:

```bash
sudo git clone https://github.com/Azimshawon/SKY.git /opt/cryptobrain
sudo python3 -m venv /opt/cryptobrain/.venv
sudo /opt/cryptobrain/.venv/bin/pip install --upgrade pip
sudo /opt/cryptobrain/.venv/bin/pip install -r /opt/cryptobrain/requirements.txt
sudo chown -R root:root /opt/cryptobrain
```

## 2. Configure the service environment

```bash
sudo install -o root -g cryptobrain -m 0640 \
  /opt/cryptobrain/ops/cryptobrain.env.example \
  /etc/cryptobrain/cryptobrain.env
sudoedit /etc/cryptobrain/cryptobrain.env
```

Keep these production-paper values unchanged:

```dotenv
DEMO_MODE=0
PROGRESSION=simulator
DESK_DEFAULT=true
PRIMARY_SETUP_FAMILY=sweep_trend_continuation
ENFORCE_RISK_LIMITS=true
TRADER_STATE_BLOCK=true
GOLD_SESSION_MODE=block
DB_PATH=/var/lib/cryptobrain/cryptobrain.db
DASHBOARD_HOST=127.0.0.1
```

Telegram/Discord and LLM settings are optional. Do **not** add exchange API
keys—the system reads public data only.

## 3. Install and verify the units

```bash
sudo install -o root -g root -m 0644 \
  /opt/cryptobrain/ops/systemd/*.service \
  /opt/cryptobrain/ops/systemd/*.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/cryptobrain-paper.service \
  /etc/systemd/system/cryptobrain-scan.service \
  /etc/systemd/system/cryptobrain-scan.timer \
  /etc/systemd/system/cryptobrain-dashboard.service
```

Run the preflight under the same user and environment as the services:

```bash
sudo -u cryptobrain bash -c '
  set -a
  source /etc/cryptobrain/cryptobrain.env
  set +a
  cd /opt/cryptobrain
  .venv/bin/python main.py preflight
'
```

Do not continue until the verdict is `READY FOR PAPER OPERATIONS`. Warnings
about optional notifications are acceptable. A price-deviation, stale-feed,
wrong-progression, or disabled-safety failure is not.

For an offline rehearsal only:

```bash
DEMO_MODE=1 PROGRESSION=simulator \
  python main.py preflight --allow-demo
python main.py paper --watch --allow-demo
```

Demo outcomes never count as live paper evidence.

## 4. First controlled run

Start one scan manually and inspect its logs before enabling the timer:

```bash
sudo systemctl start cryptobrain-scan.service
sudo journalctl -u cryptobrain-scan.service -n 200 --no-pager
```

Enable continuous monitoring only after the scan and preflight are clean:

```bash
sudo systemctl enable --now cryptobrain-paper.service
sudo systemctl enable --now cryptobrain-scan.timer
sudo systemctl enable --now cryptobrain-dashboard.service

systemctl status cryptobrain-paper.service cryptobrain-scan.timer \
  cryptobrain-dashboard.service
```

The scan timer may be inspected with:

```bash
systemctl list-timers cryptobrain-scan.timer
```

## 5. Access the dashboard safely

Port 8050 should remain closed in the VPS firewall. From your computer, create
an SSH tunnel:

```bash
ssh -N -L 8050:127.0.0.1:8050 YOUR_USER@YOUR_VPS
```

Then open <http://127.0.0.1:8050>. The dashboard is write-capable: it can
approve/reject signals, set trader state, and run paper actions. Do not expose
it anonymously to the internet.

If a reverse proxy is required, add TLS **and authentication** in Caddy/Nginx;
do not change Gunicorn's bind address from loopback.

## 6. Daily operating routine

1. Check host and service health:

   ```bash
   sudo systemctl --failed
   sudo journalctl -u cryptobrain-paper.service --since today --no-pager
   ```

2. Review every pending candidate in the dashboard or CLI. Approve only when
   the plan and your trader state meet the system rules:

   ```bash
   cd /opt/cryptobrain
   sudo -u cryptobrain bash -c '
     set -a; source /etc/cryptobrain/cryptobrain.env; set +a
     .venv/bin/python main.py review
   '
   ```

3. Never automate approval. The scanner intentionally omits
   `--auto-approve`.
4. Journal each closed paper trade, especially `followed_rules` and emotion.
5. Recompute learning and inspect the graduation gate:

   ```bash
   sudo -u cryptobrain bash -c '
     set -a; source /etc/cryptobrain/cryptobrain.env; set +a
     cd /opt/cryptobrain
     .venv/bin/python main.py learn
     .venv/bin/python main.py stats
     .venv/bin/python main.py agent ask "am I ready for micro?"
   '
   ```

Do not set `PROGRESSION=micro` until the implemented graduation gate passes:
positive expectancy, win rate above 55%, profit factor at least 1.5, rule
compliance at least 90%, and at least 100 backtest plus 20 paper samples for
each primary setup.

## 7. Logs, stop controls and recovery

Useful commands:

```bash
sudo journalctl -fu cryptobrain-paper.service
sudo journalctl -u cryptobrain-scan.service --since '24 hours ago'
sudo systemctl stop cryptobrain-scan.timer      # stop creating candidates
sudo systemctl stop cryptobrain-paper.service   # stop all paper checks
sudo systemctl restart cryptobrain-dashboard.service
```

If preflight starts failing, the paper watcher exits and systemd retries only
three times in ten minutes. Fix the feed/configuration problem, run preflight
manually, and then reset/start it:

```bash
sudo systemctl reset-failed cryptobrain-paper.service
sudo systemctl start cryptobrain-paper.service
```

## 8. Back up the learning store

SQLite's `.backup` command creates a consistent snapshot while the services are
running:

```bash
sudo install -d -o root -g root -m 0700 /var/backups/cryptobrain
sudo sqlite3 /var/lib/cryptobrain/cryptobrain.db \
  ".backup '/var/backups/cryptobrain/cryptobrain-$(date +%F).db'"
sudo chmod 0600 /var/backups/cryptobrain/cryptobrain-*.db
```

Retain several daily copies off-host. The database contains the evidence,
journal, calibration and lifecycle audit trail; losing it resets progression.

## 9. Safe application updates

```bash
sudo systemctl stop cryptobrain-scan.timer cryptobrain-paper.service \
  cryptobrain-dashboard.service
sudo git -C /opt/cryptobrain pull --ff-only
sudo /opt/cryptobrain/.venv/bin/pip install -r /opt/cryptobrain/requirements.txt
cd /opt/cryptobrain
sudo .venv/bin/python -m pytest tests/ -q
sudo -u cryptobrain bash -c '
  set -a; source /etc/cryptobrain/cryptobrain.env; set +a
  cd /opt/cryptobrain
  .venv/bin/python main.py preflight
'
sudo systemctl start cryptobrain-dashboard.service cryptobrain-paper.service \
  cryptobrain-scan.timer
```

After every update, check the first scan and paper-monitor logs before leaving
the services unattended.
