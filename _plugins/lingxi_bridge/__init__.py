"""
lingxi_bridge 插件

提供 API 中转图像生成节点（支持 banana-pro / banana-2 / gpt-image2 等多平台）。
"""

from .lb_settings import LingxiBridgeSettings
from .lb_image import LingxiBridgeImage
from .lb_inpaint import LingxiBridgeInpaint
from .lb_cache_manager import LingxiCacheManager
from .lb_notice import LingxiBridgeNotice

NODE_CLASS_MAPPINGS = {
    "LingxiBridgeSettings": LingxiBridgeSettings,
    "LingxiBridgeImage": LingxiBridgeImage,
    "LingxiBridgeInpaint": LingxiBridgeInpaint,
    "LingxiCacheManager": LingxiCacheManager,
    "LingxiBridgeNotice": LingxiBridgeNotice,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LingxiBridgeSettings": "灵犀API配置",
    "LingxiBridgeImage": "灵犀生图",
    "LingxiBridgeInpaint": "灵犀局部编辑",
    "LingxiCacheManager": "灵犀缓存管理",
    "LingxiBridgeNotice": "API配置说明",
}

from .lb_config import register_routes
register_routes()
