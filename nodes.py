"""
Subworkflow Input and Subworkflow Output: transparent passthrough nodes with MatchType.
"""
from comfy_api.latest import io


class SubworkflowInput(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        tpl = io.MatchType.Template("T")
        return io.Schema(
            node_id="SWF_SubworkflowInput",
            display_name="Subworkflow Input",
            category="subworkflow",
            description=(
                "Marks an input boundary for a reusable workflow. "
                "The type is inferred from whatever connects to the output."
            ),
            inputs=[
                io.MatchType.Input("value", template=tpl, optional=True),
                io.String.Input("slot_name", default="input"),
            ],
            outputs=[
                io.MatchType.Output(template=tpl, display_name="value"),
            ],
        )

    @classmethod
    def execute(cls, value=None, slot_name="input"):
        return io.NodeOutput(value)


class SubworkflowOutput(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        tpl = io.MatchType.Template("T")
        return io.Schema(
            node_id="SWF_SubworkflowOutput",
            display_name="Subworkflow Output",
            category="subworkflow",
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
