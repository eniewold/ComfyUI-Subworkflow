"""
Subworkflow: loads an inner workflow (UI or API format), infers its I/O from
Subworkflow Input / Subworkflow Output nodes, and executes it as a subgraph expansion.
"""
import logging

from comfy_api.latest import io
from .debug_utils import configure_logger

from .workflow_utils import (
    list_workflow_files,
    load_workflow_file,
    load_workflow_url,
    build_expansion,
    build_modifier_source_expansion,
    apply_control_after_generate,
    validate_workflow_nodes_installed,
    get_workflow_interface,
    MAX_SLOTS,
)

log = configure_logger("ComfyUI-Subworkflow")


def _apply_primitive_overrides(data: dict, kwargs: dict) -> dict:
    """
    For INT/FLOAT inputs where the outer slot is not connected and the override
    widget has its switch enabled, substitute the widget value so build_expansion
    uses it instead of the inner fallback node.

    The frontend sends a single widget named swf_override_i whose value is a dict
    {"use": bool, "val": number}.
    """
    info = get_workflow_interface(data)
    effective = dict(kwargs)
    for i, inp_info in enumerate(info["inputs"]):
        if inp_info.get("type") not in ("INT", "FLOAT"):
            continue
        key = f"swf_in_{i}"
        if effective.get(key) is not None:
            continue  # connected node takes priority
        override = effective.get(f"swf_override_{i}")
        if isinstance(override, dict) and override.get("use"):
            effective[key] = override.get("val")
    return effective


class BaseSubworkflow(io.ComfyNode):
    """
    Shared execution behavior for subworkflow nodes that load workflow JSON from
    different sources.
    """

    @classmethod
    def validate_inputs(cls, **kwargs):
        # Accept any incoming types for dynamic swf_in_* inputs.
        return True

    @classmethod
    def check_lazy_status(cls, **kwargs):
        missing_inputs = [
            name for name, value in kwargs.items()
            if name.startswith("swf_in_") and value is None
        ]
        if missing_inputs:
            log.debug("[Subworkflow] waiting for dynamic input(s) %s", missing_inputs)
        return missing_inputs

    @classmethod
    def fingerprint_inputs(cls, *args, **kwargs):
        # The inner workflow can change between runs by file reload or by cached
        # control-after-generate mutations, even when outer inputs are unchanged.
        return float("NaN")

    _loaded_workflows: dict[str, dict] = {}

    @classmethod
    def _source_label(cls, **kwargs) -> str:
        raise NotImplementedError

    @classmethod
    def _source_cache_key(cls, **kwargs) -> str:
        raise NotImplementedError

    @classmethod
    def _load_source(cls, **kwargs) -> dict:
        raise NotImplementedError

    @classmethod
    def _get_workflow_data(cls, reload_each_execution: bool, **kwargs) -> dict:
        cache_key = cls._source_cache_key(**kwargs)
        label = cls._source_label(**kwargs)
        if reload_each_execution or cache_key not in cls._loaded_workflows:
            reason = "reload_each_execution enabled" if reload_each_execution else "cache miss"
            log.info("[Subworkflow] loading inner workflow %r (%s)", label, reason)
            cls._loaded_workflows[cache_key] = cls._load_source(**kwargs)
        else:
            log.debug("[Subworkflow] reusing cached inner workflow %r", label)
        return cls._loaded_workflows[cache_key]

    @classmethod
    def _execute_source(cls, reload_each_execution=True, **kwargs):
        label = cls._source_label(**kwargs)
        log.debug(
            "[Subworkflow] executing inner workflow %r (reload_each_execution=%s, dynamic_inputs=%s)",
            label,
            reload_each_execution,
            sorted(k for k in kwargs if k.startswith("swf_in_")),
        )
        data = cls._get_workflow_data(reload_each_execution, **kwargs)
        validate_workflow_nodes_installed(data)

        effective_inputs = _apply_primitive_overrides(data, kwargs)
        output_refs, graph = build_expansion(data, effective_inputs)
        return cls._finalize_execution(output_refs, graph, data, reload_each_execution, pad_outputs=MAX_SLOTS)

    @classmethod
    def _finalize_execution(
        cls,
        output_refs,
        graph,
        data: dict,
        reload_each_execution: bool,
        pad_outputs: int | None = None,
    ):
        if not reload_each_execution:
            apply_control_after_generate(data)

        if pad_outputs is not None:
            while len(output_refs) < pad_outputs:
                output_refs.append(None)

        return io.NodeOutput(*output_refs, expand=graph.finalize())


def _subworkflow_outputs():
    return [
        io.AnyType.Output(id=f"out_{i}", display_name=f"out_{i}")
        for i in range(MAX_SLOTS)
    ]


def _reload_input():
    return io.Boolean.Input(
        "reload_each_execution",
        display_name="at execution",
        default=True,
        label_on="reload",
        label_off="keep loaded",
    )


class Subworkflow(BaseSubworkflow):
    """
    Selects a saved workflow, exposes its Subworkflow Input nodes as inputs and
    its Subworkflow Output nodes as outputs, then executes the inner workflow as
    a transparent subgraph when the outer workflow runs.
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SWF_Subworkflow",
            display_name="Subworkflow",
            category="Subworkflow",
            description=(
                "Executes a selected workflow as an expandable subworkflow, "
                "using Subworkflow Input and Subworkflow Output boundary nodes."
            ),
            inputs=[
                io.Combo.Input("workflow", options=list_workflow_files()),
                _reload_input(),
            ],
            outputs=_subworkflow_outputs(),
            enable_expand=True,
            accept_all_inputs=True,
        )

    @classmethod
    def _source_label(cls, workflow: str, **kwargs) -> str:
        return workflow

    @classmethod
    def _source_cache_key(cls, workflow: str, **kwargs) -> str:
        return f"file:{workflow}"

    @classmethod
    def _load_source(cls, workflow: str, **kwargs) -> dict:
        if not workflow:
            raise ValueError("No workflow selected. Choose a workflow file from the dropdown.")
        try:
            return load_workflow_file(workflow)
        except FileNotFoundError:
            raise ValueError(f"Workflow file not found: {workflow!r}") from None

    @classmethod
    def execute(cls, workflow: str, reload_each_execution=True, **kwargs):
        return cls._execute_source(
            workflow=workflow,
            reload_each_execution=reload_each_execution,
            **kwargs,
        )


class SubworkflowFromURL(BaseSubworkflow):
    """
    Loads a workflow JSON document from an HTTP(S) URL and executes it as a
    transparent subgraph.
    """

    @classmethod
    def define_schema(cls):
        log.debug("[Subworkflow] SubworkflowFromURL define_schema called")
        return io.Schema(
            node_id="SWF_SubworkflowFromURL",
            display_name="Subworkflow (from URL)",
            category="Subworkflow",
            description=(
                "Executes a workflow loaded from an HTTP(S) URL as an expandable "
                "subworkflow, using Subworkflow Input and Subworkflow Output "
                "boundary nodes."
            ),
            inputs=[
                io.String.Input("url", multiline=False, default=""),
                io.Boolean.Input(
                    "verify_ssl",
                    display_name="verify SSL",
                    default=True,
                    label_on="verify",
                    label_off="skip",
                ),
                _reload_input(),
            ],
            outputs=_subworkflow_outputs(),
            enable_expand=True,
            accept_all_inputs=True,
        )

    @classmethod
    def _source_label(cls, url: str, **kwargs) -> str:
        log.debug("[Subworkflow] SubworkflowFromURL _source_label url=%r", url)
        return url

    @classmethod
    def _source_cache_key(cls, url: str, verify_ssl: bool = True, **kwargs) -> str:
        log.debug(
            "[Subworkflow] SubworkflowFromURL _source_cache_key url=%r stripped=%r verify_ssl=%s",
            url,
            url.strip(),
            verify_ssl,
        )
        return f"url:{url.strip()}:verify_ssl:{bool(verify_ssl)}"

    @classmethod
    def _load_source(cls, url: str, verify_ssl: bool = True, **kwargs) -> dict:
        log.debug(
            "[Subworkflow] SubworkflowFromURL _load_source url=%r verify_ssl=%s kwargs_keys=%s",
            url,
            verify_ssl,
            sorted(kwargs.keys()),
        )
        if not url:
            log.warning("[Subworkflow] SubworkflowFromURL _load_source missing URL")
            raise ValueError("No workflow URL specified.")
        return load_workflow_url(url.strip(), verify_ssl=bool(verify_ssl))

    @classmethod
    def execute(cls, url: str, verify_ssl=True, reload_each_execution=True, **kwargs):
        log.debug(
            "[Subworkflow] SubworkflowFromURL execute called url=%r verify_ssl=%s reload_each_execution=%s dynamic_inputs=%s",
            url,
            verify_ssl,
            reload_each_execution,
            sorted(k for k in kwargs if k.startswith("swf_in_")),
        )
        return cls._execute_source(
            url=url,
            verify_ssl=verify_ssl,
            reload_each_execution=reload_each_execution,
            **kwargs,
        )


class SubworkflowModifierSource(BaseSubworkflow):
    """
    Exposes a modifier-source slot from an inner workflow as a separate outer node.
    This breaks the outer dependency cycle by moving the pre-modifier value onto
    its own node, while the main Subworkflow keeps only the modifier input.
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SWF_SubworkflowModifierSource",
            display_name="Subworkflow Modifier Source",
            category="Subworkflow",
            description=(
                "Exposes all modifier source slots from a selected inner workflow. "
                "Use this together with the main Subworkflow node to break outer "
                "modifier dependency loops."
            ),
            inputs=[
                io.Combo.Input("workflow", options=list_workflow_files()),
            ],
            outputs=_subworkflow_outputs(),
            enable_expand=True,
            accept_all_inputs=True,
        )

    @classmethod
    def _source_label(cls, workflow: str, **kwargs) -> str:
        return workflow

    @classmethod
    def _source_cache_key(cls, workflow: str, **kwargs) -> str:
        return f"file:{workflow}"

    @classmethod
    def _load_source(cls, workflow: str, **kwargs) -> dict:
        if not workflow:
            raise ValueError("No workflow selected. Choose a workflow file from the dropdown.")
        try:
            return load_workflow_file(workflow)
        except FileNotFoundError:
            raise ValueError(f"Workflow file not found: {workflow!r}") from None

    @classmethod
    def execute(cls, workflow: str, **kwargs):
        reload_each_execution = True
        data = cls._get_workflow_data(reload_each_execution, workflow=workflow, **kwargs)
        validate_workflow_nodes_installed(data)
        output_refs, graph = build_modifier_source_expansion(data, kwargs)
        return cls._finalize_execution(output_refs, graph, data, reload_each_execution, pad_outputs=MAX_SLOTS)


class SubworkflowModifierSourceFromURL(BaseSubworkflow):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SWF_SubworkflowModifierSourceFromURL",
            display_name="Subworkflow Modifier Source (from URL)",
            category="Subworkflow",
            description=(
                "Exposes all modifier source slots from a workflow loaded from an "
                "HTTP(S) URL."
            ),
            inputs=[
                io.String.Input("url", multiline=False, default=""),
                io.Boolean.Input(
                    "verify_ssl",
                    display_name="verify SSL",
                    default=True,
                    label_on="verify",
                    label_off="skip",
                ),
            ],
            outputs=_subworkflow_outputs(),
            enable_expand=True,
            accept_all_inputs=True,
        )

    @classmethod
    def _source_label(cls, url: str, **kwargs) -> str:
        return url

    @classmethod
    def _source_cache_key(cls, url: str, verify_ssl: bool = True, **kwargs) -> str:
        return f"url:{url.strip()}:verify_ssl:{bool(verify_ssl)}"

    @classmethod
    def _load_source(cls, url: str, verify_ssl: bool = True, **kwargs) -> dict:
        if not url:
            raise ValueError("No workflow URL specified.")
        return load_workflow_url(url.strip(), verify_ssl=bool(verify_ssl))

    @classmethod
    def execute(cls, url: str, verify_ssl: bool, **kwargs):
        reload_each_execution = True
        data = cls._get_workflow_data(
            reload_each_execution,
            url=url,
            verify_ssl=verify_ssl,
            **kwargs,
        )
        validate_workflow_nodes_installed(data)
        output_refs, graph = build_modifier_source_expansion(data, kwargs)
        return cls._finalize_execution(output_refs, graph, data, reload_each_execution, pad_outputs=MAX_SLOTS)
