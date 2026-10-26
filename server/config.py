'''
Function:
    kw-qq-music-api server settings (env-overridable, constructible for tests)
Author:
    Derived from musicdl hifi branch, api-server line
'''
import functools
import ipaddress
import os


def _networks_from(raw: str) -> list:
    out = []
    for part in raw.split(','):
        part = part.strip()
        if part:
            out.append(ipaddress.ip_network(part))
    return out


class Settings:
    '''All env reads happen at construction time. `env` (dict) merges over
       os.environ so tests can build isolated settings: Settings(env={'API_KEY': 'k'}).
       Construction may raise on malformed values (e.g. TRUSTED_NETWORKS) — same
       fail-fast behavior the module-level singleton always had at import time.'''

    def __init__(self, env: dict = None):
        e = os.environ if not env else {**os.environ, **env}
        # server
        self.host: str = e.get('KWQQ_HOST', '0.0.0.0')
        self.port: int = int(e.get('KWQQ_PORT', '3003'))
        # quality gate: lossless tiers (flac/hires) are disabled by default (plugin scenario caps at 320kbps)
        self.enable_lossless: bool = e.get('ENABLE_LOSSLESS', 'false').lower() in {'1', 'true', 'yes', 'on'}
        # caches (seconds)
        self.url_cache_ttl: int = int(e.get('URL_CACHE_TTL', '600'))
        self.search_cache_ttl: int = int(e.get('SEARCH_CACHE_TTL', '300'))
        self.meta_cache_ttl: int = int(e.get('META_CACHE_TTL', '86400'))
        # upstream probing
        self.tester_timeout: tuple = tuple(int(x) for x in e.get('TESTER_TIMEOUT', '3,8').split(','))
        self.hard_timeout_s: float = float(e.get('HARD_TIMEOUT_S', '35'))
        # concurrency
        self.max_concurrency_per_source: int = int(e.get('MAX_CONCURRENCY', '4'))
        # parser health (cooldown skipping for dead parsers)
        self.parser_fail_threshold: int = int(e.get('PARSER_FAIL_THRESHOLD', '3'))
        self.parser_cooldown_s: int = int(e.get('PARSER_COOLDOWN_S', '300'))
        # search defaults
        self.search_size_default: int = int(e.get('SEARCH_SIZE_DEFAULT', '20'))
        self.search_size_max: int = int(e.get('SEARCH_SIZE_MAX', '50'))
        # service-level api key (empty = disabled). Compatible with the kugou-plugin pattern:
        # send 'Authorization: Basic base64(KEY + ":")' or 'X-API-Key: KEY'. /healthz is always exempt.
        self.api_key: str = e.get('API_KEY', '').strip()
        # LAN bypass: requests originating from these networks skip the api key check
        # (direct intranet access to the container port). NOTE: the Lucky router IP must be
        # listed in untrusted_hosts, otherwise external traffic relayed through it is trusted too.
        self.trusted_networks: list = _networks_from(e.get('TRUSTED_NETWORKS', '127.0.0.0/8,10.10.10.0/24,172.16.0.0/12,192.168.0.0/16'))
        self.untrusted_hosts: list = [h.strip() for h in e.get('UNTRUSTED_HOSTS', '10.10.10.1').split(',') if h.strip()]
        # sibling api containers on the NAS (their long-lived logins power netease/kugou resolution)
        self.ncm_api_base: str = e.get('NCM_API_BASE', 'http://10.10.10.2:3000')
        self.kugou_api_base: str = e.get('KUGOU_API_BASE', 'http://10.10.10.2:3001')
        self.kugou_token_file: str = e.get('KUGOU_TOKEN_FILE', '/app/secrets/kugou_token.json')
        self.netease_cookie_file: str = e.get('NETEASE_COOKIE_FILE', '/app/secrets/netease_cookie.txt')
        self.bili_sessdata: str = e.get('BILI_SESSDATA', '').strip()  # bilibili account cookie; unlocks Hi-Res/Dolby audio tracks
        self.cookie_refresh_s: int = int(e.get('COOKIE_REFRESH_S', '1800'))


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
# single source of truth for the enabled-source registry: server/adapters/__init__.py.
# enable/disable a source by editing ADAPTER_CLASSES only (one place).
from .adapters import ADAPTER_CLASSES  # noqa: E402  (no cycle: adapters never import config)
SOURCES = tuple(ADAPTER_CLASSES)
