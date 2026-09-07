"""效果器汇总导入。

新增效果器文件后，必须在这里补一行 import，否则装饰器不会执行。
"""

from server.core.effects import basic, denoise, edit  # noqa: F401
