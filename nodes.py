"""
Subworkflow Input and Subworkflow Output: transparent passthrough nodes with MatchType.
"""
from comfy_api.latest import io


def _is_link(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], (int, float))
    )


def _has_linked_value_input(prompt, unique_id):
    if prompt is None or unique_id is None:
        return False

    node = prompt.get(str(unique_id)) or prompt.get(unique_id)
    if not isinstance(node, dict):
        return False

    inputs = node.get("inputs") or {}
    return _is_link(inputs.get("value"))


class SubworkflowInput(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        tpl = io.MatchType.Template("T")
        return io.Schema(
            node_id="SWF_SubworkflowInput",
            display_name="Subworkflow Input",
            category="Subworkflow",
            description=(
                "Marks an input boundary for a reusable workflow. "
                "The type is inferred from whatever connects to the output."
            ),
            inputs=[
                io.MatchType.Input("value", template=tpl, optional=True),
                io.String.Input("slot_name", default="input"),
            ],
            hidden=[
                io.Hidden.prompt,
                io.Hidden.unique_id,
            ],
            outputs=[
                io.MatchType.Output(template=tpl, display_name="value"),
            ],
        )

    @classmethod
    def execute(cls, value=None, slot_name="input"):
        if not _has_linked_value_input(cls.hidden.prompt, cls.hidden.unique_id):
            raise ValueError(
                "Subworkflow Input must have its value input linked when executed directly. "
                "It is only allowed to be unlinked when used inside a Subworkflow node."
            )
        return io.NodeOutput(value)


class SubworkflowOutput(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        tpl = io.MatchType.Template("T")
        return io.Schema(
            node_id="SWF_SubworkflowOutput",
            display_name="Subworkflow Output",
            category="Subworkflow",
            description=(
                "Marks an output boundary for a reusable workflow. "
                "The type is inferred from whatever connects to the input."
            ),
            inputs=[
                io.MatchType.Input("value", template=tpl),
                io.String.Input("slot_name", default="output"),
            ],
            outputs=[
                io.MatchType.Output(template=tpl, display_name="value"),
            ],
        )

    @classmethod
    def execute(cls, value, slot_name="output"):
        return io.NodeOutput(value)
