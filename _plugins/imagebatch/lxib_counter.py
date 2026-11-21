# LX_图像计数（文件夹）：统计目录下符合条件的图片数量

import os
import threading
from typing import Tuple, Dict, Any

from .lxib_folder_scan import (
    PRESET_EXTS,
    SORT_DEFAULT,
    _RECURSION_DEPTH,
    build_cycle_queue,
    build_scan_stats,
    scan_cache_key,
    root_mtime,
)
from ..categories import LX_FOLDER_CATEGORY


class LXFolderImageCount:
    """LX_图像计数（文件夹）- 统计指定目录下符合条件的图片数量"""

    DESCRIPTION = (
        "LX_图像计数（文件夹）：按格式过滤递归扫描目录，"
        "输出图片总数"
    )
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "LX_图像计数（文件夹）",
        "LX文件夹计数",
        "LX图片计数",
        "文件夹图片数量",
        "lx folder image count",
        "LXFolderImageCount",
    ]

    NODE_NAME = "LXFolderImageCount"
    CATEGORY = LX_FOLDER_CATEGORY
    SIZE = (420, 160)
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("图像总数",)
    FUNCTION = "count_images"

    _cache: Dict[str, Dict[str, Any]] = {}
    _cache_lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls):
        preset_keys = list(PRESET_EXTS.keys())
        return {
            "required": {
                "路径": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "输入文件夹路径",
                    },
                ),
                "格式过滤": (preset_keys, {"default": "全部"}),
            },
        }

    def _get_scan(
        self,
        root: str,
        ext_preset: str,
    ) -> Dict[str, Any]:
        key = scan_cache_key(root, ext_preset, SORT_DEFAULT)
        mtime = root_mtime(root)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached.get("mtime") == mtime:
                return cached

        queue = build_cycle_queue(root, _RECURSION_DEPTH, ext_preset, SORT_DEFAULT)
        stats = build_scan_stats(root, _RECURSION_DEPTH, queue, ext_preset)
        entry = {
            "mtime": mtime,
            "queue": queue,
            "stats": stats,
        }
        with self._cache_lock:
            self._cache[key] = entry
        return entry

    def count_images(
        self,
        路径: str,
        格式过滤: str = "全部",
    ) -> Tuple[int]:
        if not 路径 or not os.path.isdir(路径):
            return (0,)

        root = os.path.abspath(os.path.normpath(路径))
        scan = self._get_scan(root, 格式过滤)
        stats = scan["stats"]
        image_total = int(stats.get("total") or 0)
        return (image_total,)


NODE_CLASS_MAPPINGS = {"LXFolderImageCount": LXFolderImageCount}
NODE_DISPLAY_NAME_MAPPINGS = {"LXFolderImageCount": "图像计数（文件夹）"}
