from .py import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .py.server_routes import register_server_routes

WEB_DIRECTORY = "./web"

register_server_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
