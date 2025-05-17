import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Gunicorn config
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

# Worker configuration
worker_class = "sync"
worker_connections = 1000
keepalive = 5

# Logging configuration
logger_class = "gunicorn.glogging.Logger"
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": "ext://sys.stdout"
        }
    },
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
            "qualname": "gunicorn.error"
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
            "qualname": "gunicorn.access"
        },
        "app": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
            "qualname": "app"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"]
    }
} 