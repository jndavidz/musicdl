'''
Function:
    kw-qq-music-api server settings (env-overridable)
Author:
    Derived from musicdl hifi branch, api-server line
'''
import ipaddress
import os


def _bool(key: str, default: str = 'false') -> bool:
    return os.getenv(key, default).lower() in {'1', 'true', 'yes', 'on'}


def _tuple_int(key: str, default: str) -> tuple:
    return tuple(int(x) for x in os.getenv(key, default).split(','))


def _networks(key: str, default: str) -> list:
    out = []
    for raw in os.getenv(key, default).split(','):
        raw = raw.strip()
        if raw:
            out.append(ipaddress.ip_network(raw))
    return out


class Settings:
    # server
    host: str = os.getenv('KWQQ_HOST', '0.0.0.0')
    port: int = int(os.getenv('KWQQ_PORT', '3003'))
    # quality gate: lossless tiers (flac/hires) are disabled by default (plugin scenario caps at 320kbps)
    enable_lossless: bool = _bool('ENABLE_LOSSLESS', 'false')
    # caches (seconds)
    url_cache_ttl: int = int(os.getenv('URL_CACHE_TTL', '600'))
    search_cache_ttl: int = int(os.getenv('SEARCH_CACHE_TTL', '300'))
    meta_cache_ttl: int = int(os.getenv('META_CACHE_TTL', '86400'))
    # upstream probing
    tester_timeout: tuple = _tuple_int('TESTER_TIMEOUT', '3,8')
    hard_timeout_s: float = float(os.getenv('HARD_TIMEOUT_S', '35'))
    # concurrency
    max_concurrency_per_source: int = int(os.getenv('MAX_CONCURRENCY', '4'))
    # parser health (cooldown skipping for dead parsers)
    parser_fail_threshold: int = int(os.getenv('PARSER_FAIL_THRESHOLD', '3'))
    parser_cooldown_s: int = int(os.getenv('PARSER_COOLDOWN_S', '300'))
    # search defaults
    search_size_default: int = int(os.getenv('SEARCH_SIZE_DEFAULT', '20'))
    search_size_max: int = int(os.getenv('SEARCH_SIZE_MAX', '50'))
    # service-level api key (empty = disabled). Compatible with the kugou-plugin pattern:
    # send 'Authorization: Basic base64(KEY + ":")' or 'X-API-Key: KEY'. /healthz is always exempt.
    api_key: str = os.getenv('API_KEY', '').strip()
    # LAN bypass: requests originating from these networks skip the api key check
    # (direct intranet access to the container port). NOTE: the Lucky router IP must be
    # listed in untrusted_hosts, otherwise external traffic relayed through it is trusted too.
    trusted_networks: list = _networks('TRUSTED_NETWORKS', '127.0.0.0/8,10.10.10.0/24,172.16.0.0/12,192.168.0.0/16')
    untrusted_hosts: list = [h.strip() for h in os.getenv('UNTRUSTED_HOSTS', '10.10.10.1').split(',') if h.strip()]


settings = Settings()
SOURCES = ('kuwo', 'qq')

QUALITY_ALIASES = {
    'low': '128k', 'standard': '128k', 'high': '320k', 'super': '320k',
    'auto': 'auto', '320k': '320k', '128k': '128k', 'flac': 'flac', 'hires': 'hires',
}
