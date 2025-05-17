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
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"' 