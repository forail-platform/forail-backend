### Forge Backend — Production Dockerfile (Ubuntu 24.04)
### Headless build — frontend is served separately via forge-frontend image

# ── Stage 1: Build Python backend ──────────────────────────────────
FROM ubuntu:24.04 AS builder

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV AWX_LOGGING_MODE=stdout
ENV DEBIAN_FRONTEND=noninteractive

USER root

RUN apt-get update && apt-get install -y locales && \
    locale-gen en_US.UTF-8 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y \
    iputils-ping \
    gcc \
    g++ \
    git \
    gettext \
    libffi-dev \
    libltdl-dev \
    make \
    libnss3 \
    libldap2-dev \
    libsasl2-dev \
    openssl \
    patch \
    postgresql-client \
    libpq-dev \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    python3-pip \
    python3-setuptools \
    python3-packaging \
    python3-psycopg2 \
    swig \
    unzip \
    pkg-config \
    libxmlsec1-dev \
    libxmlsec1-openssl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages -vv build

# Install & build requirements
ADD Makefile /tmp/Makefile
RUN mkdir /tmp/requirements
ADD requirements/requirements.txt \
    requirements/requirements_tower_uninstall.txt \
    requirements/requirements_git.txt \
    /tmp/requirements/

RUN cd /tmp && make requirements_awx

ARG VERSION
ARG SETUPTOOLS_SCM_PRETEND_VERSION

# Copy source into builder, build sdist, install it into awx venv
COPY . /tmp/src/
WORKDIR /tmp/src/

RUN HEADLESS=yes make sdist && \
    rm -f dist/forge.tar.gz && \
    /var/lib/awx/venv/awx/bin/pip install dist/forge-*.tar.gz

# SSL cert compatibility for certifi/requests
RUN mkdir -p /etc/pki/tls/certs && \
    ln -sf /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt

# Collect static files (Django admin, DRF, etc.)
RUN DJANGO_SETTINGS_MODULE=forge.settings.defaults \
    SKIP_SECRET_KEY_CHECK=yes \
    SKIP_PG_VERSION_CHECK=yes \
    AWX_LOGGING_MODE=stdout \
    /var/lib/awx/venv/awx/bin/forge-manage collectstatic --noinput --clear

# ── Stage 2: Final runtime image ──────────────────────────────────
FROM ubuntu:24.04

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV AWX_LOGGING_MODE=stdout
ENV DEBIAN_FRONTEND=noninteractive

USER root

RUN apt-get update && apt-get install -y locales && \
    locale-gen en_US.UTF-8 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y \
    acl \
    ca-certificates \
    curl \
    git \
    git-lfs \
    krb5-user \
    nginx \
    libldap2 \
    openssl \
    postgresql-client \
    python3.12 \
    python3.12-dev \
    python3-pip \
    python3-setuptools \
    python3-packaging \
    python3-psycopg2 \
    rsync \
    rsyslog \
    subversion \
    sudo \
    vim-tiny \
    unzip \
    libxmlsec1-openssl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages -vv virtualenv supervisor dumb-init build

# Create CentOS-compatible SSL cert paths (certifi/requests expect these)
RUN mkdir -p /etc/pki/tls/certs && \
    ln -sf /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt

RUN rm -rf /root/.cache && rm -rf /tmp/*

# ── podman for Execution Environment process isolation ─────────────
# AWX/forge runs project updates and job templates inside EE containers
# via ansible-runner, which hardcodes process_isolation_executable=podman.
# This installs podman and configures fuse-overlay storage so it works
# when the forge-task container itself runs in privileged mode under
# Docker. Pattern mirrored from tools/ansible/roles/dockerfile/templates/
# Dockerfile.ubuntu.j2 (upstream AWX dev build).
RUN apt-get update && apt-get install -y podman fuse-overlayfs uidmap && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN STORAGE_CONF=$(find /usr/share/containers /etc/containers -name storage.conf 2>/dev/null | head -1) && \
    if [ -n "$STORAGE_CONF" ] && [ ! -f /etc/containers/storage.conf ]; then \
      cp "$STORAGE_CONF" /etc/containers/storage.conf; \
    fi && \
    if [ -f /etc/containers/storage.conf ]; then \
      sed -i -e 's|^#mount_program|mount_program|g' \
             -e '/additionalimage.*/a "/var/lib/shared",' \
             -e 's|^mountopt[[:space:]]*=.*$|mountopt = "nodev,fsync=0"|g' \
             /etc/containers/storage.conf; \
    fi

ENV _CONTAINERS_USERNS_CONFIGURED=""

# Force fully qualified image names so podman does not hang on interactive
# registry selection prompts when pulling unqualified images.
RUN mkdir -p /etc/containers/registries.conf.d/ && \
    echo "unqualified-search-registries = []" > /etc/containers/registries.conf.d/force-fully-qualified-images.conf && \
    chmod 644 /etc/containers/registries.conf.d/force-fully-qualified-images.conf

# Copy app from builder
COPY --from=builder /var/lib/awx /var/lib/awx

# IaC scanning & supply chain security CLIs (Tier 3.4)
# Installed into the forge venv so Django subprocess calls find them on PATH.
RUN /var/lib/awx/venv/awx/bin/pip install --no-cache-dir \
        'ansible-lint==25.1.*' \
        'checkov==3.2.*' \
        'pip-audit==2.7.*'

# Remove devonly module so forge detects production mode
RUN rm -f /var/lib/awx/venv/awx/lib/python3.12/site-packages/forge/devonly.py \
          /var/lib/awx/venv/awx/lib/python3.12/site-packages/forge/devonly.pyc

RUN ln -s /var/lib/awx/venv/awx/bin/forge-manage /usr/bin/forge-manage && \
    ln -s /var/lib/awx/venv/awx/bin/awx-manage /usr/bin/awx-manage

COPY --from=quay.io/ansible/receptor:devel /usr/bin/receptor /usr/bin/receptor

ADD tools/ansible/roles/dockerfile/files/rsyslog.conf /var/lib/awx/rsyslog/rsyslog.conf
ADD tools/ansible/roles/dockerfile/files/wait-for-migrations /usr/local/bin/wait-for-migrations
ADD tools/ansible/roles/dockerfile/files/stop-supervisor /usr/local/bin/stop-supervisor

ADD tools/ansible/roles/dockerfile/files/uwsgi.ini /etc/tower/uwsgi.ini

ADD tools/ansible/roles/dockerfile/files/launch_awx_web.sh /usr/bin/launch_awx_web.sh
ADD tools/ansible/roles/dockerfile/files/launch_awx_task.sh /usr/bin/launch_awx_task.sh
ADD tools/ansible/roles/dockerfile/files/launch_awx_rsyslog.sh /usr/bin/launch_awx_rsyslog.sh
ADD tools/scripts/rsyslog-4xx-recovery /usr/bin/rsyslog-4xx-recovery
ADD _build/supervisor_web.conf /etc/supervisord_web.conf
ADD _build/supervisor_task.conf /etc/supervisord_task.conf
ADD _build/supervisor_rsyslog.conf /etc/supervisord_rsyslog.conf
ADD tools/scripts/forge-python /usr/bin/forge-python
RUN ln -s /usr/bin/forge-python /usr/bin/awx-python

# Pre-create directories
RUN for dir in \
      /var/lib/awx \
      /var/lib/awx/rsyslog \
      /var/lib/awx/rsyslog/conf.d \
      /var/lib/awx/.local/share/containers/storage \
      /var/run/awx-rsyslog \
      /var/log/nginx \
      /var/lib/pgsql \
      /var/run/supervisor \
      /var/run/awx-receptor \
      /var/lib/nginx ; \
    do mkdir -m 0775 -p $dir ; chmod g+rwx $dir ; chgrp root $dir ; done && \
    for file in \
      /etc/subuid \
      /etc/subgid \
      /etc/group \
      /etc/passwd \
      /var/lib/awx/rsyslog/rsyslog.conf ; \
    do touch $file ; chmod g+rw $file ; chgrp root $file ; done

RUN ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

ENV HOME="/var/lib/awx"

EXPOSE 8013

ENTRYPOINT ["dumb-init", "--"]
VOLUME /var/lib/nginx
VOLUME /var/lib/awx/.local/share/containers
