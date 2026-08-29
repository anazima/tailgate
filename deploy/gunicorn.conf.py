# tailgate.retoph.com — Django dashboard behind aaPanel nginx.
#
# Port 8100: supplementzone owns 8000 and gcc-academy 8020 on this box; 8100 is
# also this project's reserved dev port, so the number is the same everywhere.
bind = "127.0.0.1:8100"
# Two workers: the box has ~1.9 GB RAM shared with MySQL, Postgres, Redis, nginx,
# aaPanel and two other gunicorn apps. The dashboard has one user.
workers = 2
timeout = 60
graceful_timeout = 30
max_requests = 500
max_requests_jitter = 50
accesslog = "/www/wwwroot/tailgate/logs/gunicorn-access.log"
errorlog = "/www/wwwroot/tailgate/logs/gunicorn-error.log"
loglevel = "info"
