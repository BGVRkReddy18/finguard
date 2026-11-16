#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 VM (Oracle Cloud Always Free, Ampere ARM).
set -euo pipefail

echo "==> Installing Docker (official convenience script) and git"
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl git openssl netfilter-persistent
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

echo "==> Opening HTTP/HTTPS in the VM firewall"
# Oracle's Ubuntu images ship iptables rules that REJECT everything except SSH. Insert ACCEPT rules
# just above that REJECT rule. (Ports must ALSO be opened in the VCN security list — see DEPLOY.md.)
reject_line=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
reject_line=${reject_line:-1}
for rule in "tcp 80" "tcp 443" "udp 443"; do
  set -- $rule
  sudo iptables -C INPUT -p "$1" --dport "$2" -m state --state NEW -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT "$reject_line" -p "$1" --dport "$2" -m state --state NEW -j ACCEPT
done
sudo netfilter-persistent save

echo "==> Done. Log out and back in (docker group), then: git clone <repo> && cd <repo> && ./deploy/gen-env.sh <ip>.sslip.io"
