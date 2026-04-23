import logging

log = logging.getLogger("ComfyUI-Subworkflow")
log.info("ComfyUI-Subworkflow: module load started")

from comfy_api.latest import ComfyExtension, io

from .nodes import SubworkflowInput, SubworkflowOutput
from .workflow_node import Subworkflow, SubworkflowFromURL
from . import server_routes

WEB_DIRECTORY = "./js"

log.info("ComfyUI-Subworkflow: all imports OK")


class SubworkflowExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = [Subworkflow, SubworkflowFromURL, SubworkflowInput, SubworkflowOutput]
        log.info("ComfyUI-Subworkflow: registering V3 nodes: %s",
                 [n.__name__ for n in nodes])
        return nodes

    async def on_load(self):
        server_routes.setup_routes()
        log.info("ComfyUI-Subworkflow: server routes registered")


async def comfy_entrypoint() -> SubworkflowExtension:
    log.info("ComfyUI-Subworkflow: comfy_entrypoint called")
    return SubworkflowExtension()
