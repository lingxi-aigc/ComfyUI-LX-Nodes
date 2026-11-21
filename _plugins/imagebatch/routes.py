"""Counter reset endpoint for folder image loading."""

from aiohttp import web
from server import PromptServer


def register_routes(loader_class):
    routes = PromptServer.instance.routes
    if any(
        item.method == "POST" and item.path == "/lx_imagebatch/reset_counter"
        for item in routes
    ):
        return

    @routes.post("/lx_imagebatch/reset_counter")
    async def reset_counter(request):
        with loader_class._cache_lock:
            loader_class._counters.clear()
            loader_class._fixed_counters.clear()
        return web.json_response({"status": "success", "message": "counters reset"})
