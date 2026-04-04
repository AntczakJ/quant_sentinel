#!/bin/bash
# QUANT SENTINEL - Quick Start Script

echo "🚀 QUANT SENTINEL - Starting Application..."
echo ""

# Terminal 1: Backend API
echo "📡 Starting Backend API on port 8000..."
cd "C:\Users\Jan\PycharmProjects\quant_sentinel"
python api/main.py &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"
sleep 2

# Terminal 2: Frontend
echo ""
echo "🎨 Starting Frontend on port 5173..."
cd "C:\Users\Jan\PycharmProjects\quant_sentinel\frontend"
npm run dev &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"
sleep 2

# Terminal 3: Scanner (optional)
echo ""
echo "🔍 Scanner (optional) - Press Y to start scanner or N to skip:"
read -r -n1 SCANNER_START
echo ""
if [[ $SCANNER_START == "Y" || $SCANNER_START == "y" ]]; then
    echo "Starting Scanner..."
    cd "C:\Users\Jan\PycharmProjects\quant_sentinel"
    python run.py &
    SCANNER_PID=$!
    echo "✅ Scanner started (PID: $SCANNER_PID)"
else
    echo "⏭️  Scanner skipped. You can start it later manually."
fi

echo ""
echo "======================================"
echo "🚀 QUANT SENTINEL - Started!"
echo "======================================"
echo ""
echo "Frontend: http://localhost:5173"
echo "Backend:  http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all processes..."
wait

