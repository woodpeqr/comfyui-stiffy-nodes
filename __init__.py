__version__ = "2.0"

WEB_DIRECTORY = "./web/js"

from .main import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: E402

try:
    from aiohttp import web
    from server import PromptServer

    from .models import Prompt
    from .node_logic import list_preset_names, load_preset, save_preset

    routes = PromptServer.instance.routes

    @routes.get("/api/stiffy/presets")
    async def _list_presets(request):
        category = request.rel_url.query.get("category")
        return web.json_response(list_preset_names(category or None))

    @routes.get("/api/stiffy/presets/{name}")
    async def _load_preset(request):
        name = request.match_info["name"]
        preset = load_preset(name)
        if preset is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response([p.model_dump() for p in preset])

    @routes.post("/api/stiffy/presets/{name}")
    async def _save_preset(request):
        name = request.match_info["name"]
        data = await request.json()
        save_preset(name, [Prompt(**entry) for entry in data])
        return web.json_response({"ok": True})

except ImportError:
    pass  # Running outside ComfyUI

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
