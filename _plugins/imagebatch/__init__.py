"""
imagebatch 插件

提供基于文件夹的图像批量加载/计数/保存节点。
"""

from .lxib_counter import LXFolderImageCount
from .lxib_loader import LXLoadFolderImage
from .lxib_saver import LXSaveFolderImage
from .routes import register_routes

NODE_CLASS_MAPPINGS = {
    "LXFolderImageCount": LXFolderImageCount,
    "LXImageBatch": LXLoadFolderImage,
    "LXSaveFolderImage": LXSaveFolderImage,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LXFolderImageCount": "图像计数（文件夹）",
    "LXImageBatch": "加载图像（文件夹）",
    "LXSaveFolderImage": "保存图像（文件夹）",
}
LX_LOADER_CLASS = LXLoadFolderImage

register_routes(LX_LOADER_CLASS)
