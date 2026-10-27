import os
import sys
import tempfile

# 让测试可以 import music_agent / main（不依赖 pytest 的 rootdir 机制）
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG_ROOT)

# 沙箱临时区（E:\dsn\.tmp\...）写入/清理被拒之，统一把 tempfile 重定向到工作区内
_TEST_TMP = os.path.join(_PKG_ROOT, ".tmp", "tests")
os.makedirs(_TEST_TMP, exist_ok=True)
tempfile.tempdir = _TEST_TMP
