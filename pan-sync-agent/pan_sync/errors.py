class PanSyncError(Exception):
    """工具内所有可预期错误的基类。"""


class ConfigError(PanSyncError):
    """配置缺失或非法。"""


class UploadError(PanSyncError):
    """上传过程中的协议或网络错误。"""


class AuthError(UploadError):
    """登录凭证失效；不做重试，需要重新登录。"""
