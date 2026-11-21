import os
import json
import shutil
import threading
from aiohttp import web
from .lb_aipaiai import AIPAI_ADOBE_FORMAT

_CONFIG_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(_CONFIG_DIR, 'relay_config.local.json')
CONFIG_EXAMPLE_FILE = os.path.join(_CONFIG_DIR, 'relay_config.example.json')
LEGACY_CONFIG_FILE = os.path.join(_CONFIG_DIR, 'relay_config.json')
_config_lock = threading.RLock()

DEFAULT_API_BASES = [
    "https://grsaiapi.com",
    "https://yunwu.ai",
    "https://www.runninghub.cn",
    "https://aipaiai.cn",
    "https://cdn.aipaiai.cn",
]

PLATFORMS = ["banana-pro", "banana-2", "gpt-image2", "gpt-image2.5"]

IMAGE_API_FORMATS = [
    "v1beta/models",
    "v1/images",
    AIPAI_ADOBE_FORMAT,
    "v1/chat/completions",
    "v1/api/generate",
    "runninghub-/openapi/v2",
]

# ─── Base Catalog ───────────────────────────────────────────────────────────────
# api_base → 该站点对用户暴露哪些接口，以及每个接口下有哪些模型。
# key: 接口名，value: 该接口的模型列表
# 切换 api_base 时，前端加载此表，动态填充接口下拉框和模型下拉框。

DEFAULT_BASE_CATALOG = {
    "https://grsaiapi.com": {
        "v1/api/generate": [
            "nano-banana-pro",
            "nano-banana-pro-cl",
            "nano-banana-pro-vt",
            "nano-banana-2",
            "nano-banana-2-cl",
            "gpt-image-2-vip",
        ],
    },
    "https://yunwu.ai": {
        "v1beta/models": [
            "gemini-3-pro-image-preview",
            "gemini-3.1-flash-image-preview",
        ],
        "v1/images": [
            "gpt-image-2",
        ],
        "v1/chat/completions": [
            "gemini-3-pro-image-preview",
            "gemini-3.1-flash-image-preview",
        ],
    },
    "https://www.runninghub.cn": {
        "runninghub-/openapi/v2": [
            "nano-banana-pro",
            "rhart-image-n-pro",
            "rhart-image-n-pro-official",
            "rhart-image-n-g31-flash",
            "rhart-image-n-g31-flash-official",
            "rhart-image-g-2",
            "rhart-image-g-2-official",
        ],
    },
    "https://aipaiai.cn": {
        AIPAI_ADOBE_FORMAT: ["gpt-image-2", "gpt-image-2.5-flare-firefly", "gpt-image-2.5-sunburst-firefly"],
        "v1/images": [
            "gpt-image-2",
            "gpt-image-2.5-flare-firefly",
            "gpt-image-2.5-sunburst-firefly",
        ],
    },
    "https://cdn.aipaiai.cn": {
        AIPAI_ADOBE_FORMAT: ["gpt-image-2", "gpt-image-2.5-flare-firefly", "gpt-image-2.5-sunburst-firefly"],
        "v1/images": [
            "gpt-image-2",
            "gpt-image-2.5-flare-firefly",
            "gpt-image-2.5-sunburst-firefly",
        ],
    },
}

# ─── Model Labels (描述信息) ───────────────────────────────────────────────────
# model → 用户友好的说明文字

MODEL_LABELS = {
    "nano-banana-2-cl":          "更稳定，更贵",
    "nano-banana-pro-cl":        "更稳定，更贵",
    "nano-banana-pro-vt":        "4K质量更好，高峰期可能不稳",
    "gpt-image-2-vip":          "GPT图像生成",
    "gpt-image-2":              "GPT图像生成，v2版本",
    "rhart-image-n-pro-official":  "RunningHub官方模型",
    "rhart-image-n-g31-flash-official": "RunningHub官方模型",
    "rhart-image-g-2-official":   "RunningHub官方模型",
}

# ─── API Paths ─────────────────────────────────────────────────────────────────

API_PATHS = {
    "image_v1beta/models": {
        "generate": "/v1beta/models/{model}:generateContent",
        "edit": "/v1beta/models/{model}:generateContent",
    },
    "image_v1/chat/completions": {
        "chat": "/v1/chat/completions",
    },
    "image_v1/images": {
        "generate": "/v1/images/generations",
        "edit": "/v1/images/edits",
        "gpt_image2_generate": "/v1/images/generations",
        "gpt_image2_edit": "/v1/images/edits",
    },
    "image_runninghub-/openapi/v2": {
        "create": "/openapi/v2/{model}/text-to-image",
        "edit": "/openapi/v2/{model}/image-to-image",
        "upload": "/openapi/v2/upload",
        "query": "/openapi/v2/query",
    },
    "image_v1/api/generate": {
        "generate": "/v1/api/generate",
    },
}

# ─── Config CRUD ────────────────────────────────────────────────────────────────

def _default_config():
    return {
        "base_url": DEFAULT_API_BASES[0],
        "custom_api_bases": [],
        "removed_defaults": [],
        "custom_api_formats": {},
        "custom_models": {},
        "concurrency": {},
    }


def _candidate_config_files():
    return [CONFIG_FILE, LEGACY_CONFIG_FILE, CONFIG_EXAMPLE_FILE]


def get_config():
    with _config_lock:
        for path in _candidate_config_files():
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return config if isinstance(config, dict) else _default_config()
            except Exception as exc:
                if path == CONFIG_FILE:
                    try:
                        shutil.copy2(path, f"{path}.broken")
                    except Exception:
                        pass
                print(f"[LX][lingxi_bridge] 配置读取失败，已跳过 {path}: {exc}")
        return _default_config()


def save_config(config):
    with _config_lock:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        tmp_file = f"{CONFIG_FILE}.tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_file, CONFIG_FILE)


# ─── API Base Management ───────────────────────────────────────────────────────

def get_api_base_list():
    config = get_config()
    custom_bases = config.get('custom_api_bases', [])
    removed_defaults = config.get('removed_defaults', [])
    all_bases = [b for b in DEFAULT_API_BASES if b not in removed_defaults]
    for base in custom_bases:
        base = base.strip().rstrip('/')
        if base and base not in all_bases:
            all_bases.append(base)
    if not all_bases:
        all_bases = list(DEFAULT_API_BASES)
    return all_bases


def add_custom_api_base(url):
    url = url.strip().rstrip('/')
    if not url:
        return
    config = get_config()
    custom_bases = config.get('custom_api_bases', [])
    removed_defaults = config.get('removed_defaults', [])
    if url in removed_defaults:
        removed_defaults.remove(url)
        config['removed_defaults'] = removed_defaults
    if url not in custom_bases and url not in DEFAULT_API_BASES:
        custom_bases.append(url)
        config['custom_api_bases'] = custom_bases
    save_config(config)


def remove_custom_api_base(url):
    url = url.strip().rstrip('/')
    if not url:
        return
    config = get_config()
    custom_bases = config.get('custom_api_bases', [])
    removed_defaults = config.get('removed_defaults', [])
    if url in custom_bases:
        custom_bases.remove(url)
        config['custom_api_bases'] = custom_bases
    if url in DEFAULT_API_BASES and url not in removed_defaults:
        removed_defaults.append(url)
        config['removed_defaults'] = removed_defaults
    save_config(config)


def get_current_base_url():
    config = get_config()
    return config.get('base_url', DEFAULT_API_BASES[0]).rstrip('/')


def set_current_base_url(url):
    config = get_config()
    config['base_url'] = url.strip().rstrip('/')
    save_config(config)


# ─── Base Catalog (dynamic per api_base) ───────────────────────────────────────

def _get_base_catalog(base_url):
    base_url = base_url.strip().rstrip('/')
    config = get_config()
    custom_catalogs = config.get('custom_base_catalogs', {})
    if base_url in custom_catalogs:
        return custom_catalogs[base_url]
    return DEFAULT_BASE_CATALOG.get(base_url, {})


def get_catalog_for_base(base_url):
    base_url = base_url.strip().rstrip('/')
    config = get_config()
    catalog = _get_base_catalog(base_url)
    custom_models = config.get('custom_models', {}).get(base_url, {})

    result = {}
    for fmt, models in catalog.items():
        if not isinstance(models, list):
            models = []
        for m in (custom_models.get(fmt, []) or []):
            m = m.strip()
            if m and m not in models:
                models.append(m)
        result[fmt] = models
    return result


def add_custom_model_to_base(base_url, api_format, model):
    if not model:
        return
    model = model.strip()
    if not model:
        return
    base_url = base_url.strip().rstrip('/')
    config = get_config()
    custom_models = config.get('custom_models', {})
    if base_url not in custom_models:
        custom_models[base_url] = {}
    if api_format not in custom_models[base_url]:
        custom_models[base_url][api_format] = []
    if model not in custom_models[base_url][api_format]:
        custom_models[base_url][api_format].append(model)
    config['custom_models'] = custom_models
    save_config(config)


def remove_model_from_base(base_url, api_format, model):
    if not model:
        return
    model = model.strip()
    if not model:
        return
    base_url = base_url.strip().rstrip('/')
    config = get_config()
    custom_models = config.get('custom_models', {})
    base_custom = custom_models.get(base_url, {})
    fmt_custom = base_custom.get(api_format, [])
    if isinstance(fmt_custom, list) and model in fmt_custom:
        fmt_custom.remove(model)
    custom_models[base_url] = base_custom
    config['custom_models'] = custom_models
    save_config(config)


# ─── HTTP Routes ───────────────────────────────────────────────────────────────

_LINGXI_ROUTE_MARKER = "_lx_lingxi_bridge_routes_registered"
_LINGXI_ROUTE_SPECS = (
    ("GET", "/relayapi/api_bases"),
    ("POST", "/relayapi/api_bases/add"),
    ("POST", "/relayapi/api_bases/remove"),
    ("GET", "/relayapi/catalog"),
    ("POST", "/relayapi/models/add"),
    ("POST", "/relayapi/models/remove"),
    ("GET", "/relayapi/model_labels"),
)


def _route_table_has_any(routes, specs):
    try:
        existing = {
            (getattr(item, "method", "").upper(), getattr(item, "path", ""))
            for item in getattr(routes, "_items", [])
        }
    except Exception:
        return False
    return any((method.upper(), path) in existing for method, path in specs)


def register_routes():
    try:
        from server import PromptServer
        if not hasattr(PromptServer, 'instance') or PromptServer.instance is None:
            print("[LingxiBridge] PromptServer not ready, skipping route registration")
            return
    except ImportError:
        print("[LingxiBridge] Cannot import PromptServer, skipping route registration")
        return

    if getattr(PromptServer.instance, _LINGXI_ROUTE_MARKER, False) or _route_table_has_any(
        PromptServer.instance.routes,
        _LINGXI_ROUTE_SPECS,
    ):
        setattr(PromptServer.instance, _LINGXI_ROUTE_MARKER, True)
        return
    setattr(PromptServer.instance, _LINGXI_ROUTE_MARKER, True)

    @PromptServer.instance.routes.get("/relayapi/api_bases")
    async def get_api_bases(request):
        return web.json_response(get_api_base_list())

    @PromptServer.instance.routes.post("/relayapi/api_bases/add")
    async def api_base_add(request):
        data = await request.json()
        url = data.get("url", "").strip().rstrip('/')
        if url:
            add_custom_api_base(url)
            return web.json_response({"success": True, "list": get_api_base_list()})
        return web.json_response({"success": False, "message": "URL is empty"}, status=400)

    @PromptServer.instance.routes.post("/relayapi/api_bases/remove")
    async def api_base_remove(request):
        data = await request.json()
        url = data.get("url", "").strip().rstrip('/')
        if url:
            remove_custom_api_base(url)
            return web.json_response({"success": True, "list": get_api_base_list()})
        return web.json_response({"success": False, "message": "URL is empty"}, status=400)

    @PromptServer.instance.routes.get("/relayapi/catalog")
    async def get_catalog(request):
        base_url = request.rel_url.query.get("base_url", DEFAULT_API_BASES[0])
        catalog = get_catalog_for_base(base_url)

        formats = list(catalog.keys())
        format_models = {}
        for fmt, models in catalog.items():
            format_models[fmt] = models

        return web.json_response({
            "formats": formats,
            "format_models": format_models,
            "model_labels": dict(MODEL_LABELS),
        })

    @PromptServer.instance.routes.post("/relayapi/models/add")
    async def model_add(request):
        data = await request.json()
        base_url = data.get("base_url", DEFAULT_API_BASES[0])
        api_format = data.get("api_format", "")
        model = data.get("model", "")
        if model.strip():
            add_custom_model_to_base(base_url, api_format, model)
            catalog = get_catalog_for_base(base_url)
            return web.json_response({"success": True, "catalog": catalog, "format_models": catalog})
        return web.json_response({"success": False, "message": "Model is empty"}, status=400)

    @PromptServer.instance.routes.post("/relayapi/models/remove")
    async def model_remove(request):
        data = await request.json()
        base_url = data.get("base_url", DEFAULT_API_BASES[0])
        api_format = data.get("api_format", "")
        model = data.get("model", "")
        if model.strip():
            remove_model_from_base(base_url, api_format, model)
            catalog = get_catalog_for_base(base_url)
            return web.json_response({"success": True, "catalog": catalog, "format_models": catalog})
        return web.json_response({"success": False, "message": "Model is empty"}, status=400)

    @PromptServer.instance.routes.get("/relayapi/model_labels")
    async def get_model_labels(request):
        return web.json_response(dict(MODEL_LABELS))

    # ─── Debug Log 接口 ─────────────────────────────────────────────────────────
    try:
        from . import lb_debug as dlog

        @PromptServer.instance.routes.get("/relayapi/logs")
        async def get_logs(request):
            limit = min(int(request.rel_url.query.get("limit", 50)), 200)
            logs = dlog.get_recent_logs(limit)
            return web.json_response({
                "count": len(logs),
                "total": dlog._log_count,
                "entries": [e.to_dict() for e in logs],
            })

        @PromptServer.instance.routes.delete("/relayapi/logs")
        async def clear_logs(request):
            dlog.clear_logs()
            return web.json_response({"success": True})

        @PromptServer.instance.routes.get("/relayapi/logs/latest")
        async def get_latest_log(request):
            logs = dlog.get_recent_logs(1)
            entry = logs[0].to_dict() if logs else None
            return web.json_response({"entry": entry})

        @PromptServer.instance.routes.get("/relayapi/logs/text")
        async def get_logs_text(request):
            text = dlog.get_log_summary()
            return web.json_response({"text": text})
    except Exception:
        pass
