FROM cnbcool/default-dev-env:latest

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LANGUAGE=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server curl wget ca-certificates jq procps xclip python3 python3-venv python3-pip \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 libdrm2 libxkbcommon0 \
      libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
      libcairo2 libasound2 libx11-xcb1 libfontconfig1 libx11-6 libxcb1 libxext6 libxshmfence1 \
      libglib2.0-0 libgtk-3-0 libpangocairo-1.0-0 libcairo-gobject2 libgdk-pixbuf-2.0-0 libxss1 \
      libxtst6 fonts-liberation fonts-noto-cjk libgl1-mesa-dri libegl-mesa0 \
    && rm -rf /var/lib/apt/lists/*

# Windows core fonts, same as the ms deployment.
RUN echo "deb http://deb.debian.org/debian trixie contrib" > /etc/apt/sources.list.d/contrib.list \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
    && apt-get update && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f && rm -rf /var/lib/apt/lists/*

RUN set -eux; cd /tmp; \
    wget -q https://github.com/kasmtech/KasmVNC/releases/download/v1.3.3/kasmvncserver_bookworm_1.3.3_amd64.deb; \
    apt-get update; apt-get install -y -f ./kasmvncserver_bookworm_1.3.3_amd64.deb; \
    rm -f kasmvncserver_*.deb; rm -rf /var/lib/apt/lists/*

# mihomo (per-profile proxy chain) and crane (profile archive push/pull to the CNB registry).
RUN set -eux; cd /tmp; \
    curl -fL --retry 3 -o m.gz https://github.com/MetaCubeX/mihomo/releases/download/v1.19.33/mihomo-linux-amd64-v1.19.33.gz; \
    gunzip m.gz; install -m 755 m /usr/local/bin/mihomo; \
    curl -fL --retry 3 -o c.tgz https://github.com/google/go-containerregistry/releases/download/v0.22.1/go-containerregistry_Linux_x86_64.tar.gz; \
    tar -xzf c.tgz crane; install -m 755 crane /usr/local/bin/crane; rm -f c.tgz crane

# CloakBrowser-Manager with remote environment support.
# Bump CACHE_BUST to rebuild with the latest MANAGER_REF commit.
ARG CACHE_BUST=1
ARG MANAGER_REF=feat/remote-environment
RUN echo "building ${CACHE_BUST}"
RUN set -eux; git clone --depth 1 -b ${MANAGER_REF} https://github.com/shellus/CloakBrowser-Manager.git /app; \
    command -v npm || (apt-get update && apt-get install -y --no-install-recommends nodejs npm); \
    python3 -m venv /opt/manager-venv; \
    /opt/manager-venv/bin/pip install --no-cache-dir -r /app/backend/requirements.txt; \
    cd /app/frontend && npm install && npm run build && rm -rf node_modules; \
    test -f /app/frontend/dist/index.html

ENV CLOAKBROWSER_CACHE_DIR=/opt/cloakbrowser-cache
RUN /opt/manager-venv/bin/python -c "from cloakbrowser.download import ensure_binary; print(ensure_binary())"

