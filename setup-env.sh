#!/bin/bash

echo "=== SOWKNOW4 Environment Setup ==="
echo "WARNING: Never share these values publicly!"
echo ""

# Generate secure passwords if not set
if [ -z "$DATABASE_PASSWORD" ]; then
    DATABASE_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=\n')
    echo "Generated DATABASE_PASSWORD: $DATABASE_PASSWORD"
fi

if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    echo "Generated JWT_SECRET: $JWT_SECRET"
fi

# Create .env file
cat > .env << ENVFILE
# Database
DATABASE_PASSWORD=${DATABASE_PASSWORD}

# JWT Secret
JWT_SECRET=${JWT_SECRET}

# External APIs (YOU MUST SET THESE MANUALLY!)
MOONSHOT_API_KEY=${MOONSHOT_API_KEY:-REPLACE_WITH_YOUR_MOONSHOT_API_KEY}
HUNYUAN_API_KEY=${HUNYUAN_API_KEY:-REPLACE_WITH_YOUR_HUNYUAN_API_KEY}

# Telegram (CREATE NEW BOT!)
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-REPLACE_WITH_YOUR_TELEGRAM_BOT_TOKEN}

# Admin
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@sowknow.local}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-ChangeMe123!}
ADMIN_NAME=${ADMIN_NAME:-System Administrator}

# Local LLM
LOCAL_LLM_URL=http://host.docker.internal:11434

# App Settings
APP_ENV=${APP_ENV:-development}
APP_NAME=SOWKNOW
APP_VERSION=1.0.0

# Security
BCRYPT_ROUNDS=12
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=15
JWT_REFRESH_DAYS=7
RATE_LIMIT_PER_MINUTE=100

# Storage
MAX_FILE_SIZE_MB=50
ALLOWED_FILE_TYPES=pdf,docx,txt,jpg,jpeg,png,tiff,bmp
PUBLIC_STORAGE_PATH=/data/public
CONFIDENTIAL_STORAGE_PATH=/data/confidential

# OCR Settings
HUNYUAN_OCR_MODE=base
OCR_TIMEOUT_SECONDS=30
OCR_MAX_RETRIES=3

# LLM Settings
KIMI_MODEL=moonshot-v1-128k
KIMI_MAX_TOKENS=4096
KIMI_TEMPERATURE=0.1
OLLAMA_MODEL=mistral:7b-instruct
OLLAMA_TIMEOUT_SECONDS=60

# Embedding Model
EMBEDDING_MODEL=intfloat/multilingual-e5-large
EMBEDDING_DIMENSIONS=1024
CHUNK_SIZE=512
CHUNK_OVERLAP=50
ENVFILE

echo ""
echo ".env file created!"
echo ""
echo "NEXT STEPS:"
echo "1. Edit .env and replace all 'REPLACE_WITH_' values"
echo "2. Get new API keys (old ones were compromised)"
echo "3. Run: docker-compose build"
echo "4. Run: docker-compose up -d"
