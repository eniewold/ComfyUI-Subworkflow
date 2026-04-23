"""
Subworkflow: loads an inner workflow (UI or API format), infers its I/O from
Subworkflow Input / Subworkflow Output nodes, and executes it as a subgraph expansion.
"""
import logging

from comfy_api.latest import io

from .workflow_utils import (
    list_workflow_files,
    load_workflow_file,
    load_workflow_url,
    build_expansion,
    apply_control_after_generate,
    MAX_SLOTS,
)

log = logging.getLogger("ComfyUI-Subworkflow")


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
            log.info("Subworkflow: waiting for dynamic input(s) %s", missing_inputs)
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
            log.info("Subworkflow: loading inner workflow %r (%s)", label, reason)
            cls._loaded_workflows[cache_key] = cls._load_source(**kwargs)
        else:
            log.info("Subworkflow: reusing cached inner workflow %r", label)
        return cls._loaded_workflows[cache_key]

    @classmethod
    def _execute_source(cls, reload_each_execution=True, **kwargs):
        label = cls._source_label(**kwargs)
        log.info(
            "Subworkflow: executing inner workflow %r (reload_each_execution=%s, dynamic_inputs=%s)",
            label,
            reload_each_execution,
            sorted(k for k in kwargs if k.startswith("swf_in_")),
        )
        data = cls._get_workflow_data(reload_each_execution, **kwargs)

        output_refs, graph = build_expansion(data, kwargs)
        if not reload_each_execution:
            apply_control_after_generate(data)

        while len(output_refs) < MAX_SLOTS:
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
                _reload_input(),
            ],
            outputs=_subworkflow_outputs(),
            enable_expand=True,
            accept_all_inputs=True,
        )

    @classmethod
    def _source_label(cls, url: str, **kwargs) -> str:
        return url

    @classmethod
    def _source_cache_key(cls, url: str, **kwargs) -> str:
        return f"url:{url.strip()}"

    @classmethod
    def _load_source(cls, url: str, **kwargs) -> dict:
        if not url:
            raise ValueError("No workflow URL specified.")
        return load_workflow_url(url.strip())

    @classmethod
    def execute(cls, url: str, reload_each_execution=True, **kwargs):
        return cls._execute_source(
            url=url,
            reload_each_execution=reload_each_execution,
            **kwargs,
        )
