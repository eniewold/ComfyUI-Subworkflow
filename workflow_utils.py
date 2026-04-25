"""
Utilities for loading and processing ComfyUI workflows.
Supports both UI format (saved normally via Ctrl+S) and API format.
"""
import json
import logging
import os
import random
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from comfy_execution.graph_utils import GraphBuilder
from .debug_utils import configure_logger

log = configure_logger("ComfyUI-Subworkflow")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

SWF_SUBWORKFLOW_INPUT = "SWF_SubworkflowInput"
SWF_SUBWORKFLOW_OUTPUT = "SWF_SubworkflowOutput"
SWF_SUBWORKFLOW_MODIFIER = "SWF_SubworkflowModifier"
PLACEHOLDER = ""
MAX_URL_WORKFLOW_BYTES = 50 * 1024 * 1024
URL_WORKFLOW_TIMEOUT = 20


def _workflows_dir() -> str:
    import folder_paths
    return os.path.join(folder_paths.base_path, "user", "default", "workflows")


def list_workflow_files() -> list[str]:
    d = _workflows_dir()
    files = []
    if os.path.isdir(d):
        for root, _, fnames in os.walk(d):
            for f in fnames:
                if f.endswith(".json"):
                    rel = os.path.relpath(os.path.join(root, f), d)
                    files.append(rel.replace(os.sep, "/"))
    result = [PLACEHOLDER] + sorted(files)
    log.debug("[Subworkflow] discovered %d workflow file(s) in %s", len(files), d)
    return result


def load_workflow_file(filename: str) -> dict:
    path = os.path.join(_workflows_dir(), filename)
    log.debug("[Subworkflow] loading workflow file %r", filename)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    log.debug(
        "[Subworkflow] loaded workflow file %r format=%s top_level_keys=%s",
        filename,
        "UI" if is_ui_format(data) else "API",
        sorted(data.keys())[:12],
    )
    return data


def load_workflow_url(url: str, verify_ssl: bool = True) -> dict:
    log.debug("[Subworkflow] URL loader entered with url=%r verify_ssl=%s", url, verify_ssl)
    parsed = urllib.parse.urlparse(url)
    log.debug(
        "[Subworkflow] URL loader parsed scheme=%r netloc=%r path=%r query_present=%s",
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        bool(parsed.query),
    )
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        log.warning("[Subworkflow] URL loader rejecting invalid absolute URL %r", url)
        raise ValueError("Workflow URL must be an absolute http:// or https:// URL.")

    log.debug(
        "[Subworkflow] URL loader opening URL %r timeout=%s max_bytes=%s verify_ssl=%s",
        url,
        URL_WORKFLOW_TIMEOUT,
        MAX_URL_WORKFLOW_BYTES,
        verify_ssl,
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ComfyUI-Subworkflow/1.0"},
    )
    context = None if verify_ssl else ssl._create_unverified_context()
    if not verify_ssl:
        log.warning("[Subworkflow] URL loader SSL certificate verification disabled for %r", url)
    try:
        with urllib.request.urlopen(request, timeout=URL_WORKFLOW_TIMEOUT, context=context) as response:
            status = getattr(response, "status", 200)
            log.debug(
                "[Subworkflow] URL loader response opened status=%s content_type=%r content_length=%r final_url=%r",
                status,
                response.headers.get("Content-Type"),
                response.headers.get("Content-Length"),
                response.geturl(),
            )
            if status < 200 or status >= 300:
                log.warning("[Subworkflow] URL loader rejecting HTTP status %s for %r", status, url)
                raise ValueError(f"Workflow URL returned HTTP {status}.")

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_URL_WORKFLOW_BYTES:
                log.warning(
                    "[Subworkflow] URL loader rejecting oversized Content-Length=%s for %r",
                    content_length,
                    url,
                )
                raise ValueError(
                    f"Workflow URL response is too large "
                    f"({content_length} bytes; limit {MAX_URL_WORKFLOW_BYTES})."
                )

            raw = response.read(MAX_URL_WORKFLOW_BYTES + 1)
            log.debug("[Subworkflow] URL loader read %d byte(s) from %r", len(raw), url)
    except urllib.error.HTTPError as e:
        log.warning("[Subworkflow] URL loader HTTPError for %r: %s", url, e)
        raise ValueError(f"Workflow URL returned HTTP {e.code}.") from e
    except urllib.error.URLError as e:
        log.warning("[Subworkflow] URL loader URLError for %r: %s", url, e)
        raise ValueError(f"Failed to load workflow URL: {e.reason}") from e

    if len(raw) > MAX_URL_WORKFLOW_BYTES:
        log.warning("[Subworkflow] URL loader rejecting oversized body for %r", url)
        raise ValueError(
            f"Workflow URL response is too large "
            f"(limit {MAX_URL_WORKFLOW_BYTES} bytes)."
        )

    log.debug("[Subworkflow] URL loader decoding JSON from %r", url)
    data = json.loads(raw.decode("utf-8"))
    log.debug(
        "[Subworkflow] loaded workflow URL %r format=%s top_level_keys=%s",
        url,
        "UI" if is_ui_format(data) else "API",
        sorted(data.keys())[:12],
    )
    return data


def load_workflow(filename: str) -> dict:
    return load_workflow_file(filename)


def is_ui_format(data: dict) -> bool:
    return "nodes" in data


def _sort_key(node_id: str):
    try:
        return (0, int(node_id))
    except (ValueError, TypeError):
        return (1, node_id)


# ---------------------------------------------------------------------------
# I/O discovery
# ---------------------------------------------------------------------------

def get_workflow_io(data: dict) -> tuple[list[dict], list[dict]]:
    """
    Return the public outer-node inputs/outputs for a workflow.
    """
    info = get_workflow_interface(data)
    log.debug(
        "[Subworkflow] workflow public I/O discovered inputs=%s outputs=%s modifiers=%s",
        info["inputs"],
        info["outputs"],
        info["modifiers"],
    )
    return info["inputs"], info["outputs"]


def get_workflow_interface(data: dict) -> dict:
    """
    Return the boundary analysis for a workflow.

    Keys:
      raw_inputs/raw_outputs: every boundary node participating in expansion
      inputs/outputs: public sockets for the main outer Subworkflow node
      modifiers: modifier bridges exposed through Subworkflow Modifier Source
    """
    if is_ui_format(data):
        raw_inputs, raw_outputs, explicit_modifiers = _discover_workflow_io_ui(data)
    else:
        raw_inputs, raw_outputs, explicit_modifiers = _discover_workflow_io_api(data)
    return _analyze_workflow_io(raw_inputs, raw_outputs, explicit_modifiers)


def _copy_slot_info(slot: dict) -> dict:
    result = {
        "node_id": slot["node_id"],
        "slot_name": slot["slot_name"],
        "type": slot.get("type") or "*",
    }
    if "default" in slot:
        result["default"] = slot["default"]
    return result


def _analyze_workflow_io(
    raw_inputs: list[dict],
    raw_outputs: list[dict],
    explicit_modifiers: list[dict],
) -> dict:
    modifiers_by_output_node: dict[str, dict] = {}

    for item in explicit_modifiers:
        modifiers_by_output_node[item["output_node_id"]] = {
            "slot_name": item["slot_name"],
            "type": item.get("type") or "*",
            "input_node_id": item["input_node_id"],
            "output_node_id": item["output_node_id"],
        }

    modifiers = sorted(
        modifiers_by_output_node.values(),
        key=lambda item: (_sort_key(item["output_node_id"]), item["slot_name"]),
    )
    modifier_output_ids = {item["output_node_id"] for item in modifiers}

    public_inputs = [_copy_slot_info(item) for item in raw_inputs]
    public_outputs = [
        _copy_slot_info(item)
        for item in raw_outputs
        if item["node_id"] not in modifier_output_ids
    ]

    return {
        "raw_inputs": [_copy_slot_info(item) for item in raw_inputs],
        "raw_outputs": [_copy_slot_info(item) for item in raw_outputs],
        "inputs": public_inputs,
        "outputs": public_outputs,
        "modifiers": modifiers,
    }


def _extract_ui_input_default(
    node_id: str,
    nodes_by_id: dict,
    link_map: dict,
    value_sources: dict,
    slot_type: str,
):
    """
    Try to extract a literal default value for a SubworkflowInput node from its
    fallback connection when that connection resolves to a UI widget-value node.
    Returns None if no literal default can be determined.
    """
    node = nodes_by_id.get(str(node_id))
    if not node:
        return None
    value_link = None
    for inp in node.get("inputs") or []:
        if inp.get("name") == "value" and inp.get("link") is not None:
            value_link = inp["link"]
            break
    if value_link is None:
        return None
    src = link_map.get(str(value_link))
    if src is None:
        return None
    src_node_id, src_slot = str(src[0]), int(src[1])
    if src_node_id not in value_sources:
        return None
    raw = value_sources[src_node_id].get(src_slot)
    if raw is None:
        return None
    if slot_type == "INT":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if slot_type == "FLOAT":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _discover_workflow_io_ui(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    nodes_list = data.get("nodes", [])
    subgraph_defs = _build_subgraph_defs(data)
    parsed_links = [_parse_link(lnk) for lnk in data.get("links", [])]
    link_map = {lid: (src, ss) for lid, src, ss, _, _ in parsed_links}
    value_sources = _build_widget_value_sources(nodes_list, subgraph_defs)
    nodes_by_id = {str(node.get("id")): node for node in nodes_list}

    inputs, outputs, modifiers = [], [], []
    for node in nodes_list:
        ntype = _node_class_type(node)
        nid = str(node.get("id"))
        if ntype == SWF_SUBWORKFLOW_INPUT:
            slot_name = _boundary_slot_name(node, nid)
            slot_type = _boundary_output_type(node)
            default = _extract_ui_input_default(nid, nodes_by_id, link_map, value_sources, slot_type)
            log.debug(
                "[Subworkflow] found UI input boundary node=%s slot=%r type=%s default=%r",
                nid,
                slot_name,
                slot_type,
                default,
            )
            inputs.append({"node_id": nid, "slot_name": slot_name, "type": slot_type, "default": default})
        elif ntype == SWF_SUBWORKFLOW_MODIFIER:
            slot_name = _boundary_slot_name(node, nid)
            slot_type = _boundary_output_type(node) or _boundary_value_input_type(node)
            log.debug(
                "[Subworkflow] found UI modifier boundary node=%s slot=%r type=%s",
                nid,
                slot_name,
                slot_type,
            )
            modifier_info = {"node_id": nid, "slot_name": slot_name, "type": slot_type}
            inputs.append(modifier_info)
            outputs.append(modifier_info)
            modifiers.append({
                "slot_name": slot_name,
                "type": slot_type,
                "input_node_id": nid,
                "output_node_id": nid,
            })
        elif ntype == SWF_SUBWORKFLOW_OUTPUT:
            slot_name = _boundary_slot_name(node, nid)
            slot_type = _boundary_output_type(node) or _boundary_value_input_type(node)
            log.debug(
                "[Subworkflow] found UI output boundary node=%s slot=%r type=%s",
                nid,
                slot_name,
                slot_type,
            )
            outputs.append({"node_id": nid, "slot_name": slot_name, "type": slot_type})
    inputs.sort(key=lambda x: _sort_key(x["node_id"]))
    outputs.sort(key=lambda x: _sort_key(x["node_id"]))
    modifiers.sort(key=lambda x: (_sort_key(x["output_node_id"]), x["slot_name"]))
    return inputs, outputs, modifiers


def _boundary_slot_name(node: dict, fallback: str) -> str:
    widgets = node.get("widgets_values") or []
    if isinstance(widgets, list) and widgets:
        return widgets[0]
    if isinstance(widgets, dict):
        return widgets.get("slot_name") or widgets.get("value") or fallback
    return fallback


def _boundary_output_type(node: dict) -> str:
    outputs = node.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        return outputs[0].get("type") or "*"
    return "*"


def _boundary_value_input_type(node: dict) -> str:
    for inp in node.get("inputs") or []:
        if inp.get("name") == "value":
            return inp.get("type") or "*"
    return "*"


def _discover_workflow_io_api(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    inputs, outputs, modifiers = [], [], []
    for nid, node in data.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        slot = node.get("inputs", {}).get("slot_name", nid)
        if ct == SWF_SUBWORKFLOW_INPUT:
            value_input = node.get("inputs", {}).get("value")
            # Only treat as a literal default when it is not a graph link reference.
            default = None
            if not (
                isinstance(value_input, list)
                and len(value_input) == 2
                and isinstance(value_input[0], (str, int))
            ):
                default = value_input
            log.debug("[Subworkflow] found API input boundary node=%s slot=%r type=* default=%r", nid, slot, default)
            inputs.append({"node_id": nid, "slot_name": slot, "type": "*", "default": default})
        elif ct == SWF_SUBWORKFLOW_MODIFIER:
            log.debug("[Subworkflow] found API modifier boundary node=%s slot=%r type=*", nid, slot)
            modifier_info = {"node_id": nid, "slot_name": slot, "type": "*"}
            inputs.append(modifier_info)
            outputs.append(modifier_info)
            modifiers.append({
                "slot_name": slot,
                "type": "*",
                "input_node_id": nid,
                "output_node_id": nid,
            })
        elif ct == SWF_SUBWORKFLOW_OUTPUT:
            log.debug("[Subworkflow] found API output boundary node=%s slot=%r type=*", nid, slot)
            outputs.append({"node_id": nid, "slot_name": slot, "type": "*"})
    inputs.sort(key=lambda x: _sort_key(x["node_id"]))
    outputs.sort(key=lambda x: _sort_key(x["node_id"]))
    modifiers.sort(key=lambda x: (_sort_key(x["output_node_id"]), x["slot_name"]))
    return inputs, outputs, modifiers


# ---------------------------------------------------------------------------
# Widget value resolution (UI format only)
# ---------------------------------------------------------------------------

def _node_class_type(node: dict) -> str | None:
    """
    Resolve the ComfyUI class type for a UI-format node.

    In standard LiteGraph format the class type lives in node["type"].
    In newer ComfyUI builds the type field holds a UUID.  For regular nodes
    the real class name is in node["properties"]["Node name for S&R"].
    For group nodes the UUID itself IS the registered class key in
    NODE_CLASS_MAPPINGS, so we fall back to the UUID when the property is absent.
    """
    ct = node.get("type")
    if not ct:
        return None
    if not _UUID_RE.match(str(ct)):
        return ct  # plain class name, use as-is
    # UUID: prefer the human-readable S&R name, fall back to UUID (group nodes)
    return (node.get("properties") or {}).get("Node name for S&R") or ct


def _parse_link(lnk) -> tuple[str, str, int, str, int]:
    """
    Normalise a link entry to (link_id, src_node_id, src_slot, dst_node_id, dst_slot).
    Handles both the classic array format [id, src, src_slot, dst, dst_slot, type]
    and the newer object format {"id":…, "origin_id":…, "origin_slot":…, …}.
    """
    if isinstance(lnk, dict):
        return (
            str(lnk.get("id", "")),
            str(lnk.get("origin_id", "")),
            int(lnk.get("origin_slot", 0)),
            str(lnk.get("target_id", "")),
            int(lnk.get("target_slot", 0)),
        )
    return (str(lnk[0]), str(lnk[1]), int(lnk[2]), str(lnk[3]), int(lnk[4]))


def _is_bypassed_node(node: dict) -> bool:
    return node.get("mode") == 4


def _node_has_linked_inputs(node: dict) -> bool:
    return any(inp.get("link") is not None for inp in (node.get("inputs") or []))


def _output_has_links(output: dict) -> bool:
    links = output.get("links")
    if isinstance(links, list):
        return len(links) > 0
    return links is not None


def _node_has_linked_outputs(node: dict) -> bool:
    return any(_output_has_links(out) for out in (node.get("outputs") or []))


def _is_ui_widget_value_node(node: dict, class_type: str | None, subgraph_defs: dict | None = None) -> bool:
    """
    Return True for non-executable UI helper nodes that act as a literal widget source.

    These are safe to fold into values only when they have no backend class, no linked
    inputs, and exactly one widget-backed output.
    """
    if not class_type:
        return False
    if subgraph_defs and class_type in subgraph_defs:
        return False

    import nodes as _comfy_nodes

    if class_type in _comfy_nodes.NODE_CLASS_MAPPINGS:
        return False
    if _node_has_linked_inputs(node):
        return False

    outputs = node.get("outputs") or []
    widgets_values = node.get("widgets_values")
    if len(outputs) != 1 or not isinstance(widgets_values, list) or not widgets_values:
        return False

    widget = outputs[0].get("widget") if isinstance(outputs[0], dict) else None
    return isinstance(widget, dict) and bool(widget.get("name"))


def _is_ui_decoration_node(node: dict, class_type: str | None, subgraph_defs: dict | None = None) -> bool:
    """
    Return True for non-executable UI-only nodes that have no runtime participation.
    """
    if not class_type:
        return False
    if subgraph_defs and class_type in subgraph_defs:
        return False

    import nodes as _comfy_nodes

    if class_type in _comfy_nodes.NODE_CLASS_MAPPINGS:
        return False
    if _is_ui_widget_value_node(node, class_type, subgraph_defs):
        return False

    return not _node_has_linked_inputs(node) and not _node_has_linked_outputs(node)


def _is_ui_virtual_node(node: dict, class_type: str | None, subgraph_defs: dict | None = None) -> bool:
    return _is_ui_decoration_node(node, class_type, subgraph_defs) or _is_ui_widget_value_node(
        node,
        class_type,
        subgraph_defs,
    )


def _build_widget_value_sources(
    nodes_list: list[dict],
    subgraph_defs: dict | None = None,
) -> dict[str, dict[int, object]]:
    """
    Return {node_id: {output_slot: literal_value}} for UI-only nodes whose outputs
    should be treated as widget literals during expansion.
    """
    value_sources: dict[str, dict[int, object]] = {}
    for node in nodes_list:
        node_id = str(node.get("id"))
        class_type = _node_class_type(node)
        if not _is_ui_widget_value_node(node, class_type, subgraph_defs):
            continue

        widgets_values = node.get("widgets_values")
        output_values = {0: widgets_values[0]}

        if output_values:
            value_sources[node_id] = output_values
            log.debug(
                "[Subworkflow] widget value node %s (%s) output mapping=%s",
                node_id,
                class_type,
                output_values,
            )
    return value_sources


def _build_bypass_sources(nodes_list: list[dict], link_map: dict) -> dict[str, dict[int, tuple[str, int]]]:
    """
    Return {bypassed_node_id: {output_slot: (source_node_id, source_slot)}}.

    ComfyUI UI-format workflows keep bypassed nodes in the saved graph with
    mode=4, but normal prompt conversion rewires around them.  GraphBuilder
    expansion needs to perform the same rewrite explicitly.
    """
    bypass_sources: dict[str, dict[int, tuple[str, int]]] = {}
    for node in nodes_list:
        if not _is_bypassed_node(node):
            continue

        node_id = str(node.get("id"))
        inputs = node.get("inputs") or []
        outputs = node.get("outputs") or []
        linked_inputs = []
        for index, inp in enumerate(inputs):
            link_id = inp.get("link")
            if link_id is None:
                continue
            src = link_map.get(str(link_id))
            if src is not None:
                linked_inputs.append((index, inp.get("type"), src))

        output_sources: dict[int, tuple[str, int]] = {}
        for output_index, out in enumerate(outputs):
            output_type = out.get("type")
            selected = None

            for input_index, _, src in linked_inputs:
                if input_index == output_index:
                    selected = src
                    break
            if selected is None:
                for _, input_type, src in linked_inputs:
                    if input_type == output_type:
                        selected = src
                        break
            if selected is None and linked_inputs:
                selected = linked_inputs[0][2]

            if selected is not None:
                output_sources[output_index] = selected

        bypass_sources[node_id] = output_sources
        log.debug(
            "[Subworkflow] bypass node %s (%s) output mapping=%s",
            node_id,
            _node_class_type(node),
            output_sources,
        )
    return bypass_sources


def _iter_widget_specs(class_type: str, linked_names: set):
    import nodes as _comfy_nodes
    cls = _comfy_nodes.NODE_CLASS_MAPPINGS.get(class_type)
    if cls is None:
        return
    try:
        input_types = cls.INPUT_TYPES()
    except Exception:
        return

    widget_index = 0
    for category in ("required", "optional"):
        for name, type_def in input_types.get(category, {}).items():
            if not isinstance(type_def, (list, tuple)):
                continue
            input_type = type_def[0]
            opts = type_def[1] if len(type_def) > 1 and isinstance(type_def[1], dict) else {}
            if opts.get("forceInput"):
                continue
            if not (
                isinstance(input_type, list)
                or input_type in ("COMBO", "INT", "FLOAT", "STRING", "BOOLEAN")
            ):
                continue

            skip = name in linked_names
            control_index = None
            if opts.get("control_after_generate"):
                control_index = widget_index + 1
            yield {
                "name": name,
                "input_type": input_type,
                "opts": opts,
                "index": widget_index,
                "skip": skip,
                "control_index": control_index,
            }
            widget_index += 2 if control_index is not None else 1


def _widget_input_type(input_def: dict) -> str | None:
    widget = input_def.get("widget")
    if not isinstance(widget, dict) or not widget.get("name"):
        return None
    input_type = input_def.get("type")
    if input_type in ("COMBO", "INT", "FLOAT", "STRING", "BOOLEAN"):
        return input_type
    return None


def _looks_like_control_after_generate(input_type: str, widgets_values: list, value_index: int) -> bool:
    if input_type not in ("INT", "FLOAT"):
        return False
    control_index = value_index + 1
    if control_index >= len(widgets_values):
        return False
    return str(widgets_values[control_index]).lower() in {
        "fixed",
        "increment",
        "decrement",
        "randomize",
    }


def _get_widget_values_from_saved_inputs(
    class_type: str,
    linked_names: set,
    node_inputs: list,
    widgets_values: list,
) -> dict | None:
    result = {}
    widget_index = 0
    consumed_widget_names = []

    for inp in node_inputs:
        widget_name = (inp.get("widget") or {}).get("name")
        input_type = _widget_input_type(inp)
        if not widget_name or input_type is None:
            continue
        if widget_index >= len(widgets_values):
            break

        value = widgets_values[widget_index]
        has_control = _looks_like_control_after_generate(input_type, widgets_values, widget_index)
        consumed_widget_names.append(widget_name)

        if widget_name not in linked_names:
            result[widget_name] = value

        widget_index += 2 if has_control else 1

    if widget_index == 0:
        return None

    if widget_index < len(widgets_values):
        class_specs = list(_iter_widget_specs(class_type, linked_names) or [])
        remaining_specs = [
            spec for spec in class_specs
            if spec["name"] not in consumed_widget_names
        ]
        applied = []
        for offset, spec in enumerate(remaining_specs):
            index = widget_index + offset
            if index >= len(widgets_values):
                break
            name = spec["name"]
            applied.append(name)
            if not spec["skip"]:
                result[name] = widgets_values[index]

        if widget_index + len(applied) >= len(widgets_values):
            log.debug(
                "[Subworkflow] node type %s saved input widget metadata is incomplete "
                "(mapped prefix %d/%d widget value(s), names=%s); appended missing "
                "widget names from class order=%s",
                class_type,
                widget_index,
                len(widgets_values),
                consumed_widget_names,
                applied,
            )
            return result

        log.debug(
            "[Subworkflow] node type %s saved input widget metadata is incomplete "
            "(mapped %d/%d widget value(s), names=%s); falling back to class widget order",
            class_type,
            widget_index,
            len(widgets_values),
            consumed_widget_names,
        )
        return None

    return result


def _get_widget_values(class_type: str, linked_names: set, widgets_values, node_inputs: list | None = None) -> dict:
    """
    Return {widget_name: value} by aligning widgets_values with the full ordered
    widget list for the node class, including hidden control-after-generate
    widgets that ComfyUI stores next to controlled numeric widgets.
    """
    result = {}
    if isinstance(widgets_values, dict):
        for spec in _iter_widget_specs(class_type, linked_names):
            name = spec["name"]
            if not spec["skip"] and name in widgets_values:
                result[name] = widgets_values[name]
        return result

    if not isinstance(widgets_values, list):
        log.warning(
            "[Subworkflow] node type %s has unsupported widgets_values type %s",
            class_type,
            type(widgets_values).__name__,
        )
        return result

    if node_inputs:
        saved_result = _get_widget_values_from_saved_inputs(
            class_type,
            linked_names,
            node_inputs,
            widgets_values,
        )
        if saved_result is not None:
            return saved_result

    for spec in _iter_widget_specs(class_type, linked_names):
        index = spec["index"]
        if index >= len(widgets_values):
            break
        if not spec["skip"]:
            result[spec["name"]] = widgets_values[index]
    return result


def _next_controlled_value(value, input_type: str, opts: dict, mode: str):
    mode = str(mode).lower()
    if mode in ("fixed", "none", ""):
        return value

    min_value = opts.get("min", 0)
    max_value = opts.get("max", 0xffffffffffffffff if input_type == "INT" else 1.0)
    step = opts.get("step", 1)

    if input_type == "INT":
        min_value = int(min_value)
        max_value = int(max_value)
        step = int(step) if step else 1
        value = int(value)
        if mode == "increment":
            return min_value if value + step > max_value else value + step
        if mode == "decrement":
            return max_value if value - step < min_value else value - step
        if mode == "randomize":
            return random.randint(min_value, max_value)
    elif input_type == "FLOAT":
        min_value = float(min_value)
        max_value = float(max_value)
        step = float(step) if step else 1.0
        value = float(value)
        if mode == "increment":
            return min_value if value + step > max_value else value + step
        if mode == "decrement":
            return max_value if value - step < min_value else value - step
        if mode == "randomize":
            return random.uniform(min_value, max_value)

    return value


def _apply_control_after_generate_to_nodes(nodes_list: list, location: str) -> tuple[int, int]:
    candidates = 0
    changed = 0
    for node in nodes_list:
        class_type = _node_class_type(node)
        widgets_values = node.get("widgets_values")
        if not class_type or not isinstance(widgets_values, list):
            continue

        linked_names = {
            inp.get("name")
            for inp in (node.get("inputs") or [])
            if inp.get("name") and inp.get("link") is not None
        }
        for spec in _iter_widget_specs(class_type, linked_names):
            value_index = spec["index"]
            control_index = spec["control_index"]
            if control_index is None or control_index >= len(widgets_values):
                continue
            if value_index >= len(widgets_values):
                continue

            candidates += 1
            old_value = widgets_values[value_index]
            mode = widgets_values[control_index]
            try:
                new_value = _next_controlled_value(old_value, spec["input_type"], spec["opts"], mode)
            except (TypeError, ValueError) as e:
                log.warning(
                    "[Subworkflow] control-after-generate skipped %s node %s %s value=%r mode=%r: %s",
                    location,
                    node.get("id"),
                    spec["name"],
                    old_value,
                    mode,
                    e,
                )
                continue
            if new_value == old_value:
                continue
            widgets_values[value_index] = new_value
            changed += 1
            log.debug(
                "[Subworkflow] control-after-generate updated %s node %s %s from %r to %r (%s)",
                location,
                node.get("id"),
                spec["name"],
                old_value,
                new_value,
                mode,
            )

    return candidates, changed


def apply_control_after_generate(data: dict) -> int:
    """
    Mutate cached UI-format workflow widget values the same way ComfyUI's
    frontend advances control-after-generate widgets between queued runs.
    """
    if not is_ui_format(data):
        return 0

    candidates, changed = _apply_control_after_generate_to_nodes(data.get("nodes", []), "workflow")

    for subgraph in ((data.get("definitions") or {}).get("subgraphs") or []):
        if not isinstance(subgraph, dict):
            continue
        sg_candidates, sg_changed = _apply_control_after_generate_to_nodes(
            subgraph.get("nodes") or [],
            f"subgraph {subgraph.get('id')}",
        )
        candidates += sg_candidates
        changed += sg_changed

    if changed:
        log.debug("[Subworkflow] updated %d cached control-after-generate widget(s)", changed)
    return changed


# ---------------------------------------------------------------------------
# Subgraph expansion
# ---------------------------------------------------------------------------

def build_expansion(
    data: dict,
    outer_inputs: dict,
    runtime_inputs_info: list[dict] | None = None,
    selected_outputs_info: list[dict] | None = None,
    boundary_inputs_info: list[dict] | None = None,
    boundary_outputs_info: list[dict] | None = None,
):
    """
    Build a GraphBuilder subgraph from an inner workflow.
    Accepts both UI format and API format.

    outer_inputs: {"swf_in_0": value, "swf_in_1": value, ...}
    Returns (output_refs, graph).
    """
    info = get_workflow_interface(data)
    runtime_inputs_info = runtime_inputs_info or info["inputs"]
    selected_outputs_info = selected_outputs_info or info["outputs"]
    boundary_inputs_info = boundary_inputs_info or info["raw_inputs"]
    boundary_outputs_info = boundary_outputs_info or info["raw_outputs"]

    if is_ui_format(data):
        return _build_expansion_ui(
            data,
            outer_inputs,
            runtime_inputs_info,
            selected_outputs_info,
            boundary_inputs_info,
            boundary_outputs_info,
        )
    return _build_expansion_api(
        data,
        outer_inputs,
        runtime_inputs_info,
        selected_outputs_info,
        boundary_inputs_info,
        boundary_outputs_info,
    )


def build_modifier_source_expansion(data: dict, outer_inputs: dict):
    info = get_workflow_interface(data)
    if not info["modifiers"]:
        raise ValueError("No Subworkflow Modifier nodes found in inner workflow.")

    selected_outputs_info = [
        item for item in info["raw_outputs"]
        if item["node_id"] in {modifier["output_node_id"] for modifier in info["modifiers"]}
    ]
    return build_expansion(
        data,
        outer_inputs,
        runtime_inputs_info=[],
        selected_outputs_info=selected_outputs_info,
        boundary_inputs_info=info["raw_inputs"],
        boundary_outputs_info=info["raw_outputs"],
    )


def _is_graph_link(value) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], (int, float))
    )


def _validate_outer_runtime_inputs(inputs_info: list[dict], outer_inputs: dict, workflow_format: str):
    for i, inp in enumerate(inputs_info):
        expected_type = inp.get("type") or "*"
        if expected_type in ("*", ""):
            continue

        key = f"swf_in_{i}"
        value = outer_inputs.get(key)
        if value is None or _is_graph_link(value):
            continue

        if expected_type == "VIDEO" and not hasattr(value, "get_components"):
            raise TypeError(
                f"Subworkflow input {i} '{inp.get('slot_name')}' expects VIDEO "
                f"from {workflow_format} boundary node {inp.get('node_id')}, "
                f"but received {type(value).__name__}. Connect a VIDEO output, "
                "not IMAGE frames."
            )


def _hide_expanded_node_display(gb_node):
    """
    Prevent UI-emitting inner nodes from attaching previews to the outer
    Subworkflow wrapper node.
    """
    gb_node.set_override_display_id(f"__swf_internal__:{gb_node.id}")


def _build_subgraph_defs(data: dict) -> dict:
    """Extract subgraph (group node) definitions from workflow data, keyed by UUID."""
    result = {}
    for sg in ((data.get("definitions") or {}).get("subgraphs") or []):
        if isinstance(sg, dict) and sg.get("id"):
            result[sg["id"]] = sg
    return result


def _format_missing_node_error(missing_nodes: list[dict], workflow_format: str) -> str:
    lines = [
        f"Inner {workflow_format} workflow uses node types that are not installed in this ComfyUI instance."
    ]
    for item in missing_nodes:
        lines.append(
            f"- node {item['node_id']}: {item['class_type']}"
            + (f" ({item['title']})" if item.get("title") else "")
        )
    lines.append("Install the missing custom node package(s) and run the subworkflow again.")
    return "\n".join(lines)


def _missing_ui_nodes(nodes_list: list[dict], subgraph_defs: dict) -> list[dict]:
    import nodes as _comfy_nodes

    missing = []
    seen = set()
    for node in nodes_list:
        node_id = str(node.get("id"))
        class_type = _node_class_type(node)
        if not class_type:
            key = (node_id, "<unknown>")
            if key not in seen:
                seen.add(key)
                missing.append({
                    "node_id": node_id,
                    "class_type": "<unknown>",
                    "title": node.get("title"),
                })
            continue
        if _is_ui_virtual_node(node, class_type, subgraph_defs):
            continue
        if class_type in subgraph_defs or class_type in _comfy_nodes.NODE_CLASS_MAPPINGS:
            continue
        key = (node_id, class_type)
        if key in seen:
            continue
        seen.add(key)
        missing.append({
            "node_id": node_id,
            "class_type": class_type,
            "title": node.get("title"),
        })
    return missing


def _missing_api_nodes(data: dict) -> list[dict]:
    import nodes as _comfy_nodes

    missing = []
    seen = set()
    for node_id, node in data.items():
        if str(node_id).startswith("_"):
            continue
        class_type = node.get("class_type")
        if not class_type:
            key = (str(node_id), "<unknown>")
            if key not in seen:
                seen.add(key)
                missing.append({
                    "node_id": str(node_id),
                    "class_type": "<unknown>",
                    "title": node.get("_meta", {}).get("title") if isinstance(node.get("_meta"), dict) else None,
                })
            continue
        if class_type in _comfy_nodes.NODE_CLASS_MAPPINGS:
            continue
        key = (str(node_id), class_type)
        if key in seen:
            continue
        seen.add(key)
        missing.append({
            "node_id": str(node_id),
            "class_type": class_type,
            "title": node.get("_meta", {}).get("title") if isinstance(node.get("_meta"), dict) else None,
        })
    return missing


def validate_workflow_nodes_installed(data: dict):
    """
    Raise an execution-time error if the inner workflow references node types that
    are not installed in the current ComfyUI instance.
    """
    if is_ui_format(data):
        subgraph_defs = _build_subgraph_defs(data)
        missing = _missing_ui_nodes(data.get("nodes", []), subgraph_defs)
        for sg in subgraph_defs.values():
            missing.extend(_missing_ui_nodes(sg.get("nodes") or [], subgraph_defs))
        if missing:
            log.warning("[Subworkflow] UI workflow has missing node types: %s", missing)
            raise RuntimeError(_format_missing_node_error(missing, "UI"))
        return

    missing = _missing_api_nodes(data)
    if missing:
        log.warning("[Subworkflow] API workflow has missing node types: %s", missing)
        raise RuntimeError(_format_missing_node_error(missing, "API"))


def _expand_subgraph(outer_node: dict, sg_def: dict, outer_link_map: dict,
                     outer_resolve_fn, graph, id_prefix: str) -> list:
    """
    Expand a subgraph (group node) definition inline into the GraphBuilder.

    The subgraph uses two virtual boundary nodes:
      inputNode  (id = inputNode.id, e.g. -10): outputs carry each outer input value
      outputNode (id = outputNode.id, e.g. -20): inputs receive the subgraph outputs

    Returns a list of NodeRefs corresponding to sg_def['outputs'].
    """
    import nodes as _comfy_nodes

    sg_nodes       = sg_def.get("nodes") or []
    sg_links       = sg_def.get("links") or []
    sg_inputs_def  = sg_def.get("inputs") or []
    sg_outputs_def = sg_def.get("outputs") or []
    input_node_id  = str((sg_def.get("inputNode") or {}).get("id", -10))

    # Parse inner links.
    parsed = [_parse_link(lnk) for lnk in sg_links]
    sg_link_map = {lid: (src, ss) for lid, src, ss, _, _ in parsed}
    sg_bypass_sources = _build_bypass_sources(sg_nodes, sg_link_map)
    sg_value_sources = _build_widget_value_sources(sg_nodes, subgraph_defs={})

    # Build outer_values_by_slot: {subgraph_input_slot_index → resolved value}
    sg_input_name_to_slot = {inp.get("name"): i for i, inp in enumerate(sg_inputs_def)}
    outer_values_by_slot: dict[int, object] = {}
    for outer_inp in (outer_node.get("inputs") or []):
        name    = outer_inp.get("name")
        link_id = outer_inp.get("link")
        if name and link_id is not None:
            slot_idx = sg_input_name_to_slot.get(name)
            if slot_idx is not None:
                src = outer_link_map.get(str(link_id))
                if src:
                    outer_values_by_slot[slot_idx] = outer_resolve_fn(src[0], src[1])

    # Pass 1: register inner nodes (with prefixed IDs to avoid conflicts).
    sg_refs: dict = {}
    for node in sg_nodes:
        nid = str(node.get("id"))
        if nid in sg_bypass_sources:
            continue
        if nid in sg_value_sources:
            continue
        ct  = _node_class_type(node)
        if not ct:
            log.warning("[Subworkflow] subgraph node id=%s has no class_type, skipping", nid)
            continue
        if _is_ui_decoration_node(node, ct, subgraph_defs={}):
            continue
        if ct not in _comfy_nodes.NODE_CLASS_MAPPINGS:
            log.warning("[Subworkflow] subgraph node id=%s type=%r not in NODE_CLASS_MAPPINGS, skipping", nid, ct)
            continue
        gb_node = graph.node(ct, id=f"{id_prefix}_{nid}")
        _hide_expanded_node_display(gb_node)
        sg_refs[nid] = gb_node

    def resolve_sg_link(link_id: str):
        src = sg_link_map.get(str(link_id))
        if src is None:
            return None
        src_id, src_slot = str(src[0]), int(src[1])
        if src_id in sg_bypass_sources:
            bypass_src = sg_bypass_sources[src_id].get(src_slot)
            if bypass_src is None:
                log.warning("[Subworkflow] subgraph bypass node %s slot %d has no source", src_id, src_slot)
                return None
            if str(bypass_src[0]) == input_node_id:
                return outer_values_by_slot.get(int(bypass_src[1]))
            ref = sg_refs.get(str(bypass_src[0]))
            if ref is None:
                log.warning("[Subworkflow] subgraph bypass node %s source %s not in sg_refs", src_id, bypass_src[0])
                return None
            return ref.out(int(bypass_src[1]))
        if src_id in sg_value_sources:
            return sg_value_sources[src_id].get(src_slot)
        if src_id == input_node_id:
            return outer_values_by_slot.get(src_slot)
        ref = sg_refs.get(src_id)
        if ref is None:
            log.warning("[Subworkflow] subgraph link %s src node %s not in sg_refs", link_id, src_id)
            return None
        return ref.out(src_slot)

    # Pass 2: wire inner nodes.
    for node in sg_nodes:
        nid     = str(node.get("id"))
        gb_node = sg_refs.get(nid)
        if gb_node is None:
            continue
        ct             = _node_class_type(node)
        node_inputs    = node.get("inputs") or []
        widgets_values = node.get("widgets_values") or []

        linked_names: set = set()
        for inp in node_inputs:
            link_id = inp.get("link")
            name    = inp.get("name")
            if link_id is not None and name:
                resolved = resolve_sg_link(str(link_id))
                if resolved is not None:
                    linked_names.add(name)
                    gb_node.set_input(name, resolved)
                else:
                    src = sg_link_map.get(str(link_id))
                    if src and str(src[0]) == input_node_id:
                        pass  # outer not wired — fall through to inner widget default
                    else:
                        linked_names.add(name)
                        log.warning("[Subworkflow] subgraph node %s (%s) input %r unresolved", nid, ct, name)

        for wname, val in _get_widget_values(ct, linked_names, widgets_values, node_inputs).items():
            gb_node.set_input(wname, val)

    # Collect output refs from the subgraph's virtual outputNode.
    output_refs = []
    for out_def in sg_outputs_def:
        link_ids = out_def.get("linkIds") or []
        if not link_ids:
            log.warning("[Subworkflow] subgraph output %r has no linkIds", out_def.get("name"))
            output_refs.append(None)
            continue
        src = sg_link_map.get(str(link_ids[0]))
        if src is None:
            log.warning("[Subworkflow] subgraph output link %s not in sg_link_map", link_ids[0])
            output_refs.append(None)
            continue
        src_id, src_slot = str(src[0]), int(src[1])
        if src_id in sg_bypass_sources:
            bypass_src = sg_bypass_sources[src_id].get(src_slot)
            if bypass_src is None:
                log.warning("[Subworkflow] subgraph output bypass node %s slot %d has no source", src_id, src_slot)
                output_refs.append(None)
                continue
            src_id, src_slot = str(bypass_src[0]), int(bypass_src[1])
            if src_id == input_node_id:
                output_refs.append(outer_values_by_slot.get(src_slot))
                continue
        ref = sg_refs.get(src_id)
        if ref is None:
            log.warning("[Subworkflow] subgraph output src node %s not in sg_refs", src_id)
            output_refs.append(None)
            continue
        output_refs.append(ref.out(src_slot))

    return output_refs


def _build_expansion_ui(
    data: dict,
    outer_inputs: dict,
    runtime_inputs_info: list[dict],
    selected_outputs_info: list[dict],
    boundary_inputs_info: list[dict],
    boundary_outputs_info: list[dict],
):
    nodes_list = data.get("nodes", [])
    links_list = data.get("links", [])

    subgraph_defs = _build_subgraph_defs(data)

    parsed_links = [_parse_link(lnk) for lnk in links_list]
    link_map = {lid: (src, ss) for lid, src, ss, _, _ in parsed_links}
    bypass_sources = _build_bypass_sources(nodes_list, link_map)
    value_sources = _build_widget_value_sources(nodes_list, subgraph_defs)
    nodes_by_id = {str(node.get("id")): node for node in nodes_list}
    dst_to_src: dict[str, tuple[str, int]] = {}
    for _, src, ss, dst, _ in parsed_links:
        dst_to_src.setdefault(dst, (src, ss))

    _validate_outer_runtime_inputs(runtime_inputs_info, outer_inputs, "UI")

    fi_node_ids  = {inp["node_id"] for inp in boundary_inputs_info}
    fo_node_ids  = {out["node_id"] for out in boundary_outputs_info}
    func_node_ids = fi_node_ids | fo_node_ids
    fo_src = {out["node_id"]: dst_to_src.get(out["node_id"]) for out in boundary_outputs_info}

    fi_value = {
        inp["node_id"]: outer_inputs.get(f"swf_in_{i}")
        for i, inp in enumerate(runtime_inputs_info)
    }
    fi_fallback_src: dict[str, tuple[str, int]] = {}
    for inp in boundary_inputs_info:
        node = nodes_by_id.get(inp["node_id"]) or {}
        node_inputs = node.get("inputs") or []
        fallback_link = None
        for node_input in node_inputs:
            if node_input.get("name") == "value" and node_input.get("link") is not None:
                fallback_link = node_input.get("link")
                break
        if fallback_link is None:
            for node_input in node_inputs:
                if node_input.get("link") is not None:
                    fallback_link = node_input.get("link")
                    break
        if fallback_link is not None:
            src = link_map.get(str(fallback_link))
            if src is not None:
                fi_fallback_src[inp["node_id"]] = src

    missing = [
        f"swf_in_{i}:{inp['slot_name']}({inp['node_id']})"
        for i, inp in enumerate(runtime_inputs_info)
        if outer_inputs.get(f"swf_in_{i}") is None and inp["node_id"] not in fi_fallback_src
    ]
    if missing:
        log.warning("[Subworkflow] missing UI inner input value(s) and fallback link(s): %s", missing)
    log.debug(
        "[Subworkflow] building UI expansion with %d input(s), %d output(s), %d inner node(s), outer_input_keys=%s",
        len(runtime_inputs_info),
        len(selected_outputs_info),
        len(nodes_list),
        sorted(k for k in outer_inputs if k.startswith("swf_in_")),
    )

    graph = GraphBuilder()
    node_refs: dict = {}
    subgraph_outputs: dict = {}  # nid → [output_ref, ...]

    def resolve_input_boundary_value(node_id: str):
        value = fi_value.get(node_id)
        if value is not None:
            return value
        src = fi_fallback_src.get(node_id)
        return resolve_link(src[0], src[1]) if src else None

    def resolve_link(src_node_id: str, src_slot: int):
        if src_node_id in fi_value:
            return resolve_input_boundary_value(src_node_id)
        if src_node_id in fo_src:
            src = fo_src[src_node_id]
            return resolve_link(src[0], src[1]) if src else None
        if src_node_id in bypass_sources:
            src = bypass_sources[src_node_id].get(src_slot)
            if src is None:
                log.warning("[Subworkflow] bypass node %s slot %d has no source", src_node_id, src_slot)
                return None
            return resolve_link(src[0], src[1])
        if src_node_id in value_sources:
            return value_sources[src_node_id].get(src_slot)
        if src_node_id in subgraph_outputs:
            refs = subgraph_outputs[src_node_id]
            return refs[src_slot] if src_slot < len(refs) else None
        ref = node_refs.get(src_node_id)
        if ref is None:
            log.warning("[Subworkflow] node %s slot %d unresolvable", src_node_id, src_slot)
        return ref.out(src_slot) if ref is not None else None

    import nodes as _comfy_nodes

    # Pass 1: register regular inner nodes (skip SWF boundary and subgraph nodes).
    for node in nodes_list:
        nid = str(node["id"])
        if nid in func_node_ids:
            continue
        if nid in bypass_sources:
            continue
        if nid in value_sources:
            continue
        ct = _node_class_type(node)
        if not ct:
            log.warning("[Subworkflow] node id=%s has no resolvable class_type, skipping", nid)
            continue
        if ct in subgraph_defs:
            continue  # expanded separately below
        if _is_ui_decoration_node(node, ct, subgraph_defs):
            continue
        if ct not in _comfy_nodes.NODE_CLASS_MAPPINGS:
            log.warning("[Subworkflow] node id=%s type=%r not in NODE_CLASS_MAPPINGS, skipping", nid, ct)
            continue
        gb_node = graph.node(ct, id=nid)
        _hide_expanded_node_display(gb_node)
        node_refs[nid] = gb_node

    # Subgraph expansion pass (runs after pass 1 so node_refs is populated).
    for node in nodes_list:
        nid = str(node["id"])
        if nid in func_node_ids:
            continue
        if nid in bypass_sources:
            continue
        if nid in value_sources:
            continue
        ct = _node_class_type(node)
        if not ct or ct not in subgraph_defs:
            continue
        refs = _expand_subgraph(
            outer_node=node,
            sg_def=subgraph_defs[ct],
            outer_link_map=link_map,
            outer_resolve_fn=resolve_link,
            graph=graph,
            id_prefix=nid,
        )
        subgraph_outputs[nid] = refs

    # Pass 2: wire inputs for regular inner nodes.
    for node in nodes_list:
        nid = str(node["id"])
        if nid in func_node_ids:
            continue
        gb_node = node_refs.get(nid)
        if gb_node is None:
            continue  # subgraph nodes are not in node_refs

        ct             = _node_class_type(node)
        node_inputs    = node.get("inputs") or []
        widgets_values = node.get("widgets_values") or []

        linked_names: set = set()
        for inp in node_inputs:
            link_id = inp.get("link")
            name    = inp.get("name")
            if link_id is not None and name:
                linked_names.add(name)
                src = link_map.get(str(link_id))
                if src:
                    resolved = resolve_link(src[0], src[1])
                    if resolved is not None:
                        gb_node.set_input(name, resolved)
                    else:
                        log.warning("[Subworkflow] node %s (%s) input %r unresolved", nid, ct, name)
                else:
                    log.warning("[Subworkflow] node %s (%s) input %r: link %s not in link_map",
                                nid, ct, name, link_id)

        for wname, val in _get_widget_values(ct, linked_names, widgets_values, node_inputs).items():
            gb_node.set_input(wname, val)

    # Collect output refs from Subworkflow Output nodes.
    output_refs = []
    for out in selected_outputs_info:
        src = dst_to_src.get(out["node_id"])
        if src is None and out["node_id"] in fi_node_ids:
            ref = resolve_input_boundary_value(out["node_id"])
        else:
            if src is None:
                log.warning("[Subworkflow] Subworkflow Output node=%s has no incoming link", out["node_id"])
            ref = resolve_link(src[0], src[1]) if src else None
        output_refs.append(ref)

    return output_refs, graph


def _build_expansion_api(
    data: dict,
    outer_inputs: dict,
    runtime_inputs_info: list[dict],
    selected_outputs_info: list[dict],
    boundary_inputs_info: list[dict],
    boundary_outputs_info: list[dict],
):
    _validate_outer_runtime_inputs(runtime_inputs_info, outer_inputs, "API")

    fi_value = {
        inp["node_id"]: outer_inputs.get(f"swf_in_{i}")
        for i, inp in enumerate(runtime_inputs_info)
    }
    fi_fallback_value = {
        inp["node_id"]: data[inp["node_id"]].get("inputs", {}).get("value")
        for inp in boundary_inputs_info
        if inp["node_id"] in data
    }
    missing = [
        f"swf_in_{i}:{inp['slot_name']}({inp['node_id']})"
        for i, inp in enumerate(runtime_inputs_info)
        if outer_inputs.get(f"swf_in_{i}") is None and fi_fallback_value.get(inp["node_id"]) is None
    ]
    if missing:
        log.warning("[Subworkflow] missing API inner input value(s) and fallback value(s): %s", missing)
    log.debug(
        "[Subworkflow] building API expansion with %d input(s), %d output(s), %d inner node(s), outer_input_keys=%s",
        len(runtime_inputs_info),
        len(selected_outputs_info),
        len([nid for nid in data if not str(nid).startswith("_")]),
        sorted(k for k in outer_inputs if k.startswith("swf_in_")),
    )
    func_node_ids = {inp["node_id"] for inp in boundary_inputs_info} | {out["node_id"] for out in boundary_outputs_info}
    fo_src = {
        out["node_id"]: data[out["node_id"]].get("inputs", {}).get("value")
        for out in boundary_outputs_info
    }

    graph = GraphBuilder()
    node_refs: dict = {}

    def resolve_input_boundary_value(node_id: str):
        value = fi_value.get(node_id)
        if value is not None:
            return value
        fallback = fi_fallback_value.get(node_id)
        if isinstance(fallback, list) and len(fallback) == 2 and isinstance(fallback[0], (str, int)):
            return resolve_link(fallback)
        return fallback

    def resolve_link(link_val):
        src_id   = str(link_val[0])
        src_slot = int(link_val[1])
        if src_id in fi_value:
            return resolve_input_boundary_value(src_id)
        if src_id in fo_src:
            src = fo_src[src_id]
            return resolve_link(src) if isinstance(src, list) and len(src) == 2 else src
        ref = node_refs.get(src_id)
        if ref is None:
            log.warning("[Subworkflow] API node %s slot %d unresolvable", src_id, src_slot)
        return ref.out(src_slot) if ref is not None else None

    for nid, node in data.items():
        if nid.startswith("_") or nid in func_node_ids:
            continue
        ct = node.get("class_type")
        if ct is None:
            continue
        gb_node = graph.node(ct, id=nid)
        _hide_expanded_node_display(gb_node)
        node_refs[nid] = gb_node

    for nid, node in data.items():
        if nid.startswith("_") or nid in func_node_ids:
            continue
        gb_node = node_refs.get(nid)
        if gb_node is None:
            continue
        for inp_name, inp_val in node.get("inputs", {}).items():
            if isinstance(inp_val, list) and len(inp_val) == 2 and isinstance(inp_val[0], (str, int)):
                resolved = resolve_link(inp_val)
                if resolved is not None:
                    gb_node.set_input(inp_name, resolved)
                else:
                    log.warning("[Subworkflow] API node %s input %r unresolved link %s", nid, inp_name, inp_val)
            else:
                gb_node.set_input(inp_name, inp_val)

    output_refs = []
    for out in selected_outputs_info:
        inp_dict = data[out["node_id"]].get("inputs", {})
        val = inp_dict.get("value")
        if isinstance(val, list) and len(val) == 2 and isinstance(val[0], (str, int)):
            output_refs.append(resolve_link(val))
        elif out["node_id"] in {inp["node_id"] for inp in boundary_inputs_info}:
            output_refs.append(resolve_input_boundary_value(out["node_id"]))
        else:
            output_refs.append(val)

    return output_refs, graph
