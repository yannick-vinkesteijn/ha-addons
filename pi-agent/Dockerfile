ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TERM=xterm-256color

RUN apk add --no-cache \
    bash curl git jq nodejs npm python3 py3-yaml uv nginx openssh-client libstdc++ ncurses \
    vim nano tmux coreutils findutils grep sed gawk ca-certificates \
    openssl ripgrep fd \
    && update-ca-certificates

# ttyd static binary (same approach as the upstream Claude Code add-on)
ARG TARGETARCH
RUN A="${TARGETARCH:-$(apk --print-arch)}"; \
    case "${A}" in \
        arm64|aarch64) TTYD_ARCH="aarch64"; HA_ARCH="aarch64" ;; \
        amd64|x86_64) TTYD_ARCH="x86_64"; HA_ARCH="amd64" ;; \
        *) echo "Unsupported architecture: ${A}" && exit 1 ;; \
    esac && echo "${HA_ARCH}" > /etc/ha-arch && \
    curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors \
        "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${TTYD_ARCH}" -o /usr/bin/ttyd && \
    chmod +x /usr/bin/ttyd

# Pi + MCP adapter. The adapter is installed into a seed dir and copied to the
# persistent agent dir on first start (see run.sh).
ARG PI_VERSION=1.1.0
ENV PI_SEED_DIR=/opt/pi-seed
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent@${PI_VERSION} \
    && mkdir -p ${PI_SEED_DIR} \
    && PI_CODING_AGENT_DIR=${PI_SEED_DIR} pi install npm:pi-mcp-adapter@5.1.0 \
    && PI_CODING_AGENT_DIR=${PI_SEED_DIR} pi install npm:pi-permission-system@0.8.0 \
    && PI_CODING_AGENT_DIR=${PI_SEED_DIR} pi install npm:@juicesharp/rpiv-web-tools@2.12.0 \
    && pi --version

# Home Assistant MCP server
ENV UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install hass-mcp==0.2.0

# Home Assistant CLI
ARG HA_CLI_VERSION=5.2.0
RUN curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors \
        "https://github.com/home-assistant/cli/releases/download/${HA_CLI_VERSION}/ha_$(cat /etc/ha-arch)" \
        -o /usr/local/bin/ha && chmod +x /usr/local/bin/ha

COPY rootfs/root/.tmux.conf /root/.tmux.conf
COPY rootfs/root/.bashrc /root/.bashrc
RUN echo 'source ~/.bashrc' > /root/.profile
COPY rootfs/defaults /opt/defaults
COPY rootfs/etc/nginx/pi-agent.conf /etc/nginx/pi-agent.conf
COPY rootfs/usr/local/lib/pi-agent/ /usr/local/lib/pi-agent/
COPY run.sh /usr/local/bin/run.sh
COPY rootfs/usr/local/bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/run.sh /usr/local/bin/ha-safe-write /usr/local/bin/ha-reload /usr/local/bin/ha-restore

WORKDIR /homeassistant

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:7681/ || exit 1

ENTRYPOINT []
CMD ["/usr/local/bin/run.sh"]

LABEL org.opencontainers.image.title="Home Assistant App: Pi Agent" \
      org.opencontainers.image.description="Pi coding agent with web terminal and HA integration" \
      org.opencontainers.image.source="https://github.com/yannick-vinkesteijn/ha-addons" \
      org.opencontainers.image.licenses="MIT"
