import logging

log = logging.getLogger("ComfyUI-Workflow-Functions")
log.info("ComfyUI-Workflow-Functions: module load started")

from typing_extensions import override
from comfy_api.latest import ComfyExtension, io

from .nodes import FunctionInput, FunctionOutput
from .workflow_node import FunctionWorkflow
from . import server_routes

WEB_DIRECTORY = "./js"

log.info("ComfyUI-Workflow-Functions: all imports OK")


class WorkflowFunctionsExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = [FunctionInput, FunctionOutput]
        log.info("ComfyUI-Workflow-Functions: registering V3 nodes: %s",
                 [n.__name__ for n in nodes])
        return nodes

    @override
    async def on_load(self):
        import nodes as _comfy_nodes
        _comfy_nodes.NODE_CLASS_MAPPINGS["WFF_FunctionWorkflow"] = FunctionWorkflow
        _comfy_nodes.NODE_DISPLAY_NAME_MAPPINGS["WFF_FunctionWorkflow"] = "Subworkflow"
        log.info("ComfyUI-Workflow-Functions: registered V1 node WFF_FunctionWorkflow")

        server_routes.setup_routes()
        log.info("ComfyUI-Workflow-Functions: server routes registered")


async def comfy_entrypoint() -> WorkflowFunctionsExtension:
    log.info("ComfyUI-Workflow-Functions: comfy_entrypoint called")
    return WorkflowFunctionsExtension()
