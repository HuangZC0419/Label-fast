"""统一的业务异常类型。

路由层只负责抛出带状态码的业务异常，最终由全局异常处理器转换为
``{"detail": "..."}``，保证所有 API 的错误结构一致。
"""

from __future__ import annotations


class ServiceError(Exception):
    """可安全返回给客户端的业务异常。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class NotFoundError(ServiceError):
    def __init__(self, detail: str = "资源不存在") -> None:
        super().__init__(404, detail)


class BadRequestError(ServiceError):
    def __init__(self, detail: str = "请求参数不合法") -> None:
        super().__init__(400, detail)


class ConflictError(ServiceError):
    def __init__(self, detail: str = "当前状态不允许该操作") -> None:
        super().__init__(409, detail)


class PayloadTooLargeError(ServiceError):
    def __init__(self, detail: str = "上传文件过大") -> None:
        super().__init__(413, detail)


class UpstreamError(ServiceError):
    def __init__(self, detail: str = "OCR Worker 暂不可用") -> None:
        super().__init__(502, detail)
