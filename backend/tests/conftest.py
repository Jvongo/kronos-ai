"""pytest 夹具：注入 backend 到 sys.path，并隔离重型依赖。

行情数据层的单测只依赖 requests，不需要 torch/transformers；
而 `app.services.__init__` 会连带导入 model_manager（依赖 torch），
因此这里用一个只带 `__path__` 的轻量包对象占位，避免测试被重型依赖阻断。
"""
import sys
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if "app.services" not in sys.modules:
    _pkg = types.ModuleType("app.services")
    _pkg.__path__ = [str(BACKEND_DIR / "app" / "services")]
    sys.modules["app.services"] = _pkg
