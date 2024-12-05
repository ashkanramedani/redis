from prometheus_client import Counter, Summary, make_asgi_app

REQUEST_COUNT = Counter("request_count", "Total number of requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Summary("request_latency_seconds", "Request latency in seconds", ["endpoint"])

metrics_app = make_asgi_app()
