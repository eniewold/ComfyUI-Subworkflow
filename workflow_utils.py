"""
Utilities for loading and processing ComfyUI workflows.
Supports both UI format (saved normally via Ctrl+S) and API format.
"""
import json
import logging
import os
import random
import re
from comfy_execution.graph_utils import GraphBuilder

log = logging.getLogger("ComfyUI-Subworkflow")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

SWF_SUBWORKFLOW_INPUT = "SWF_SubworkflowInput"
SWF_SUBWORKFLOW_OUTPUT = "SWF_SubworkflowOutput"
MAX_SLOTS = 8
PLACEHOLDER = "[select workflow]"


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
    return [PLACEHOLDER] + sorted(files)


def load_workflow(filename: str) -> dict:
    path = os.path.join(_workflows_dir(), filename)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
    Return (inputs, outputs) sorted by node id.
    Each entry: {"node_id": str, "slot_name": str}
    """
    if is_ui_format(data):
        return _get_workflow_io_ui(data)
    return _get_workflow_io_api(data)


def _get_workflow_io_ui(data: dict) -> tuple[list[dict], list[dict]]:
    inputs, outputs = [], []
    for node in data.get("nodes", []):
        ntype = _node_class_type(node)
        nid = str(node.get("id"))
        widgets = node.get("widgets_values") or []
        slot_name = widgets[0] if widgets else nid
        if ntype == SWF_SUBWORKFLOW_INPUT:
            inputs.append({"node_id": nid, "slot_name": slot_name})
        elif ntype == SWF_SUBWORKFLOW_OUTPUT:
            outputs.append({"node_id": nid, "slot_name": slot_name})
    inputs.sort(key=lambda x: _sort_key(x["node_id"]))
    outputs.sort(key=lambda x: _sort_key(x["node_id"]))
    return inputs, outputs


def _get_workflow_io_api(data: dict) -> tuple[list[dict], list[dict]]:
    inputs, outputs = [], []
    for nid, node in data.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        slot = node.get("inputs", {}).get("slot_name", nid)
        if ct == SWF_SUBWORKFLOW_INPUT:
            inputs.append({"node_id": nid, "slot_name": slot})
        elif ct == SWF_SUBWORKFLOW_OUTPUT:
            outputs.append({"node_id": nid, "slot_name": slot})
    inputs.sort(key=lambda x: _sort_key(x["node_id"]))
    outputs.sort(key=lambda x: _sort_key(x["node_id"]))
    return inputs, outputs


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
            if not (isinstance(input_type, list) or input_type in ("INT", "FLOAT", "STRING", "BOOLEAN")):
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


def _get_widget_values(class_type: str, linked_names: set, widgets_values: list) -> dict:
    """
    Return {widget_name: value} by aligning widgets_values with the full ordered
    widget list for the node class, including hidden control-after-generate
    widgets that ComfyUI stores next to controlled numeric widgets.
    """
    result = {}
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
                    "Subworkflow: control-after-generate skipped %s node %s %s value=%r mode=%r: %s",
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
            log.info(
                "Subworkflow: control-after-generate updated %s node %s %s from %r to %r (%s)",
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
        log.info("Subworkflow: updated %d cached control-after-generate widget(s)", changed)
    return changed


# ---------------------------------------------------------------------------
# Subgraph expansion
# ---------------------------------------------------------------------------

def build_expansion(data: dict, outer_inputs: dict):
    """
    Build a GraphBuilder subgraph from an inner workflow.
    Accepts both UI format and API format.

    outer_inputs: {"swf_in_0": value, "swf_in_1": value, ...}
    Returns (output_refs, graph).
    """
    if is_ui_format(data):
        return _build_expansion_ui(data, outer_inputs)
    return _build_expansion_api(data, outer_inputs)


def _build_subgraph_defs(data: dict) -> dict:
    """Extract subgraph (group node) definitions from workflow data, keyed by UUID."""
    result = {}
    for sg in ((data.get("definitions") or {}).get("subgraphs") or []):
        if isinstance(sg, dict) and sg.get("id"):
            result[sg["id"]] = sg
    return result


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
        ct  = _node_class_type(node)
        if not ct:
            log.warning("SWF sg: node id=%s has no class_type, skipping", nid)
            continue
        if ct not in _comfy_nodes.NODE_CLASS_MAPPINGS:
            log.warning("SWF sg: node id=%s type=%r not in NODE_CLASS_MAPPINGS, skipping", nid, ct)
            continue
        sg_refs[nid] = graph.node(ct, id=f"{id_prefix}_{nid}")

    def resolve_sg_link(link_id: str):
        src = sg_link_map.get(str(link_id))
        if src is None:
            return None
        src_id, src_slot = str(src[0]), int(src[1])
        if src_id == input_node_id:
            return outer_values_by_slot.get(src_slot)
        ref = sg_refs.get(src_id)
        if ref is None:
            log.warning("SWF sg: link %s src node %s not in sg_refs", link_id, src_id)
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
                        log.warning("SWF sg: node %s (%s) input %r UNRESOLVED", nid, ct, name)

        for wname, val in _get_widget_values(ct, linked_names, widgets_values).items():
            gb_node.set_input(wname, val)

    # Collect output refs from the subgraph's virtual outputNode.
    output_refs = []
    for out_def in sg_outputs_def:
        link_ids = out_def.get("linkIds") or []
        if not link_ids:
            log.warning("SWF sg: output %r has no linkIds", out_def.get("name"))
            output_refs.append(None)
            continue
        src = sg_link_map.get(str(link_ids[0]))
        if src is None:
            log.warning("SWF sg: output link %s not in sg_link_map", link_ids[0])
            output_refs.append(None)
            continue
        src_id, src_slot = str(src[0]), int(src[1])
        ref = sg_refs.get(src_id)
        if ref is None:
            log.warning("SWF sg: output src node %s not in sg_refs", src_id)
            output_refs.append(None)
            continue
        output_refs.append(ref.out(src_slot))

    return output_refs


def _build_expansion_ui(data: dict, outer_inputs: dict):
    nodes_list = data.get("nodes", [])
    links_list = data.get("links", [])

    subgraph_defs = _build_subgraph_defs(data)

    parsed_links = [_parse_link(lnk) for lnk in links_list]
    link_map = {lid: (src, ss) for lid, src, ss, _, _ in parsed_links}
    dst_to_src: dict[str, tuple[str, int]] = {}
    for _, src, ss, dst, _ in parsed_links:
        dst_to_src.setdefault(dst, (src, ss))

    inputs_info, outputs_info = _get_workflow_io_ui(data)

    fi_node_ids  = {inp["node_id"] for inp in inputs_info}
    fo_node_ids  = {out["node_id"] for out in outputs_info}
    func_node_ids = fi_node_ids | fo_node_ids
    fo_src = {out["node_id"]: dst_to_src.get(out["node_id"]) for out in outputs_info}

    fi_value = {inp["node_id"]: outer_inputs.get(f"swf_in_{i}") for i, inp in enumerate(inputs_info)}
    missing = [
        f"swf_in_{i}:{inp['slot_name']}({inp['node_id']})"
        for i, inp in enumerate(inputs_info)
        if outer_inputs.get(f"swf_in_{i}") is None
    ]
    if missing:
        log.warning("Subworkflow: missing UI inner input value(s): %s", missing)
    log.info(
        "Subworkflow: building UI expansion with %d input(s), %d output(s), %d inner node(s), outer_input_keys=%s",
        len(inputs_info),
        len(outputs_info),
        len(nodes_list),
        sorted(k for k in outer_inputs if k.startswith("swf_in_")),
    )

    graph = GraphBuilder()
    node_refs: dict = {}
    subgraph_outputs: dict = {}  # nid → [output_ref, ...]

    def resolve_link(src_node_id: str, src_slot: int):
        if src_node_id in fi_value:
            return fi_value[src_node_id]
        if src_node_id in fo_src:
            src = fo_src[src_node_id]
            return resolve_link(src[0], src[1]) if src else None
        if src_node_id in subgraph_outputs:
            refs = subgraph_outputs[src_node_id]
            return refs[src_slot] if src_slot < len(refs) else None
        ref = node_refs.get(src_node_id)
        if ref is None:
            log.warning("SWF: node %s slot %d unresolvable", src_node_id, src_slot)
        return ref.out(src_slot) if ref is not None else None

    import nodes as _comfy_nodes

    # Pass 1: register regular inner nodes (skip SWF boundary and subgraph nodes).
    for node in nodes_list:
        nid = str(node["id"])
        if nid in func_node_ids:
            continue
        ct = _node_class_type(node)
        if not ct:
            log.warning("SWF: node id=%s has no resolvable class_type, skipping", nid)
            continue
        if ct in subgraph_defs:
            continue  # expanded separately below
        if ct not in _comfy_nodes.NODE_CLASS_MAPPINGS:
            log.warning("SWF: node id=%s type=%r not in NODE_CLASS_MAPPINGS, skipping", nid, ct)
            continue
        node_refs[nid] = graph.node(ct, id=nid)

    # Subgraph expansion pass (runs after pass 1 so node_refs is populated).
    for node in nodes_list:
        nid = str(node["id"])
        if nid in func_node_ids:
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
                        log.warning("SWF: node %s (%s) input %r unresolved", nid, ct, name)
                else:
                    log.warning("SWF: node %s (%s) input %r: link %s not in link_map",
                                nid, ct, name, link_id)

        for wname, val in _get_widget_values(ct, linked_names, widgets_values).items():
            gb_node.set_input(wname, val)

    # Collect output refs from Subworkflow Output nodes.
    output_refs = []
    for out in outputs_info:
        src = dst_to_src.get(out["node_id"])
        if src is None:
            log.warning("SWF: Subworkflow Output node=%s has no incoming link", out["node_id"])
        ref = resolve_link(src[0], src[1]) if src else None
        output_refs.append(ref)

    return output_refs, graph


def _build_expansion_api(data: dict, outer_inputs: dict):
    inputs_info, outputs_info = _get_workflow_io_api(data)

    fi_value = {inp["node_id"]: outer_inputs.get(f"swf_in_{i}") for i, inp in enumerate(inputs_info)}
    missing = [
        f"swf_in_{i}:{inp['slot_name']}({inp['node_id']})"
        for i, inp in enumerate(inputs_info)
        if outer_inputs.get(f"swf_in_{i}") is None
    ]
    if missing:
        log.warning("Subworkflow: missing API inner input value(s): %s", missing)
    log.info(
        "Subworkflow: building API expansion with %d input(s), %d output(s), %d inner node(s), outer_input_keys=%s",
        len(inputs_info),
        len(outputs_info),
        len([nid for nid in data if not str(nid).startswith("_")]),
        sorted(k for k in outer_inputs if k.startswith("swf_in_")),
    )
    func_node_ids = {inp["node_id"] for inp in inputs_info} | {out["node_id"] for out in outputs_info}
    fo_src = {
        out["node_id"]: data[out["node_id"]].get("inputs", {}).get("value")
        for out in outputs_info
    }

    graph = GraphBuilder()
    node_refs: dict = {}

    def resolve_link(link_val):
        src_id   = str(link_val[0])
        src_slot = int(link_val[1])
        if src_id in fi_value:
            return fi_value[src_id]
        if src_id in fo_src:
            src = fo_src[src_id]
            return resolve_link(src) if isinstance(src, list) and len(src) == 2 else src
        ref = node_refs.get(src_id)
        if ref is None:
            log.warning("SWF api: node %s slot %d unresolvable", src_id, src_slot)
        return ref.out(src_slot) if ref is not None else None

    for nid, node in data.items():
        if nid.startswith("_") or nid in func_node_ids:
            continue
        ct = node.get("class_type")
        if ct is None:
            continue
        node_refs[nid] = graph.node(ct, id=nid)

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
                    log.warning("SWF api: node %s input %r unresolved link %s", nid, inp_name, inp_val)
            else:
                gb_node.set_input(inp_name, inp_val)

    output_refs = []
    for out in outputs_info:
        inp_dict = data[out["node_id"]].get("inputs", {})
        val = inp_dict.get("value")
        if isinstance(val, list) and len(val) == 2 and isinstance(val[0], (str, int)):
            output_refs.append(resolve_link(val))
        else:
            output_refs.append(val)

    return output_refs, graph
