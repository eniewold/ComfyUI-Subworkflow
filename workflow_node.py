"""
Subworkflow: loads an inner workflow (UI or API format), infers its I/O from
Subworkflow Input / Subworkflow Output nodes, and executes it as a subgraph expansion.
"""
from .workflow_utils import (
    list_workflow_files,
    load_workflow,
    get_workflow_io,
    build_expansion,
    MAX_SLOTS,
    PLACEHOLDER,
)

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
    def execute(cls, workflow: str, **kwargs):
        if not workflow or workflow.startswith("["):
            raise ValueError("No workflow selected. Choose a workflow file from the dropdown.")
        try:
            data = load_workflow(workflow)
        except FileNotFoundError:
            raise ValueError(f"Workflow file not found: {workflow!r}")

        output_refs, graph = build_expansion(data, kwargs)

        while len(output_refs) < MAX_SLOTS:
            output_refs.append(None)

        return {"result": tuple(output_refs), "expand": graph.finalize()}
