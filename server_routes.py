"""
Custom API routes for the Subworkflow extension.
"""
import asyncio
import json
import logging
from aiohttp import web
from .workflow_utils import (
    load_workflow_file,
    load_workflow_url,
    get_workflow_io,
    list_workflow_files,
    is_ui_format,
)


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
        source = request.rel_url.query.get("source", "file")
        workflow_name = request.rel_url.query.get("workflow", "")
        url = request.rel_url.query.get("url", "")
        source_value = url if source == "url" else workflow_name
        log.info("Subworkflow route: info requested for source=%r value=%r", source, source_value)
        if source == "url":
            if not url:
                log.warning("Subworkflow route: URL info request missing URL")
                return web.json_response({"inputs": [], "outputs": [], "error": "No workflow URL specified"})
            loader = load_workflow_url
        elif source == "file":
            if not workflow_name:
                log.warning("Subworkflow route: info request missing workflow name")
                return web.json_response({"inputs": [], "outputs": [], "error": "No workflow specified"})
            loader = load_workflow_file
        else:
            log.warning("Subworkflow route: unsupported source=%r", source)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Unsupported source: {source}"})

        try:
            if source == "url":
                data = await asyncio.to_thread(loader, source_value)
            else:
                data = loader(source_value)
        except FileNotFoundError:
            log.warning("Subworkflow route: workflow file not found: %r", source_value)
            return web.json_response({"inputs": [], "outputs": [], "error": f"File not found: {source_value}"})
        except json.JSONDecodeError as e:
            log.warning("Subworkflow route: invalid JSON in workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Invalid JSON: {e}"})
        except UnicodeDecodeError as e:
            log.warning("Subworkflow route: invalid UTF-8 in workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Invalid UTF-8: {e}"})
        except ValueError as e:
            log.warning("Subworkflow route: failed to load workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "error": str(e)})

        try:
            inputs, outputs = get_workflow_io(data)
        except Exception as e:
            log.exception("Subworkflow route: failed to discover I/O for workflow %r", source_value)
            return web.json_response({"inputs": [], "outputs": [], "error": f"Failed to discover workflow I/O: {e}"})
        log.info(
            "Subworkflow route: source=%r workflow=%r format=%s inputs=%s outputs=%s",
            source,
            source_value,
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
