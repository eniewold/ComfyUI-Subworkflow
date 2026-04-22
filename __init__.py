import logging

log = logging.getLogger("ComfyUI-Subworkflow")
log.info("ComfyUI-Subworkflow: module load started")

from typing_extensions import override
from comfy_api.latest import ComfyExtension, io

from .nodes import SubworkflowInput, SubworkflowOutput
from .workflow_node import Subworkflow
from . import server_routes

WEB_DIRECTORY = "./js"

log.info("ComfyUI-Subworkflow: all imports OK")


class SubworkflowExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = [SubworkflowInput, SubworkflowOutput]
        log.info("ComfyUI-Subworkflow: registering V3 nodes: %s",
                 [n.__name__ for n in nodes])
        return nodes

    @override
    async def on_load(self):
        import nodes as _comfy_nodes
        _comfy_nodes.NODE_CLASS_MAPPINGS["SWF_Subworkflow"] = Subworkflow
        _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS["SWF_Subworkflow"] = "Subworkflow"
        log.info("ComfyUI-Subworkflow: registered V1 node SWF_Subworkflow")

        server_routes.setup_routes()
        log.info("ComfyUI-Subworkflow: server routes registered")


async def comfy_entrypoint() -> SubworkflowExtension:
    log.info("ComfyUI-Subworkflow: comfy_entrypoint called")
    return SubworkflowExtension()
