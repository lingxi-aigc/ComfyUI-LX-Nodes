import json
from ..categories import LX_RELAY_CATEGORY
from .lb_config import (
    get_api_base_list,
    set_current_base_url,
    PLATFORMS, IMAGE_API_FORMATS, get_catalog_for_base,
)


class LingxiBridgeSettings:
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀API配置", "API配置", "中转站配置", "api settings")

    @classmethod
    def INPUT_TYPES(cls):
        api_base_list = get_api_base_list()
        default_base = api_base_list[0] if api_base_list else ""
        catalog = get_catalog_for_base(default_base) if default_base else {}
        api_format_list = list(catalog.keys()) or IMAGE_API_FORMATS
        default_api_format = api_format_list[0] if api_format_list else ""
        model_list = catalog.get(default_api_format, [""]) or [""]
        return {
            "required": {
                "platform": (PLATFORMS, {"default": PLATFORMS[0]}),
                "api_base": (api_base_list, {"default": default_base}),
                "api_format": (api_format_list, {"default": default_api_format}),
                "model": (model_list, {"default": model_list[0] if model_list else ""}),
                "apikey": ("STRING", {"default": ""}),
            },
            "optional": {
                "custom_api_base": ("STRING", {
                    "default": "",
                    "placeholder": "填入则以此地址为准，覆盖上方下拉选择",
                }),
                "custom_api_format": ("STRING", {
                    "default": "",
                    "placeholder": "填入则以此接口格式为准，覆盖上方下拉选择",
                }),
                "custom_model": ("STRING", {
                    "default": "",
                    "placeholder": "填入则以此模型为准，覆盖上方下拉选择",
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("info",)
    FUNCTION = "set_api"
    CATEGORY = f"{LX_RELAY_CATEGORY}/接口配置"
    SIZE = (420, 340)

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, api_base=None, **kwargs):
        return True

    def set_api(self, platform, api_base, model, apikey="",
                 custom_api_base="", custom_api_format="", custom_model="",
                 unique_id=None, api_format=""):
        custom_api_base = custom_api_base.strip().rstrip('/')
        custom_api_format = custom_api_format.strip()
        effective_api_format = custom_api_format or api_format
        effective_model = custom_model.strip() or model

        effective_base = custom_api_base or api_base

        set_current_base_url(effective_base)

        real_key = (apikey or "").strip()

        info = json.dumps({
            "apikey": real_key,
            "api_base": effective_base,
            "model": effective_model,
            "platform": platform,
            "api_format": effective_api_format,
        })

        print(f"[LingxiBridge] {platform} | {effective_api_format} | {effective_base} | {effective_model}")

        return (info,)
