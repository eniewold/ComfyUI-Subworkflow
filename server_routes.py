"""
Custom API routes for the Subworkflow extension.
"""
import json
import logging
from aiohttp import web
from .workflow_utils import load_workflow, get_workflow_io, list_workflow_files, is_ui_format


log = logging.getLogger("ComfyUI-Subworkflow")


def setup_routes():
    try:
        from server import PromptServer
    except ImportError:
        return
    routes = PromptServer.instance.routes

    async def get_workflow_info(request: web.Request):
        """
        Returns the Subworkflow Input / Subworkflow Output slot info for a workflow.
        Response: {"inputs": [...], "outputs": [...], "error": null | str}
        """
        workflow_name = request.rel_url.query.get("workflow", "")
        log.info("Subworkflow route: info requested for workflow=%r", workflow_name)
        if not workflow_name:
            log.warning("Subworkflow route: info request missing workflow name")
            return web.json_response({"inputs": [], "outputs": [], "error": "No workflow specified"})
        try:
            data = load_workflow(workflow_name)
        except FileNotFoundError:
            log.warning("Subworkflow route: workflow file not found: %r", workflow_name)
            return web.json_response({"inputs": [], "outputs": [], "error": f"File not found: {workflow_name}"})
        except json.JSONDecodeError as e:
            log.warning("Subworkflow route: invalid JSON in workflow %r: %s", workflow_name, e)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Invalid JSON: {e}"})

        try:
            inputs, outputs = get_workflow_io(data)
        except Exception as e:
            log.exception("Subworkflow route: failed to discover I/O for workflow %r", workflow_name)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Failed to discover workflow I/O: {e}"})
        log.info(
            "Subworkflow route: workflow=%r format=%s inputs=%s outputs=%s",
            workflow_name,
            "UI" if is_ui_format(data) else "API",
            inputs,
            outputs,
        )
        return web.json_response({"inputs": inputs, "outputs": outputs, "error": None})

    routes.get("/subworkflow/info")(get_workflow_info)

    async def list_workflows(request: web.Request):
        """Returns the available workflow file names."""
        workflows = list_workflow_files()
        log.info("Subworkflow route: list requested, returning %d workflow option(s)", len(workflows))
        return web.json_response(workflows)

    routes.get("/subworkflow/list")(list_workflows)
