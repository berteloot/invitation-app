import os

port = int(os.getenv("PORT", 10000))
bind = f"0.0.0.0:{port}"
workers = 2
timeout = 120 