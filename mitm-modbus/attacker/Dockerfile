FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ettercap-text-only \
        tcpdump \
        net-tools \
        iproute2 \
        iptables \
        nmap \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ttyd has no Debian package; its GitHub releases publish prebuilt binaries
# per architecture, so pick the right one instead of hardcoding x86_64 -
# this image needs to run on the Raspberry Pi, not just an x86 dev host.
ARG TTYD_VERSION=1.7.7
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
        amd64) TTYD_ARCH=x86_64 ;; \
        arm64) TTYD_ARCH=aarch64 ;; \
        armhf) TTYD_ARCH=armhf ;; \
        *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/ttyd \
        "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}"; \
    chmod +x /usr/local/bin/ttyd

WORKDIR /root
# Build context is the mitm-modbus/ directory (see docker-compose.yml),
# not attacker/, so these existing shared filter files can be copied in
# without duplicating them into this subdirectory.
COPY etter.filter.modbus etter.filter.modbuscomp ./
COPY attacker/README.md ./README.md

EXPOSE 7681
# -W enables writable/interactive mode (participants can type, not just
# view) - no auth by design, matching audit-sidecar's write panel: this
# box exists specifically so participants can run commands.
CMD ["ttyd", "-W", "-p", "7681", "bash"]
