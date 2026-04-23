import logging

from .debug_utils import configure_logger, DEBUG_ENABLED

log = configure_logger("ComfyUI-Subworkflow")
log.info("[Subworkflow] module load started")

from comfy_api.latest import ComfyExtension, io

from .nodes import SubworkflowInput, SubworkflowOutput
from .workflow_node import Subworkflow, SubworkflowFromURL
from . import server_routes

WEB_DIRECTORY = "./js"

log.debug("[Subworkflow] all imports OK")
log.info("[Subworkflow] debug logging %s", "enabled" if DEBUG_ENABLED else "disabled")


class SubworkflowExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = [Subworkflow, SubworkflowFromURL, SubworkflowInput, SubworkflowOutput]
        log.debug("[Subworkflow] registering V3 nodes: %s",
                  [n.__name__ for n in nodes])
        return nodes

    async def on_load(self):
        server_routes.setup_routes()
        log.debug("[Subworkflow] server routes registered")


async def comfy_entrypoint() -> SubworkflowExtension:
    log.debug("[Subworkflow] comfy_entrypoint called")
    return SubworkflowExtension()
