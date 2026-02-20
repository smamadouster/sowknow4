#!/bin/bash
# SOWKNOW SSL Certificate Auto-Renewal Script
# Handles initial setup and automatic renewal with cron
# Domain: sowknow.gollamtech.com

set -e

DOMAIN="sowknow.gollamtech.com"
EMAIL="admin@gollamtech.com"
PROJECT_DIR="/var/docker/sowknow4"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/sowknow-ssl.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} [$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} [$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} [$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to check if certificate exists
check_certificate_exists() {
    docker run --rm -v certbot-conf:/etc/letsencrypt alpine:latest \
        test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" 2>/dev/null
}

# Function to get certificate expiry date
get_expiry_date() {
    docker run --rm -v certbot-conf:/etc/letsencrypt alpine:latest sh -c \
        "cat /etc/letsencrypt/live/$DOMAIN/fullchain.pem 2>/dev/null" | \
        openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo ""
}

# Function to check if port 80 is available
check_port_80() {
    if netstat -tuln | grep -q ':80 '; then
        return 1
    fi
    return 0
}

# Function to stop containers using port 80
stop_port_80_containers() {
    log "Checking for containers using port 80..."
    local containers=$(docker ps --format "{{.Names}}" --filter "publish=80" 2>/dev/null)
    if [ -n "$containers" ]; then
        warning "Found containers using port 80: $containers"
        log "Stopping containers temporarily for certificate renewal..."
        echo "$containers" | xargs -r docker stop
        sleep 2
    fi
}

# Function to restart containers that were stopped
restart_containers() {
    log "Restarting previously stopped containers..."
    docker ps -a --filter "exited=0" --format "{{.Names}}" | \
        grep -E "(nginx|sowknow)" | xargs -r docker start
}

# Function to request new certificate
request_certificate() {
    log "Requesting new SSL certificate for $DOMAIN..."

    # Create certbot directories
    mkdir -p "$PROJECT_DIR/certbot-www"

    # Stop any containers using port 80
    stop_port_80_containers

    # Request certificate using standalone mode (most reliable)
    if docker run --rm -it \
        -p 80:80 \
        -v certbot-www:/var/www/certbot \
        -v certbot-conf:/etc/letsencrypt \
        certbot/certbot certonly --standalone \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        -d "$DOMAIN"; then

        success "Certificate obtained successfully!"
        copy_certificates
    else
        error "Failed to obtain certificate"
        restart_containers
        return 1
    fi

    restart_containers
    return 0
}

# Function to copy certificates to nginx ssl directory
copy_certificates() {
    log "Copying certificates to nginx ssl directory..."

    mkdir -p "$PROJECT_DIR/nginx/ssl"

    docker run --rm \
        -v certbot-conf:/letsencrypt:ro \
        -v "$PROJECT_DIR/nginx/ssl:/ssl" \
        alpine:latest sh -c "
            cp /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/ &&
            cp /letsencrypt/live/$DOMAIN/privkey.pem /ssl/ &&
            chmod 644 /ssl/fullchain.pem /ssl/privkey.pem &&
            ls -la /ssl/
        "

    success "Certificates copied to nginx/ssl/"
}

# Function to renew certificate
renew_certificate() {
    log "Attempting to renew SSL certificate..."

    # Try webroot renewal first (doesn't require stopping nginx)
    if docker run --rm \
        -v certbot-www:/var/www/certbot \
        -v certbot-conf:/etc/letsencrypt \
        certbot/certbot renew --webroot --webroot-path=/var/www/certbot --quiet; then

        success "Certificate renewed successfully via webroot!"
        copy_certificates
        reload_nginx
        return 0
    fi

    warning "Webroot renewal failed, trying standalone mode..."

    # Fall back to standalone mode
    stop_port_80_containers

    if docker run --rm -it \
        -p 80:80 \
        -v certbot-www:/var/www/certbot \
        -v certbot-conf:/etc/letsencrypt \
        certbot/certbot renew --standalone; then

        success "Certificate renewed successfully via standalone!"
        copy_certificates
        restart_containers
        reload_nginx
        return 0
    fi

    error "Certificate renewal failed"
    restart_containers
    return 1
}

# Function to reload nginx
reload_nginx() {
    log "Reloading nginx to apply new certificates..."
    if docker ps | grep -q "sowknow-nginx"; then
        docker exec sowknow-nginx nginx -s reload 2>/dev/null || \
            docker restart sowknow-nginx
        success "Nginx reloaded"
    else
        warning "sowknow-nginx container not running"
    fi
}

# Function to setup cron job for auto-renewal
setup_cron() {
    log "Setting up cron job for automatic renewal..."

    local cron_job="0 3 * * * $SCRIPT_DIR/ssl-auto-renewal.sh renew >> /var/log/sowknow-ssl-cron.log 2>&1"

    # Remove existing cron job if present
    (crontab -l 2>/dev/null | grep -v "ssl-auto-renewal.sh") | crontab -

    # Add new cron job
    (crontab -l 2>/dev/null; echo "$cron_job") | crontab -

    success "Cron job added: Daily at 3:00 AM"
    log "Current cron jobs:"
    crontab -l | grep ssl-auto-renewal
}

# Function to check certificate status
check_status() {
    log "Checking SSL certificate status for $DOMAIN..."

    if ! check_certificate_exists; then
        error "No certificate found for $DOMAIN"
        log "Run: $0 setup"
        return 1
    fi

    local expiry=$(get_expiry_date)
    if [ -z "$expiry" ]; then
        error "Could not read certificate expiry date"
        return 1
    fi

    local expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null || date -j -f "%b %d %H:%M:%S %Y %Z" "$expiry" +%s)
    local now_epoch=$(date +%s)
    local days_until=$(( (expiry_epoch - now_epoch) / 86400 ))

    success "Certificate found!"
    log "Expiry date: $expiry"
    log "Days until expiry: $days_until"

    if [ $days_until -lt 7 ]; then
        error "CRITICAL: Certificate expires in less than 7 days!"
        return 1
    elif [ $days_until -lt 30 ]; then
        warning "Certificate expires in less than 30 days - renewal recommended"
    fi

    # Check certificate files
    log "Certificate files:"
    ls -la "$PROJECT_DIR/nginx/ssl/" 2>/dev/null || warning "No files in nginx/ssl/"

    # Check nginx status
    log "Nginx container status:"
    docker ps --filter "name=sowknow-nginx" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

    return 0
}

# Function to diagnose SSL issues
diagnose() {
    log "Running SSL diagnostics..."
    echo "========================================"

    # Check certificate existence
    echo -e "\n1. Certificate Status:"
    if check_certificate_exists; then
        success "Certificate exists in certbot volume"
        check_status
    else
        error "Certificate NOT found"
    fi

    # Check nginx container
    echo -e "\n2. Nginx Container Status:"
    docker ps --filter "name=sowknow-nginx" --format "table {{.Names}}\t{{.Status}}"

    # Check nginx logs
    echo -e "\n3. Recent Nginx Errors:"
    docker logs --tail 10 sowknow-nginx 2>&1 | grep -E "(error|emerg|fatal)" || log "No recent errors"

    # Check port 443
    echo -e "\n4. Port 443 Usage:"
    netstat -tuln | grep 443 || warning "Port 443 not listening"

    # Check backend container
    echo -e "\n5. Backend Container Status:"
    docker ps --filter "name=sowknow-backend" --format "table {{.Names}}\t{{.Status}}"

    # Check Docker network
    echo -e "\n6. Docker Network:"
    docker network ls | grep sowknow
    docker network inspect sowknow-net 2>/dev/null | grep -A5 "Containers" || warning "sowknow-net not found"

    echo "========================================"
}

# Main command handler
case "${1:-setup}" in
    setup|new)
        log "Starting SSL certificate setup..."
        if check_certificate_exists; then
            warning "Certificate already exists. Use 'renew' to renew or 'force-renew' to force renewal."
            check_status
            exit 0
        fi
        request_certificate
        setup_cron
        success "SSL setup complete!"
        ;;

    renew)
        if ! check_certificate_exists; then
            error "No certificate found. Run setup first."
            request_certificate
            exit $?
        fi
        renew_certificate
        ;;

    force-renew)
        warning "Forcing certificate renewal..."
        request_certificate
        ;;

    status)
        check_status
        exit $?
        ;;

    diagnose)
        diagnose
        ;;

    cron)
        setup_cron
        ;;

    copy)
        copy_certificates
        reload_nginx
        ;;

    help|--help|-h)
        echo "SOWKNOW SSL Certificate Manager"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  setup       - Initial certificate setup (default)"
        echo "  renew       - Renew existing certificate"
        echo "  force-renew - Force new certificate request"
        echo "  status      - Check certificate status"
        echo "  diagnose    - Run full SSL diagnostics"
        echo "  cron        - Setup automatic renewal cron job"
        echo "  copy        - Copy certs to nginx and reload"
        echo "  help        - Show this help"
        echo ""
        echo "Examples:"
        echo "  $0 setup       # First time setup"
        echo "  $0 renew       # Manual renewal"
        echo "  $0 status      # Check certificate expiry"
        ;;

    *)
        error "Unknown command: $1"
        echo "Run '$0 help' for usage"
        exit 1
        ;;
esac
