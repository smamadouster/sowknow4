FROM python:3.12-slim

# Install Docker CLI (for docker exec probes) + postgresql-client (for psql probes)
# curl + gnupg needed for Docker's apt repo; util-linux for flock
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates \
        util-linux \
        postgresql-client && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* && \
    python -m ensurepip --default-pip && \
    python -m pip install --no-cache-dir --upgrade pip

RUN groupadd -r appuser && useradd -r -g appuser -u 1001 appuser && \
    groupadd -g 988 docker && usermod -aG docker appuser

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -e . && \
    chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["guardian-hc", "run"]
CMD ["/config/guardian-hc.yml"]
