"""
Subworkflow: loads an inner workflow (UI or API format), infers its I/O from
Subworkflow Input / Subworkflow Output nodes, and executes it as a subgraph expansion.
"""
import logging

from comfy_api.latest import io

from .workflow_utils import (
    list_workflow_files,
    load_workflow,
    build_expansion,
    apply_control_after_generate,
    MAX_SLOTS,
)

log = logging.getLogger("ComfyUI-Subworkflow")


class Subworkflow(io.ComfyNode):
    """
    Selects a saved API-format workflow, exposes its Subworkflow Input nodes as
    inputs and its Subworkflow Output nodes as outputs, then executes the inner
    workflow as a transparent subgraph when the outer workflow runs.
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="SWF_Subworkflow",
            display_name="Subworkflow",
            category="subworkflow",
            description=(
                "Executes a selected workflow as an expandable subworkflow, "
                "using Subworkflow Input and Subworkflow Output boundary nodes."
            ),
            inputs=[
                io.Combo.Input("workflow", options=list_workflow_files()),
                io.Boolean.Input(
                    "reload_each_execution",
                    display_name="at execution",
                    default=True,
                    label_on="reload",
                    label_off="keep loaded",
                ),
            ],
            outputs=[
                io.AnyType.Output(id=f"out_{i}", display_name=f"out_{i}")
                for i in range(MAX_SLOTS)
            ],
            enable_expand=True,
            accept_all_inputs=True,
        )

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
    def fingerprint_inputs(cls, workflow: str, reload_each_execution=True, **kwargs):
        # The inner workflow can change between runs by file reload or by cached
        # control-after-generate mutations, even when outer inputs are unchanged.
        return float("NaN")

    _loaded_workflows: dict[str, dict] = {}

    @classmethod
    def _get_workflow_data(cls, workflow: str, reload_each_execution: bool) -> dict:
        if reload_each_execution or workflow not in cls._loaded_workflows:
            reason = "reload_each_execution enabled" if reload_each_execution else "cache miss"
            log.info("Subworkflow: loading inner workflow %r (%s)", workflow, reason)
            cls._loaded_workflows[workflow] = load_workflow(workflow)
        else:
            log.info("Subworkflow: reusing cached inner workflow %r", workflow)
        return cls._loaded_workflows[workflow]

    @classmethod
    def execute(cls, workflow: str, reload_each_execution=True, **kwargs):
        if not workflow:
            raise ValueError("No workflow selected. Choose a workflow file from the dropdown.")
        log.info(
            "Subworkflow: executing inner workflow %r (reload_each_execution=%s, dynamic_inputs=%s)",
            workflow,
            reload_each_execution,
            sorted(k for k in kwargs if k.startswith("swf_in_")),
        )
        try:
            data = cls._get_workflow_data(workflow, reload_each_execution)
        except FileNotFoundError:
            raise ValueError(f"Workflow file not found: {workflow!r}")

        output_refs, graph = build_expansion(data, kwargs)
        if not reload_each_execution:
            apply_control_after_generate(data)

        while len(output_refs) < MAX_SLOTS:
            output_refs.append(None)

        return io.NodeOutput(*output_refs, expand=graph.finalize())
