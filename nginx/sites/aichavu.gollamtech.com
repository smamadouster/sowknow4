server {
    listen 80;
    listen [::]:80;
    server_name aichavu.gollamtech.com;

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 503 '{"status":"maintenance","message":"AiChavu is under maintenance"}';
        add_header Content-Type application/json;
    }
}
