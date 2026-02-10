#!/bin/bash

echo "=== SOWKNOW4 Setup ==="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose is not installed. Installing..."
    curl -L "https://github.com/docker/compose/releases/download/v2.23.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Create data directories
mkdir -p data/{public,confidential,backups}

# Create SSL directory for nginx
mkdir -p nginx/ssl

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit the .env file with your actual values:"
echo "   nano .env"
echo ""
echo "2. Build and start the containers:"
echo "   docker-compose build"
echo "   docker-compose up -d"
echo ""
echo "3. Check the logs:"
echo "   docker-compose logs -f"
echo ""
echo "4. Access the application:"
echo "   Frontend: http://localhost:3000"
echo "   Backend API: http://localhost:8000"
echo "   API Docs: http://localhost:8000/api/docs"
