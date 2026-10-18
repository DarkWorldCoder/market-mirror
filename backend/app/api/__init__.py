"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import market  # noqa: E402, F401  (MarketMirror)

from . import feed  # noqa: E402, F401  (MarketMirror feed story)
from . import product  # noqa: E402, F401  (MarketMirror product profile)
