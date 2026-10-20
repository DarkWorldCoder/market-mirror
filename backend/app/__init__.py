"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


_DEV_CORS_ORIGINS = [r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"]


def _cors_origins():
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw.lower() == "none":
        return None
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins[0] if origins == ["*"] else origins
    return None if Config.is_production() else _DEV_CORS_ORIGINS


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # Production safety: refuse an open or misconfigured production start (token, CORS, SECRET_KEY).
    production_errors = Config.production_errors()
    if production_errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(production_errors))

    # CORS: explicit CORS_ORIGINS (comma-separated, or "none"); otherwise loopback origins in
    # development and no cross-origin access in production.
    origins_val = _cors_origins()
    if origins_val:
        CORS(app, resources={r"/api/*": {"origins": origins_val}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")

    # Tasks left pending/processing by a previous process can never finish: mark them failed.
    from .models.task import TaskManager
    TaskManager().recover_interrupted_tasks()

    # 注册生产级中间件（API 鉴权、限流、请求追踪ID、安全响应头、/ready 与 /metrics 探针）
    from .utils.production import install_production_middleware
    install_production_middleware(app)
    
    # 请求日志中间件（生产环境不记录请求体：可能含客户数据或凭据）
    log_bodies = not Config.is_production()

    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if log_bodies and request.content_type and 'json' in request.content_type:
            body = request.get_json(silent=True)
            if request.path == '/api/simulation/website-test' and isinstance(body, dict):
                body = {**body, 'spec': {**(body.get('spec') or {}), 'test_data': '[redacted]'}} if isinstance(body.get('spec'), dict) else body
            logger.debug(f"请求体: {body}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    from .api.setup import setup_bp
    app.register_blueprint(setup_bp)
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

