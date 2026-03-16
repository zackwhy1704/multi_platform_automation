#!/bin/bash
# =============================================================
# Local Test Server — run this in your terminal
# Uses fixed ngrok domain (never changes)
# =============================================================

cd "$(dirname "$0")"

NGROK_DOMAIN="charity-unappointed-fred.ngrok-free.dev"

echo ""
echo "============================================"
echo "  AI Automation Service — Local Dev Server"
echo "============================================"
echo ""

# Kill any existing processes
pkill -f "local_test.py" 2>/dev/null
pkill -f "pyngrok" 2>/dev/null
pkill -f "ngrok" 2>/dev/null
sleep 1

# Start ngrok with fixed domain in background
echo "[1/2] Starting ngrok tunnel (fixed domain)..."
python3 -c "
from pyngrok import ngrok
import signal, sys

tunnel = ngrok.connect(8000, 'http', domain='$NGROK_DOMAIN')
print('')
print('  NGROK URL:    ' + tunnel.public_url)
print('  WEBHOOK URL:  ' + tunnel.public_url + '/webhook')
print('')
print('  Domain is FIXED — no need to update Meta webhook config')
print('')
sys.stdout.flush()
signal.pause()
" &
NGROK_PID=$!
sleep 5

echo "[2/2] Starting bot server..."
echo ""
echo "============================================"
echo "  Server is running — logs below"
echo "  Webhook: https://$NGROK_DOMAIN/webhook"
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

# Run the bot server in foreground (shows live logs)
python3 local_test.py

# Cleanup on exit
kill $NGROK_PID 2>/dev/null
pkill -f "ngrok" 2>/dev/null
