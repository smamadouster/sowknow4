#!/usr/bin/env python3
"""
DNS validation module for Telegram bot pre-flight checks
"""
import socket
import subprocess
import platform
import json
from typing import Dict, Tuple, List
import datetime

def check_dns_resolution(hostname: str = "api.telegram.org") -> Tuple[bool, str]:
    """
    Validate DNS resolution for critical services
    
    Args:
        hostname: Hostname to resolve
        
    Returns:
        Tuple[bool, str]: Success status and detailed message
    """
    try:
        ip_address = socket.gethostbyname(hostname)
        return True, f"✓ DNS resolved {hostname} -> {ip_address}"
    except socket.gaierror as e:
        return False, f"✗ DNS resolution failed: {str(e)}"
    except Exception as e:
        return False, f"✗ Unexpected error: {str(e)}"

def analyze_dns_config() -> Dict:
    """Analyze current DNS configuration"""
    config = {
        "platform": platform.system(),
        "dns_servers": [],
        "resolv_conf": None,
        "docker_dns": None,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    # Check /etc/resolv.conf (Linux/Docker)
    try:
        with open('/etc/resolv.conf', 'r') as f:
            content = f.read()
            config['resolv_conf'] = content
            # Extract nameservers
            for line in content.split('\n'):
                if line.startswith('nameserver'):
                    config['dns_servers'].append(line.split()[1])
    except:
        pass
    
    # Check Docker DNS settings
    try:
        result = subprocess.run(
            ['cat', '/etc/docker/daemon.json'], 
            capture_output=True, 
            text=True
        )
        if result.returncode == 0 and result.stdout:
            config['docker_dns'] = json.loads(result.stdout).get('dns', [])
    except:
        pass
    
    return config

def validate_before_startup() -> bool:
    """
    Pre-flight check - must pass before bot starts
    """
    print("🔍 Running pre-flight DNS validation...")
    
    # Check critical endpoints
    endpoints = [
        "api.telegram.org",
        "google.com",  # General internet connectivity
        "1.1.1.1"      # Cloudflare DNS (if using IP directly)
    ]
    
    all_passed = True
    for endpoint in endpoints:
        success, message = check_dns_resolution(endpoint)
        print(message)
        if not success:
            all_passed = False
    
    if not all_passed:
        config = analyze_dns_config()
        print("\n📊 DNS Configuration Analysis:")
        print(json.dumps(config, indent=2))
        
    return all_passed

if __name__ == "__main__":
    # Run validation when script executed directly
    if validate_before_startup():
        print("\n✅ DNS validation passed")
        exit(0)
    else:
        print("\n❌ DNS validation failed")
        exit(1)
