#!/bin/bash
# Startup script for Azure App Service

# Install dependencies
echo "Installing dependencies..."
pip install --no-cache-dir -r requirements.txt

# Run database initialization (tables will be created on first request)
echo "Starting Flask application..."

# Start with gunicorn
exec gunicorn --bind=0.0.0.0:${PORT:-8000} --workers=2 --threads=4 --timeout=120 app:app