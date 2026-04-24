"""
Custom API routes for the Subworkflow extension.
"""
import asyncio
import json
import logging
from aiohttp import web
from .debug_utils import configure_logger
from .workflow_utils import (
    load_workflow_file,
    load_workflow_url,
    get_workflow_interface,
    list_workflow_files,
    is_ui_format,
)


log = configure_logger("ComfyUI-Subworkflow")


def _query_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def setup_routes():
    try:
        from server import PromptServer
    except ImportError:
        log.warning("[Subworkflow] route setup skipped: PromptServer import failed")
        return
    routes = PromptServer.instance.routes
    log.debug("[Subworkflow] route setup registering /subworkflow/info and /subworkflow/list")

    async def get_workflow_info(request: web.Request):
        """
        Returns the Subworkflow Input / Subworkflow Output slot info for a workflow.
        Response: {"inputs": [...], "outputs": [...], "error": null | str}
        """
        source = request.rel_url.query.get("source", "file")
        workflow_name = request.rel_url.query.get("workflow", "")
        url = request.rel_url.query.get("url", "")
        verify_ssl = _query_bool(request.rel_url.query.get("verify_ssl"), True)
        source_value = url if source == "url" else workflow_name
        log.debug(
            "[Subworkflow] route info requested path=%r query=%s source=%r value=%r verify_ssl=%s",
            str(request.rel_url),
            dict(request.rel_url.query),
            source,
            source_value,
            verify_ssl,
        )
        if source == "url":
            if not url:
                log.warning("[Subworkflow] route URL info request missing URL")
                return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": "No workflow URL specified"})
            log.debug("[Subworkflow] route selected URL loader for %r verify_ssl=%s", url, verify_ssl)
            loader = load_workflow_url
        elif source == "file":
            if not workflow_name:
                log.warning("[Subworkflow] route info request missing workflow name")
                return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": "No workflow specified"})
            log.debug("[Subworkflow] route selected file loader for %r", workflow_name)
            loader = load_workflow_file
        else:
            log.warning("[Subworkflow] route unsupported source=%r", source)
            return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": f"Unsupported source: {source}"})

        try:
            if source == "url":
                log.debug(
                    "[Subworkflow] route dispatching URL load to worker thread for %r verify_ssl=%s",
                    source_value,
                    verify_ssl,
                )
                data = await asyncio.to_thread(loader, source_value, verify_ssl)
            else:
                log.debug("[Subworkflow] route loading file workflow synchronously for %r", source_value)
                data = loader(source_value)
            log.debug(
                "[Subworkflow] route loader returned source=%r value=%r type=%s keys=%s",
                source,
                source_value,
                type(data).__name__,
                sorted(data.keys())[:12] if isinstance(data, dict) else None,
            )
        except FileNotFoundError:
            log.warning("[Subworkflow] route workflow file not found: %r", source_value)
            return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": f"File not found: {source_value}"})
        except json.JSONDecodeError as e:
            log.warning("[Subworkflow] route invalid JSON in workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": f"Invalid JSON: {e}"})
        except UnicodeDecodeError as e:
            log.warning("[Subworkflow] route invalid UTF-8 in workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": f"Invalid UTF-8: {e}"})
        except ValueError as e:
            log.warning("[Subworkflow] route failed to load workflow %r: %s", source_value, e)
            return web.json_response({"inputs": [], "outputs": [], "modifiers": [], "error": str(e)})

        try:
            interface = get_workflow_interface(data)
        except Exception as e:
            log.exception("[Subworkflow] route failed to discover I/O for workflow %r", source_value)
            return web.json_response({
                "inputs": [],
                "outputs": [],
                "modifiers": [],
                "error": f"Failed to discover workflow I/O: {e}",
            })
        log.debug(
            "[Subworkflow] route source=%r workflow=%r format=%s inputs=%s outputs=%s modifiers=%s",
            source,
            source_value,
            "UI" if is_ui_format(data) else "API",
            interface["inputs"],
            interface["outputs"],
            interface["modifiers"],
        )
        return web.json_response({
            "inputs": interface["inputs"],
            "outputs": interface["outputs"],
            "modifiers": interface["modifiers"],
            "error": None,
        })

    routes.get("/subworkflow/info")(get_workflow_info)

    async def list_workflows(request: web.Request):
        """Returns the available workflow file names."""
        workflows = list_workflow_files()
        log.debug("[Subworkflow] route list requested, returning %d workflow option(s)", len(workflows))
        return web.json_response(workflows)

    routes.get("/subworkflow/list")(list_workflows)
