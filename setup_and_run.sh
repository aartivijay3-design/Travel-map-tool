#!/usr/bin/env bash
# Luxury Travel Map Tool — setup & launch (macOS / Linux)
set -e

echo ""
echo " ============================================"
echo "  Luxury Travel Map Generator"
echo " ============================================"
echo ""

# Create venv if needed
if [ ! -f "venv/bin/activate" ]; then
    echo " Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo " Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r backend/requirements.txt --quiet

echo ""
echo " Starting server at http://localhost:5000"
echo " Press Ctrl+C to stop."
echo ""

cd backend
python app.py
