#!/bin/bash
# Fix for Docker DOCKER-INTERNAL chain blocking inter-container traffic
# This script adds an ACCEPT rule for the 172.23.0.0/16 network
# which is used by sowknow4 containers

# Wait for Docker to be ready
sleep 5

# Check if the rule already exists
if ! iptables -C DOCKER-INTERNAL -s 172.23.0.0/16 -d 172.23.0.0/16 -j ACCEPT 2>/dev/null; then
    echo "Adding iptables rule to allow 172.23.0.0/16 traffic in DOCKER-INTERNAL..."
    iptables -I DOCKER-INTERNAL 1 -s 172.23.0.0/16 -d 172.23.0.0/16 -j ACCEPT
    echo "Rule added successfully"
else
    echo "Rule already exists"
fi

# Also ensure the rule survives Docker restart by adding to /etc/docker-daemon.json or similar
# But since iptables rules are persistent, this should be enough for now