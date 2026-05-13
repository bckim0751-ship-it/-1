#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

if ! command -v pip &> /dev/null; then
  echo "pip not found"
  exit 1
fi

echo "Installing dependencies..."
pip install -r backend/requirements.txt -q

echo "Starting server at http://localhost:8000"
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
