FROM python:3.12-slim

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
