#!/usr/bin/env python3
"""
Ngrok tunnel script for Sales Dialer POC
This script starts an ngrok tunnel and optionally updates the BASE_URL in .env
"""

import subprocess
import sys
import os
import time
import requests
from pathlib import Path


def check_ngrok_installed():
    """Check if ngrok is installed"""
    try:
        subprocess.run(["ngrok", "version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_ngrok_url():
    """Get the public ngrok URL from ngrok API"""
    try:
        response = requests.get("http://localhost:4040/api/tunnels", timeout=2)
        if response.status_code == 200:
            data = response.json()
            tunnels = data.get("tunnels", [])
            if tunnels:
                return tunnels[0].get("public_url")
    except (requests.RequestException, KeyError, IndexError):
        pass
    return None


def update_env_file(base_url):
    """Update BASE_URL in .env file"""
    env_file = Path(".env")
    if not env_file.exists():
        print("⚠️  .env file not found. Creating one...")
        env_file.write_text(f"BASE_URL={base_url}\n", encoding="utf-8")
        return
    
    # Read existing .env
    lines = env_file.read_text(encoding="utf-8").splitlines()
    
    # Update or add BASE_URL
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("BASE_URL="):
            new_lines.append(f"BASE_URL={base_url}")
            updated = True
        else:
            new_lines.append(line)
    
    if not updated:
        new_lines.append(f"BASE_URL={base_url}")
    
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"✅ Updated BASE_URL in .env file: {base_url}")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
    update_env = "--update-env" in sys.argv or "-u" in sys.argv
    
    # Static ngrok domain
    ngrok_domain = "sales-dialer-poc.jp.ngrok.io"
    static_url = f"https://{ngrok_domain}"
    
    print("🚀 Sales Dialer POC - Ngrok Tunnel")
    print("=" * 50)
    
    # Check if ngrok is installed
    if not check_ngrok_installed():
        print("❌ Error: ngrok is not installed.")
        print("📥 Install it from: https://ngrok.com/download")
        print("   Or via homebrew: brew install ngrok")
        print("   Or via pip: pip install pyngrok")
        sys.exit(1)
    
    # Check for auth token (required for static domains)
    auth_token = os.getenv("NGROK_AUTH_TOKEN")
    if auth_token:
        print("✅ Ngrok auth token found in environment")
    else:
        print("⚠️  NGROK_AUTH_TOKEN not set (REQUIRED for static domains)")
        print("   Get your token from: https://dashboard.ngrok.com/get-started/your-authtoken")
        print("   Set it: export NGROK_AUTH_TOKEN=your_token")
        response = input("\nContinue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    print(f"\n🌐 Starting ngrok tunnel on port {port}...")
    print(f"📋 Using static domain: {ngrok_domain}")
    print(f"🌐 Static URL: {static_url}")
    print("📋 Waiting for tunnel to be established...")
    print("   (This may take a few seconds)")
    print("\nPress Ctrl+C to stop the tunnel\n")
    
    # Start ngrok in background with static domain
    try:
        ngrok_process = subprocess.Popen(
            ["ngrok", "http", str(port), "--domain", ngrok_domain],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a bit for ngrok to start
        time.sleep(3)
        
        # Get the public URL (should match static domain)
        max_retries = 10
        for _ in range(max_retries):
            url = get_ngrok_url()
            if url:
                # Verify it matches our static domain
                if ngrok_domain not in url:
                    print(f"⚠️  Warning: Expected {static_url} but got {url}")
                    url = static_url
                else:
                    url = static_url  # Use static URL regardless
                
                print("=" * 50)
                print("✅ Tunnel established!")
                print(f"🌐 Static URL: {url}")
                print("=" * 50)
                print("\n📝 Twilio webhook URLs (already configured):")
                print(f"   {url}/api/voice/customer-queue")
                print(f"   {url}/api/voice/amd-status")
                print(f"   {url}/api/voice/status")
                print(f"   {url}/api/voice/customer-join-conference")
                print(f"\n✅ BASE_URL is already set to: {url}")
                print("   (configured in app/config.py)")
                
                if update_env:
                    update_env_file(url)
                else:
                    print("\n💡 Tip: BASE_URL is already configured in app/config.py")
                    print("   Run with --update-env to also update .env file if needed")
                
                print("\n⏳ Tunnel is running. Press Ctrl+C to stop...\n")
                
                # Keep running until interrupted
                try:
                    ngrok_process.wait()
                except KeyboardInterrupt:
                    print("\n\n🛑 Stopping ngrok tunnel...")
                    ngrok_process.terminate()
                    ngrok_process.wait()
                    print("✅ Tunnel stopped")
                    break
                break
            else:
                time.sleep(1)
        else:
            print("⚠️  Could not get ngrok URL. Check if ngrok is running correctly.")
            print("   You can manually check: http://localhost:4040")
            ngrok_process.terminate()
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping ngrok tunnel...")
        if 'ngrok_process' in locals():
            ngrok_process.terminate()
        print("✅ Tunnel stopped")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

