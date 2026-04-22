"""
Custom API routes for the Workflow Functions extension.
"""
import json
from aiohttp import web
from .workflow_utils import load_workflow, get_workflow_io, list_workflow_files


def setup_routes():
    try:
        from server import PromptServer
    except ImportError:
        return
    routes = PromptServer.instance.routes

    @routes.get("/workflow_functions/info")
    async def get_workflow_info(request: web.Request):
        """
        Returns the FunctionInput / FunctionOutput slot info for a workflow.
        Response: {"inputs": [...], "outputs": [...], "error": null | str}
        """
        workflow_name = request.rel_url.query.get("workflow", "")
        if not workflow_name:
            return web.json_response({"inputs": [], "outputs": [], "error": "No workflow specified"})
        try:
            data = load_workflow(workflow_name)
        except FileNotFoundError:
            return web.json_response({"inputs": [], "outputs": [], "error": f"File not found: {workflow_name}"})
        except json.JSONDecodeError as e:
            return web.json_response({"inputs": [], "outputs": [], "error": f"Invalid JSON: {e}"})

        inputs, outputs = get_workflow_io(data)
        return web.json_response({"inputs": inputs, "outputs": outputs, "error": None})

    @routes.get("/workflow_functions/list")
    async def list_workflows(request: web.Request):
        """Returns the available workflow file names."""
        return web.json_response(list_workflow_files())
