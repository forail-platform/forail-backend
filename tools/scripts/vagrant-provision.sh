#!/bin/bash
set -euo pipefail

echo "============================================"
echo " Forail Build Environment - Ubuntu 24.04"
echo " Provisioning..."
echo "============================================"

export DEBIAN_FRONTEND=noninteractive

# --- System packages ---
echo "[1/5] Installing system packages..."
apt-get update
apt-get install -y \
    git curl wget gnupg lsb-release ca-certificates \
    build-essential gcc g++ make \
    python3 python3-pip python3-venv python3-dev \
    libpq-dev libxml2-dev libxslt1-dev libffi-dev libssl-dev \
    libldap2-dev libsasl2-dev \
    libxmlsec1-dev libxmlsec1-openssl \
    pkg-config \
    swig \
    unzip rsync \
    ansible

# --- Docker ---
echo "[2/5] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable docker --now
usermod -aG docker vagrant

# Docker Compose plugin (comes with docker now, but ensure it's there)
apt-get install -y docker-compose-plugin 2>/dev/null || true

# Standalone docker-compose binary as fallback
if ! command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -oP '"tag_name": "\K[^"]+')
    curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# --- Node.js 18 (matches build requirement) ---
echo "[3/5] Installing Node.js 18..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
    apt-get install -y nodejs
fi

# --- Python setup ---
echo "[4/5] Setting up Python environment..."
# Ubuntu 24.04 ships python3.12 — use it directly
python3.12 -m ensurepip 2>/dev/null || true
python3.12 -m pip install --break-system-packages --upgrade pip setuptools wheel 2>/dev/null || true

# Install ansible for vagrant user (used by Makefile)
pip3 install --break-system-packages ansible docker 2>/dev/null || \
    pip3 install ansible docker

# --- Workspace setup ---
echo "[5/5] Setting up workspace..."

# Create projects dir
mkdir -p /awx_devel/forail/projects

# Link for convenience
ln -sf /awx_devel /home/vagrant/forail

# Shell environment for vagrant user
cat >> /home/vagrant/.bashrc << 'BASHRC'

# Forail Development Environment
export FORAIL_DEVEL=/awx_devel
alias forail-build='cd /awx_devel && make docker-compose-build'
alias forail-start='cd /awx_devel && make docker-compose COMPOSE_UP_OPTS=-d'
alias forail-stop='cd /awx_devel && make docker-compose-down'
alias forail-logs='docker compose -f /awx_devel/tools/docker-compose/_sources/docker-compose.yml logs -f'
alias forail-shell='docker exec -it tools_awx_1 bash'
alias forail-test='cd /awx_devel && make docker-compose-runtest'
BASHRC

chown -R vagrant:vagrant /home/vagrant

echo ""
echo "============================================"
echo " Forail Build Environment - Ready"
echo "============================================"
echo ""
echo " Versions:"
echo "   OS:          $(lsb_release -ds)"
echo "   Python 3.12: $(python3.12 --version 2>&1)"
echo "   Node.js:     $(node --version 2>&1)"
echo "   Docker:      $(docker --version 2>&1)"
echo "   Ansible:     $(ansible --version 2>&1 | head -1)"
echo ""
echo " Quick start (run inside VM with 'vagrant ssh'):"
echo "   1. cd /awx_devel"
echo "   2. make docker-compose-build     # Build dev image"
echo "   3. make docker-compose COMPOSE_UP_OPTS=-d  # Start Forail"
echo ""
echo " Or use aliases:"
echo "   forail-build   - Build Forail dev image"
echo "   forail-start   - Start Forail containers"
echo "   forail-stop    - Stop Forail containers"
echo "   forail-logs    - Follow Forail logs"
echo "   forail-shell   - Shell into Forail container"
echo "   forail-test    - Run tests"
echo ""
echo " Access: https://192.168.56.20:8043"
echo "============================================"
