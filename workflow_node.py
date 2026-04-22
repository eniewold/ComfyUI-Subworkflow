"""
Subworkflow: loads an inner workflow (UI or API format), infers its I/O from
Subworkflow Input / Subworkflow Output nodes, and executes it as a subgraph expansion.
"""
import logging

from .workflow_utils import (
    list_workflow_files,
    load_workflow,
    get_workflow_io,
    build_expansion,
    apply_control_after_generate,
    MAX_SLOTS,
    PLACEHOLDER,
)

log = logging.getLogger("ComfyUI-Subworkflow")

# A string subclass whose __ne__ always returns False so that ComfyUI's
# type-matching considers it equal to any other type string.
class _AnyType(str):
    def __eq__(self, _):
        return True
    def __ne__(self, _):
        return False

_ANY = _AnyType("*")


class Subworkflow:
    """
    Selects a saved API-format workflow, exposes its Subworkflow Input nodes as
    inputs and its Subworkflow Output nodes as outputs, then executes the inner
    workflow as a transparent subgraph when the outer workflow runs.
    """

    @classmethod
    def INPUT_TYPES(cls):
        workflows = list_workflow_files()
        return {
            "required": {
                "workflow": (workflows, {}),
                "reload_each_execution": (
                    "BOOLEAN",
                    {"default": True, "label_on": "reload", "label_off": "keep loaded"},
                ),
            },
        }

    # Fixed upper bound; the JS extension hides the unused tail slots.
    RETURN_TYPES = (_ANY,) * MAX_SLOTS
    RETURN_NAMES = tuple(f"out_{i}" for i in range(MAX_SLOTS))
    FUNCTION = "execute"
    CATEGORY = "subworkflow"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None, **kwargs):
        # Accept any incoming types for dynamic swf_in_* inputs.
        return True

    @classmethod
    def IS_CHANGED(cls, workflow: str, reload_each_execution=True, **kwargs):
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
        if not workflow or workflow.startswith("["):
            raise ValueError("No workflow selected. Choose a workflow file from the dropdown.")
        log.info(
            "Subworkflow: executing inner workflow %r (reload_each_execution=%s)",
            workflow,
            reload_each_execution,
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

        return {"result": tuple(output_refs), "expand": graph.finalize()}
