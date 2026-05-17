#!/bin/bash
# Start the Leave Management System
cd "$(dirname "$0")"
pip3 install flask flask-cors --quiet

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   📋  Leave Management System                 ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║  Staff Form  →  http://localhost:5050/         ║"
echo "║  Dashboard   →  http://localhost:5050/dashboard║"
echo "║  Settings    →  http://localhost:5050/settings ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

python3 app.py
