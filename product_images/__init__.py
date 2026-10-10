# -*- coding: utf-8 -*-
"""产品图片管理域的公开接口。"""

from .backend import LoadedProductImages, ProductImageWorkspaceBackend
from .workspace import ProductImageWorkspace

__all__ = [
    "LoadedProductImages",
    "ProductImageWorkspace",
    "ProductImageWorkspaceBackend",
]
