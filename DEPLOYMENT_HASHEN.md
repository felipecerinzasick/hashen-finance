# Hashen VPS Deployment Notes

Do not use any private key that has been pasted into chat or committed anywhere.
Generate a fresh SSH keypair, add the new public key to the VPS, and revoke the exposed key before deploying.

Target:
- Domain: `hashen.ch`
- Server: Ubuntu 24.04 LTS
- App user: `ubuntu`
- App path: `/srv/hashen`

## Server setup

```bash
sudo apt update
sudo apt install -y git curl build-essential libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev libffi-dev liblzma-dev caddy
```

This project currently runs on Python 3.9 locally. On Ubuntu 24.04, use `pyenv` or a maintained Python 3.9 package source rather than the default Python 3.12.

## Clone and install

```bash
sudo mkdir -p /srv/hashen
sudo chown ubuntu:ubuntu /srv/hashen
cd /srv/hashen
git clone https://github.com/felipecerinzasick/ventures-master.git .

python3.9 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Create `/srv/hashen/.env`:

```bash
SECRET_KEY=replace-with-a-long-random-secret
DEBUG=False
DJANGO_SETTINGS_MODULE=web.local_settings
HASHEN_DASHBOARD_USERNAME=hashen
HASHEN_DASHBOARD_PASSWORD_HASH=sha256$replace-with-password-sha256
```

## Django setup

```bash
cd /srv/hashen
set -a
. ./.env
set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
```

## Gunicorn service

Create `/etc/systemd/system/hashen.service`:

```ini
[Unit]
Description=Hashen Django app
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/srv/hashen
EnvironmentFile=/srv/hashen/.env
ExecStart=/srv/hashen/.venv/bin/gunicorn web.wsgi:application --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hashen
sudo systemctl status hashen
```

## Caddy

Create `/etc/caddy/Caddyfile`:

```caddy
hashen.ch {
  encode gzip
  reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Point the DNS `A` record for `hashen.ch` to the VPS IPv4 address and add the IPv6 record if desired.
