import os

port = int(os.getenv("PORT", 10000))
bind = f"0.0.0.0:{port}"
workers = 1
timeout = 120
capture_output = True
enable_stdio_inheritance = True
log_level = "info"
accesslog = "-"
errorlog = "-" 