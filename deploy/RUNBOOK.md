# Deploy runbook: Extractly on AWS EC2

Target: the existing `t3.micro` in `us-east-1` (free tier, $0).
Service port: **3200** (signal-lab already owns 3100 on the same box).
Public URL shape: `http://<PUBLIC_IP>:3200`.

## 0. Confirm the box

Instance id (from prior work): `i-0ead85f4c02139ea3`. Its public IP changes on
stop/start; confirm the current one (Oct 3 it was `3.85.37.119`):

```bash
aws ec2 describe-instances --instance-ids i-0ead85f4c02139ea3 \
  --region us-east-1 --query 'Reservations[0].Instances[0].PublicIpAddress'
```

Recommended: allocate an Elastic IP and associate it (free while attached to a
running instance) so the production URL never moves before judging.

## 1. Security group

Allow inbound TCP 3200 from 0.0.0.0/0 (same pattern as the existing 3100 rule
for signal-lab). Without this the service is unreachable from the internet.

## 2. Write the env file (by hand, never in chat)

SSH in and create `/opt/extractly/extractly.env`:

```
NEBIUS_API_KEY=<dedicated Token Factory key, e.g. "extractly-prod">
```

Obtain the key via the Secure Vault flow; never paste it in chat or logs.
`GUMROAD_PRODUCT_PERMALINK` can be added later when the Pro product exists;
until then `/v1/upgrade` honestly returns 503 `not_configured`.

```bash
sudo mkdir -p /opt/extractly && sudo chown ubuntu:ubuntu /opt/extractly
cat > /opt/extractly/extractly.env <<'EOF'
NEBIUS_API_KEY=PASTE_VIA_SECURE_CHANNEL
EOF
chmod 600 /opt/extractly/extractly.env
```

## 3. Run setup

```bash
bash /opt/extractly/scripts/setup-box.sh   # after cloning, or:
```

First run from a fresh checkout:

```bash
git clone https://github.com/fernandogarzaaa/extractly.git /opt/extractly
bash /opt/extractly/scripts/setup-box.sh
```

The script installs deps, creates the venv, installs the systemd unit,
enables it, installs the 5-minute pull-based auto-update cron, and
health-checks `http://127.0.0.1:3200/healthz`.

## 4. Verify from the internet

```bash
curl -s http://<PUBLIC_IP>:3200/healthz
curl -s -X POST http://<PUBLIC_IP>:3200/v1/keys -H 'Content-Type: application/json' -d '{}'
```

Then run one real extraction with the returned key (see README).

## 5. Ongoing deploys

Push to `main` on GitHub; the box pulls within 5 minutes, reinstalls if
`requirements.txt` changed, restarts the service, and health-checks.
The box is a pure deploy target: `git reset --hard` on every update.

## Troubleshooting

- `systemctl status extractly`, `journalctl -u extractly -n 50`
- Update log: `/var/log/extractly-update.log`
- `/v1/extract` returns 502 `model_error`: `NEBIUS_API_KEY` missing/invalid
  in `/opt/extractly/extractly.env`.
- Abuse: set `EXTRACTLY_KILL_SWITCH=1` in the env file and
  `sudo systemctl restart extractly` to pause extractions instantly.
