"""公共测试基类：提供工作区内的临时目录（沙箱临时区 E:\\dsn\\.tmp 写入被拒）。"""
import os
import shutil
import unittest

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_TMP_ROOT = os.path.join(_PKG_ROOT, ".tmp", "tests")


class TmpDirTestCase(unittest.TestCase):
    """每个测试方法给一个独立的工作区内临时目录 self.tmp，结束后尽力清理。"""

    def setUp(self):
        os.makedirs(_TEST_TMP_ROOT, exist_ok=True)
        self.tmp = os.path.join(_TEST_TMP_ROOT, self.id().split(".")[-1] + "_d")
        if os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
