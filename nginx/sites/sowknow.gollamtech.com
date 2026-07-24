# Rate limit for the login endpoint: logins are rare for legitimate users,
# and each attempt costs a bcrypt round (~250ms CPU). Broken clients have
# hammered this endpoint in a login->403->login loop (2026-07-24).
limit_req_zone $binary_remote_addr zone=sowknow_login_limit:10m rate=10r/m;

server {
    listen 80;
    listen [::]:80;
    server_name sowknow.gollamtech.com;

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Exact match so the limiter only applies to login, not the whole API
    location = /api/v1/auth/login {
        limit_req zone=sowknow_login_limit burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
        proxy_cache off;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
        proxy_cache off;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
