# Gunicorn configuration file
import os

# Use PORT environment variable from Render, fallback to 10000
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 2
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2
max_requests = 1000
max_requests_jitter = 50
preload_app = True
