# Build on the same host as the locally prepared, versioned Codex image.
# Record both base and output image IDs in the deployment evidence.
ARG CODEX_IMAGE=3dbench-codex:0.163.0
FROM ${CODEX_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git python3 python3-venv rsync \
    libvulkan1 vulkan-tools libasound2 libx11-6 libxext6 libxrandr2 \
    libxcursor1 libxi6 libxss1 libxcomposite1 libxdamage1 libxfixes3 \
    libxrender1 libxcb1 libxkbcommon0 libglib2.0-0 libnss3 \
    libfontconfig1 libfreetype6 libicu72 libssl3 libdbus-1-3 netbase zlib1g \
    libatk1.0-0 libatk-bridge2.0-0 libdrm2 libgbm1 libegl1 libgl1 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*
ARG AGENT_UID=20018
ARG AGENT_GID=20018
RUN test "${AGENT_UID}" -gt 0 && \
    (getent group "${AGENT_GID}" || groupadd -g "${AGENT_GID}" agent) && \
    useradd -m -o -u "${AGENT_UID}" -g "${AGENT_GID}" -s /bin/bash agent && \
    mkdir -p /workspace && chown "${AGENT_UID}:${AGENT_GID}" /workspace
ENV HOME=/home/agent \
    XDG_RUNTIME_DIR=/tmp/ue-runtime \
    UE_LocalDataCachePath=/workspace/.cache/ue \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute
USER agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
