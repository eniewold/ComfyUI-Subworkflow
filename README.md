# ComfyUI-Subworkflow

ComfyUI-Subworkflow adds reusable workflow boundaries to ComfyUI. It lets one workflow expose named inputs and outputs, then lets another workflow execute it through a single `Subworkflow` node.

## Custom Nodes

### Subworkflow

Loads a workflow from `ComfyUI/user/default/workflows` and expands it into the current prompt at execution time. The selected inner workflow determines the visible input and output slots on the node.

Inputs:
- `workflow`: workflow file to execute (the inner workflow).
- `at execution`: controls whether the inner workflow file is reloaded on every execution or a loaded workflow instance is kept.

Outputs are dynamic and are inferred from the inner workflow's `Subworkflow Output` nodes.

### Subworkflow Input

Marks an input boundary inside a reusable workflow. The `slot_name` widget controls the label shown on the outer `Subworkflow` node. The value type is inferred from the connected node.

When used directly in a normal workflow, `Subworkflow Input` must have its `value` input linked. It may be unlinked only when used as a boundary inside an inner workflow executed by `Subworkflow`.

### Subworkflow Output

Marks an output boundary inside a reusable workflow. The `slot_name` widget controls the label shown on the outer `Subworkflow` node. The output type is inferred from the connected value.

`Subworkflow Output` also behaves as a passthrough when other nodes inside the same inner workflow consume its output.

## Features

Create reusable workflow components with named inputs and outputs, then compose them from other workflows. Inner workflows can be loaded fresh for every execution or kept loaded between executions, which allows ComfyUI-style widget state changes such as randomize-after-processing to persist while reload is disabled. UI and API workflow formats are supported, including native ComfyUI subgraphs in UI-format workflows.

## Supported Shapes

ComfyUI workflow JSON appears in a few different shapes depending on how it was saved and which nodes are used. This extension currently supports:

- UI-format workflows with top-level `nodes` and `links` arrays.
- API-format workflows where each node is keyed by node id and has `class_type` and `inputs`.
- UI-format native ComfyUI subgraphs stored under `definitions.subgraphs`.
- UI node class names stored directly in `node.type`.
- UI node class names stored in `node.properties["Node name for S&R"]` when `node.type` contains a UUID.
- UI links in classic array form: `[id, source_node, source_slot, target_node, target_slot, type]`.
- UI links in object form with `id`, `origin_id`, `origin_slot`, `target_id`, and `target_slot`.
- UI `widgets_values` stored as ordered lists.
- UI `widgets_values` stored as dictionaries keyed by widget/input name.
- Widget-backed `COMBO`, `INT`, `FLOAT`, `STRING`, and `BOOLEAN` inputs, including legacy list-based combo definitions and control-after-generate companion widgets.
- Boundary nodes used as passthroughs when other nodes connect to `Subworkflow Input` or `Subworkflow Output` outputs.

`Subworkflow Input` and `Subworkflow Output` boundary names are read from their `slot_name` widget. For UI workflows this can come from either list-style or dictionary-style `widgets_values`; for API workflows it is read from the node's `inputs.slot_name`.

## Installation

Clone this repository into your ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/eniewold/ComfyUI-Subworkflow.git
```

Restart ComfyUI after installation or after Python changes. Browser-side updates may also require a hard refresh.

## Usage

1. Create an inner workflow and add one or more `Subworkflow Input` nodes where external values should enter.
2. Add one or more `Subworkflow Output` nodes where values should leave the inner workflow.
3. Set meaningful `slot_name` values on each input and output boundary.
4. Save the inner workflow under `ComfyUI/user/default/workflows`.
5. In another workflow, add a `Subworkflow` node and select the saved workflow file.
6. Connect the generated input and output slots.

Use `at execution` set to `reload` when the inner workflow file should be read fresh every run. Use `keep loaded` when the inner workflow should keep its in-memory state between runs.

## Use Cases

- Reuse a prompt, sampler, or decode chain across multiple workflows.
- Wrap model-specific pipelines behind a small set of named inputs and outputs.
- Build compact higher-level workflows from tested lower-level workflows.
- Keep experimental graph sections isolated while exposing only the inputs and outputs that matter.
- Share common workflow pieces without copying all nodes into every workflow.

## Notes

- The `Subworkflow` node sets the input and output parameters when loading the inner workflow. This load is executed when the outer workflow is loaded. When linked nodes do not match the expected input types provided by `Subworkflow Output` and `Subworkflow Input` from inner workflow, the links are severed silently. 
- The `Subworkflow Output` node will not pass through values to it's output when it's used as inner workflow. When the workflow is executed standalone, it will pass through values transparently as expected. 
- The `Subworkflow Input` will ignore any linked nodes to the input values when used as inner workflow. When the workflow is executed standalone, it will use the linked values transparently as expected.

## Known Issues

- [ ] The `Subworkflow` node progress can exceed 100%, sometimes reaching about 200%. Check with the upscale workflow example.
- [ ] When no node is attached to an output of `Subworkflow`, an error occurs; it could be treated as an optional output.
- [ ] Used paths with macro elements are not formatted currectly when used in inner workflow? (use Video Combine node with %date:yyyy-MM-dd%/WAN/Video)
- [ ] Green progress borders appear on more than one node when executing a inner workflow as part of a larger workflow. These borders should be limited to the currently executing node(s) outer workflow.
- [ ] The order if inputs/outputs on the `Subworkflow` node is undetermined (probably based on the order of nodes in the inner workflow JSON). Consider adding an option to control this order.

### Recently fixed
- [x] `Subworkflow Output` can be placed between two nodes and still behave as a passthrough.
- [x] `Subworkflow Input` transparency for nodes is handled for tested pass-through cases such as concatenate string.
- [x] Inner workflow nodes with randomize-after-processing preserve updated values when `at execution` is set to `keep loaded`.
- [x] `Subworkflow`, `Subworkflow Input`, and `Subworkflow Output` are all V3 nodes.
- [x] When linked nodes have a mismatch in expected input type and the value provided by Subworkflow Output, no error is given but passed to the next node. Implement type checking and error handling?

### Wish List
- [ ] For each Subworkflow Input node, add an input field in the Subworkflow node for directly setting its value. This also allows for linking of nodes with same type. Similar as subgraphs. 
