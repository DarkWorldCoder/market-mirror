"""\n配置管理\n统一从项目根目录的 .env 文件加载配置\n"""

import ipaddress
import os
import re
import secrets
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    # No hard-coded fallback: without SECRET_KEY a random per-process key is used
    # (development only; production refuses to start without an explicit key).
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    # LLM_PROVIDER=claude (default) uses Anthropic's OpenAI-compatible endpoint.
    # LLM_PROVIDER=gemini uses Google Gemini's OpenAI-compatible endpoint.
    # Set LLM_PROVIDER=openai to use OpenAI or any other OpenAI-format provider.
    # Set LLM_POOL=claude,openai,gemini (or LLM_POOL=auto) to pool multiple providers concurrently.
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'claude').strip().lower()
    LLM_POOL = os.environ.get('LLM_POOL', '').strip()
    LLM_API_KEY = (
        os.environ.get('LLM_API_KEY')
        or (os.environ.get('ANTHROPIC_API_KEY') if LLM_PROVIDER == 'claude' else None)
        or ((os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')) if LLM_PROVIDER == 'gemini' else None)
        or (os.environ.get('OPENAI_API_KEY') if LLM_PROVIDER == 'openai' else None)
    )
    LLM_BASE_URL = os.environ.get(
        'LLM_BASE_URL',
        'https://api.anthropic.com/v1/'
        if LLM_PROVIDER == 'claude'
        else (
            'https://generativelanguage.googleapis.com/v1beta/openai/'
            if LLM_PROVIDER == 'gemini'
            else 'https://api.openai.com/v1'
        ),
    )
    LLM_MODEL_NAME = os.environ.get(
        'LLM_MODEL_NAME',
        'claude-haiku-4-5'
        if LLM_PROVIDER == 'claude'
        else ('gemini-2.5-flash' if LLM_PROVIDER == 'gemini' else 'gpt-4o-mini'),
    )
    
    # Memory / knowledge-graph backend
    # MEMORY_BACKEND=local (default): free SQLite graph built with the configured LLM,
    #   hybrid BM25 + local-embedding search.
    # MEMORY_BACKEND=cognee: Cognee (open source) extraction/search via a sidecar
    #   process in its own venv (see backend/memory_sidecar/cognee_server.py).
    # MEMORY_BACKEND=zep: hosted Zep Cloud (legacy, requires ZEP_API_KEY).
    MEMORY_BACKEND = (os.environ.get('MEMORY_BACKEND') or 'local').strip().lower()
    MEMORY_BACKENDS = ('local', 'cognee', 'zep')
    # Local embeddings (fastembed, ONNX on CPU). Falls back to BM25 when unavailable.
    MEMORY_EMBEDDINGS = os.environ.get('MEMORY_EMBEDDINGS', 'true').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    MEMORY_EMBED_MODEL = (
        os.environ.get('MEMORY_EMBED_MODEL')
        or 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    ).strip()
    MEMORY_EMBED_CACHE_DIR = os.environ.get('MEMORY_EMBED_CACHE_DIR') or os.environ.get(
        'FASTEMBED_CACHE_PATH'
    ) or os.path.abspath(os.path.join(os.path.dirname(__file__), '../uploads/models'))
    # Same-type entities whose names embed at least this similar are merged.
    MEMORY_ENTITY_SIMILARITY = float(os.environ.get('MEMORY_ENTITY_SIMILARITY', '0.9'))
    # Minimum query/document cosine for a semantic (embedding) search hit.
    MEMORY_MIN_SIMILARITY = float(os.environ.get('MEMORY_MIN_SIMILARITY', '0.3'))
    # Characters of one episode sent to the extraction LLM (longer text is truncated).
    LOCAL_GRAPH_MAX_EPISODE_CHARS = int(os.environ.get('LOCAL_GRAPH_MAX_EPISODE_CHARS', '6000'))
    # Cognee sidecar (MEMORY_BACKEND=cognee)
    COGNEE_SIDECAR_URL = (os.environ.get('COGNEE_SIDECAR_URL') or 'http://127.0.0.1:8765').rstrip('/')
    COGNEE_SIDECAR_TIMEOUT = float(os.environ.get('COGNEE_SIDECAR_TIMEOUT', '900'))
    # Bookkeeping DB (graphs, episodes, batches, mirrored nodes/edges) for cognee.
    COGNEE_GRAPH_DB = os.environ.get('COGNEE_GRAPH_DB') or os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../uploads/cognee_graph.db')
    )
    # Episodes sent to one cognee add+cognify run.
    COGNEE_INGEST_BATCH = int(os.environ.get('COGNEE_INGEST_BATCH', '20'))
    LOCAL_GRAPH_DB = os.environ.get('LOCAL_GRAPH_DB') or os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../uploads/local_graph.db')
    )
    # Run LLM entity extraction on simulation activity episodes (costly; off by default).
    MEMORY_EXTRACT_ACTIVITY = os.environ.get('MEMORY_EXTRACT_ACTIVITY', 'false').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    LOCAL_GRAPH_EXTRACT_WORKERS = int(os.environ.get('LOCAL_GRAPH_EXTRACT_WORKERS', '4'))

    # Zep配置 (only used when MEMORY_BACKEND=zep)
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def is_local_memory(cls) -> bool:
        """True when a self-hosted backend (local SQLite or Cognee) is selected.

        Both need no Zep key and expose the same LocalZep client surface.
        """
        return cls.MEMORY_BACKEND != 'zep'

    @classmethod
    def is_cognee_memory(cls) -> bool:
        """True when the optional Cognee sidecar backend is selected."""
        return cls.MEMORY_BACKEND == 'cognee'

    @classmethod
    def memory_backend_configured(cls) -> bool:
        """True when the selected memory backend has everything it needs."""
        return cls.is_local_memory() or bool(cls.ZEP_API_KEY)

    @classmethod
    def get_model_pool(cls, api_key: str | None = None, base_url: str | None = None, model_name: str | None = None):
        """Return a configured `MultiProviderPool` (single or multi-provider)."""
        from .utils.model_pool import MultiProviderPool
        return MultiProviderPool.from_env(
            primary_api_key=api_key or cls.LLM_API_KEY,
            primary_base_url=base_url or cls.LLM_BASE_URL,
            primary_model=model_name or cls.LLM_MODEL_NAME,
            primary_provider=cls.LLM_PROVIDER,
        )

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if cls.MEMORY_BACKEND not in cls.MEMORY_BACKENDS:
            errors.append(
                f"MEMORY_BACKEND must be 'local', 'cognee' or 'zep' (got {cls.MEMORY_BACKEND!r})"
            )
        if cls.MEMORY_BACKEND == 'zep' and not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置 (required when MEMORY_BACKEND=zep)")
        if cls.MEMORY_BACKEND == 'zep' and os.environ.get("ZEP_API_URL"):
            errors.append("ZEP_API_URL 不受支持；MiroFish 仅连接 Zep Cloud")
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        return errors

    # ------------------------------------------------------------------
    # Production checks (MM_ENV=production)
    # ------------------------------------------------------------------

    # The old hard-coded default and the .env.production.example values are refused.
    _INSECURE_SECRET_DEFAULTS = {'mirofish-secret-key'}
    _PLACEHOLDER_MARKERS = (
        'replace-with', 'replace_me', 'replaceme', 'changeme', 'change-me', 'change_me',
        'your-', 'your_', 'example', 'placeholder', 'secret-here', 'token-here', '<', '>', 'xxxx',
    )
    MIN_SECRET_LENGTH = 32
    _ORIGIN_RE = re.compile(r'^https?://[A-Za-z0-9.\-\[\]:]+$')

    @staticmethod
    def is_production() -> bool:
        return os.environ.get('MM_ENV', '').strip().lower() == 'production'

    @staticmethod
    def is_loopback_host(host: str) -> bool:
        host = (host or '').strip().strip('[]').lower()
        if host in ('localhost', 'ip6-localhost'):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @classmethod
    def _looks_like_placeholder(cls, value: str) -> bool:
        low = value.strip().lower()
        return low in cls._INSECURE_SECRET_DEFAULTS or any(m in low for m in cls._PLACEHOLDER_MARKERS)

    @classmethod
    def production_errors(cls, host: str | None = None) -> list[str]:
        """
        Settings that make a production start unsafe. Empty unless MM_ENV=production.

        Always (production): SECRET_KEY set explicitly, not a default or placeholder,
        at least 32 characters; FLASK_DEBUG off; CORS_ORIGINS never "*".
        Non-loopback bind host: MM_API_AUTH_TOKEN (>= 32 chars, not a placeholder)
        and an explicit CORS_ORIGINS (comma-separated http(s) origins, or "none").
        Values are never echoed back.
        """
        if not cls.is_production():
            return []
        env = os.environ
        host = host if host is not None else env.get('FLASK_HOST', '127.0.0.1')
        errors: list[str] = []

        secret = (env.get('SECRET_KEY') or '').strip()
        if not secret:
            errors.append('SECRET_KEY is not set (generate one with: openssl rand -hex 32)')
        elif cls._looks_like_placeholder(secret):
            errors.append('SECRET_KEY is a default or placeholder value; set a random secret')
        elif len(secret) < cls.MIN_SECRET_LENGTH:
            errors.append(f'SECRET_KEY must be at least {cls.MIN_SECRET_LENGTH} characters')

        if env.get('FLASK_DEBUG', 'False').strip().lower() in ('1', 'true', 'yes', 'on'):
            errors.append('FLASK_DEBUG must be off in production')

        cors = (env.get('CORS_ORIGINS') or '').strip()
        if cors == '*' or '*' in [o.strip() for o in cors.split(',')]:
            errors.append('CORS_ORIGINS="*" is not allowed in production; list the allowed origins or use "none"')

        if not cls.is_loopback_host(host):
            token = (env.get('MM_API_AUTH_TOKEN') or env.get('API_AUTH_TOKEN') or '').strip()
            if not token:
                errors.append(
                    f'MM_API_AUTH_TOKEN is required when binding to a non-loopback host ({host}); '
                    'generate one with: openssl rand -hex 32'
                )
            elif cls._looks_like_placeholder(token):
                errors.append('MM_API_AUTH_TOKEN is a placeholder value; set a random token')
            elif len(token) < cls.MIN_SECRET_LENGTH:
                errors.append(f'MM_API_AUTH_TOKEN must be at least {cls.MIN_SECRET_LENGTH} characters')

            if not cors:
                errors.append(
                    f'CORS_ORIGINS must be set explicitly when binding to a non-loopback host ({host}): '
                    'a comma-separated list such as https://app.yourcompany.com, or "none" for no browser access'
                )
            elif cors.lower() != 'none' and '*' not in cors:
                for origin in (o.strip() for o in cors.split(',')):
                    if not origin:
                        continue
                    if not cls._ORIGIN_RE.match(origin):
                        errors.append(f'CORS_ORIGINS entry is not an http(s) origin without a path: {origin!r}')
                    elif cls._looks_like_placeholder(origin):
                        errors.append(f'CORS_ORIGINS entry is a placeholder: {origin!r}')
        return errors
