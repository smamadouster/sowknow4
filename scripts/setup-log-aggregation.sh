#!/bin/bash
# Set up basic log aggregation for SOWKNOW
# This script configures centralized log collection and rotation

set -e

echo "========================================="
echo "SOWKNOW Log Aggregation Setup"
echo "========================================="

# Create log directories
mkdir -p logs/app logs/celery logs/nginx
mkdir -p logs/archive

# Create Docker Compose override for log collection
cat > docker-compose.logging.yml << 'EOF'
version: '3.8'

services:
  # Fluentd log collector
  fluentd:
    image: fluent/fluentd:v1.16-1
    container_name: sowknow4-fluentd
    volumes:
      - ./fluentd/conf:/fluentd/etc
      - ./logs:/fluentd/log
      - fluentd-data:/fluentd/data
    ports:
      - "24224:24224"
      - "24224:24224/udp"
    networks:
      - sowknow-net
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.25'
    healthcheck:
      test: ["CMD", "fluentd", "--version"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  fluentd-data:

networks:
  sowknow-net:
    external: true
EOF

# Create Fluentd configuration
mkdir -p fluentd/conf

cat > fluentd/conf/fluent.conf << 'EOF'
# Fluentd configuration for SOWKNOW log aggregation

<source>
  @type forward
  @id input_forward
  port 24224
  bind 0.0.0.0
</source>

# Parse JSON logs
<filter **>
  @type parser
  key_name log
  reserve_data true
  <parse>
    @type json
  </parse>
</filter>

# Add hostname to all records
<filter **>
  @type record_transformer
  <record>
    hostname "#{Socket.gethostname}"
  </record>
</filter>

# Output to file with buffering
<match **>
  @type file
  @id output_file
  path /fluentd/log/data./fluentd
  symlink_path /fluentd/log/data/fluentd.log
  <buffer>
    @type file
    path /fluentd/data/buffer
    flush_mode interval
    flush_interval 10s
    chunk_limit_size 5M
  </buffer>
  <format>
    @type json
  </format>
</match>
EOF

# Create log rotation configuration
cat > /etc/logrotate.d/sowknow4 << 'EOF'
/root/development/src/active/sowknow4/logs/**/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
    postrotate
        docker compose exec nginx nginx -s reopen > /dev/null 2>&1 || true
    endscript
}
EOF

echo "✅ Log aggregation configured!"
echo ""
echo "Components installed:"
echo "  - Fluentd log collector"
echo "  - Log rotation configuration"
echo ""
echo "To start log collection:"
echo "  docker compose -f docker-compose.yml -f docker-compose.logging.yml up -d"
echo ""
echo "Log locations:"
echo "  - Application logs: ./logs/app/"
echo "  - Celery logs: ./logs/celery/"
echo "  - Nginx logs: ./logs/nginx/"
echo "  - Archived logs: ./logs/archive/"
EOF

chmod +x scripts/setup-log-aggregation.sh
