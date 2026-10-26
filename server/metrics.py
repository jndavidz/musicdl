'''
Function:
    Prometheus metrics for kw-qq-music-api: per-endpoint request counter + latency
    histogram, parser health gauges, cache hit-rate gauges. Scraped via GET /metrics
    (plain exposition format, no envelope).
Notes:
    One Metrics instance per app with its own CollectorRegistry — multiple in-process
    apps (offline smoke starts two) must not collide on the global default registry.
    Endpoint labels use the route template ('/{source}/search'), never the raw path,
    so dynamic segments can't blow up label cardinality; unroutable paths → 'other'.
'''
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter('kwqq_requests_total', 'HTTP requests by endpoint and status code',
                                ['endpoint', 'status'], registry=self.registry)
        self.latency = Histogram('kwqq_request_latency_seconds', 'End-to-end request latency',
                                 ['endpoint'], registry=self.registry)
        self.parser_up = Gauge('kwqq_parser_up', '1 = parser usable, 0 = in cooldown',
                               ['parser'], registry=self.registry)
        self.parser_fail_streak = Gauge('kwqq_parser_fail_streak', 'Consecutive parser failures',
                                        ['parser'], registry=self.registry)
        self.cache_hit_rate = Gauge('kwqq_cache_hit_rate', 'Cache hit rate 0..1 (no samples yet -> 0)',
                                    ['cache'], registry=self.registry)
        self.cache_items = Gauge('kwqq_cache_items', 'Entries currently held by the cache',
                                 ['cache'], registry=self.registry)

    def observe(self, endpoint: str, status: int, seconds: float) -> None:
        self.requests.labels(endpoint, str(status)).inc()
        self.latency.labels(endpoint).observe(seconds)

    '''refresh gauges from live app state (call at scrape time; gauges only exist for
       label values actually seen — parsers never invoked simply emit no series)'''
    def sync_from_state(self, state) -> None:
        for name, st in state.health.snapshot().items():
            self.parser_up.labels(name).set(0 if st['cooled_down'] else 1)
            self.parser_fail_streak.labels(name).set(st['fail_streak'])
        caches = {'url': state.url_cache.stats(), 'search': state.search_cache.stats(),
                  'meta': state.meta_cache.stats(), 'lyric': state.lyric_cache.stats()}
        for name, stats in caches.items():
            self.cache_hit_rate.labels(name).set(stats['hit_rate'] or 0)
            self.cache_items.labels(name).set(stats['items'])

    def render(self) -> bytes:
        return generate_latest(self.registry)
