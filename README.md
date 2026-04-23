# ComfyUI-Subworkflow ![Important](https://img.shields.io/badge/BETA-yellow)

ComfyUI-Subworkflow adds reusable workflow boundaries to ComfyUI. It lets one workflow expose named inputs and outputs, then lets another workflow execute it through a single `Subworkflow` node.

![Example workflow used as inner workflow in Subworkflow node](./assets/readme_usage.png)

## Subworkflow vs Subgraph

**Note:** *Subworkflows are fundametally different from subgraphs. Subworkflow offers a way to reuse entire workflows as nodes in other workflows, while subgraphs are a way to reuse a group of nodes within the same workflow.*

In the example below you can see several workflows are used, and the image to video workflow is used several times:

![Example workflow with several Subworkflow nodes with loaded inner workflows](./assets/readme_wf1.png)
*Example workflow with several Subworkflow nodes with loaded inner workflows*

## Subworkflow custom nodes

To control the workflow boundaries, this extension adds several custom nodes: `Subworkflow`, `Subworkflow Input`, and `Subworkflow Output`. These nodes work together to load and execute inner workflows while exposing their inputs and outputs on the outer workflow.

### Subworkflow

Loads a workflow from `ComfyUI/user/default/workflows` and expands it into the current prompt at execution time. The selected inner workflow determines the visible input and output slots on the node.

Inputs:
- `workflow`: workflow file to execute (the inner workflow).
- `at execution`: controls whether the inner workflow file is reloaded on every execution or a loaded workflow instance is kept.

Outputs are dynamic and are inferred from the inner workflow's `Subworkflow Output` nodes.

### Subworkflow (from URL)

Loads a workflow from a URL and expands it into the current prompt at execution time. The selected inner workflow determines the visible input and output slots on the node.

Inputs:
- `url`: absolute `http://` or `https://` URL that returns a workflow JSON file.
- `at execution`: controls whether the inner workflow URL is reloaded on every execution or a loaded workflow instance is kept.
- `verify ssl`: controls whether HTTPS certificate validation is enforced while loading from URL.

Outputs are dynamic and are inferred from the inner workflow's `Subworkflow Output` nodes.

### Subworkflow Input

Marks an input boundary inside a reusable workflow. The `slot_name` widget controls the label shown on the outer `Subworkflow` node. The value type is inferred from the connected node.

When used directly in a normal workflow, `Subworkflow Input` must have its `value` input linked for correct execution.
That linked node is ignored when used as inner workflow inside `Subworkflow`, and the value is instead provided by the outer `Subworkflow` node input. 
If no linked node is attached to the `Subworkflow` input, the linked node of the `Subworkflow Input` is used as fallback. This allows for optional inputs on the inner workflow.
This structure allows for default values to be set on the input, and to use the same workflow as standalone or as inner workflow without changes.

### Subworkflow Output

Marks an output boundary inside a reusable workflow. The `slot_name` widget controls the label shown on the outer `Subworkflow` node. The output type is inferred from the connected value.

`Subworkflow Output` also behaves as a passthrough when other nodes inside the same inner workflow consume its output.

![Example workflow with input and output nodes](./assets/readme_upscale.png)
*Example workflow setup with (green) input and output nodes for usage as inner workflow.*

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

Restart ComfyUI after installation or after Python changes. Browser-side updates also require a hard refresh. 
Note that there are no library dependencies outside of the standard Python environment bundled with ComfyUI.

**FEEDBACK WELCOME**: This is an initial release and work in progress. Expect bugs and breaking changes as I continue development. Please report any issues you encounter, especially those related to the known issues below, and share your use cases and feedback. Check below on how to get debug messages in the log files. 

## Step-by-Step Usage

1. Adjust an (inner) workflow and add one or more `Subworkflow Input` nodes where external values should enter.
2. Add one or more `Subworkflow Output` nodes where values should leave the inner workflow.
3. Set meaningful `slot_name` values on each input and output boundary.
4. Save the inner workflow (to default folder `ComfyUI/user/default/workflows`).
5. In another workflow, add a `Subworkflow` node and select the saved workflow file.
6. Connect the generated input and output slots.

Use `at execution` set to `reload` when the inner workflow file should be read fresh every run. Use `keep loaded` when the inner workflow should keep its in-memory state between runs.

## Load from URL 

Use the `Subworkflow (from URL)` node to load an inner workflow from a URL instead of a local file. The URL must point to a raw JSON workflow file. 
Since the SSL certificate handling of ComfyUI's Python environment may not support all HTTPS endpoints, there is an option to ignore SSL errors when loading from URL. Use this option with caution and only for trusted sources.

## Use Cases

- Reuse a prompt, sampler, or decode chain across multiple workflows.
- Wrap model-specific pipelines behind a small set of named inputs and outputs.
- Build compact higher-level workflows from tested lower-level workflows.
- Keep experimental graph sections isolated while exposing only the inputs and outputs that matter.
- Share common workflow pieces without copying all nodes into every workflow.

## Notes

- Developed and tested with ComfyUI version 0.18.2.
- The `Subworkflow` node sets the input and output parameters when loading the inner workflow. This load is executed when the outer workflow is loaded. When linked nodes do not match the expected input types provided by `Subworkflow Output` and `Subworkflow Input` from inner workflow, the links are severed silently. 
- The `Subworkflow Output` node will not pass through values to it's output when it's used as inner workflow. When the workflow is executed standalone, it will pass through values transparently as expected. 
- The `Subworkflow Input` will ignore any linked nodes to the input values when used as inner workflow. When the workflow is executed standalone, it will use the linked values transparently as expected.
- If the input of a corresponding `Subworkflow Input` on the `Subworkflow` node is not linked, the inner workflow will use the linked node of the `Subworkflow Input` node. This allows for optional inputs on the inner workflow.
- The `Subworkflow` node loads the values from the selected inner workflow as is; including seed numbers. When `at execution` is set to `keep loaded`, the seed value will be updated by the inner workflow if it has a randomize-after-processing node linked to the `Subworkflow Input`. This allows for workflows that need to update their own input values, such as a seed that should randomize on every execution but also be exposed for linking to other nodes.
- The `Subworkflow` node will keep the loaded file untouched, it will never save any changes to the inner workflow back to the file. 
- A large portion of the source code has been created using AI assistance. Without this, the project would not have been possible for me at this time. I have done my best to review and test the generated code, but there may be edge cases or bugs that I have missed. Please report any issues you encounter.

## Known Issues

- [ ] The `Subworkflow` node progress can exceed 100%, sometimes reaching about 200%. Check with the upscale workflow example.
- [ ] Used paths with macro elements are not formatted currectly when used in inner workflow? (use Video Combine node with %date:yyyy-MM-dd%/WAN/Video)
- [ ] Green progress borders appear on more than one node when executing a inner workflow as part of a larger workflow. These borders should be limited to the currently executing node(s) outer workflow.
- [ ] The order if inputs/outputs on the `Subworkflow` node is undetermined (probably based on the order of nodes in the inner workflow JSON). Consider adding an option to control this order.

### Version History

- 0.1.0 - Initial release of the four custom nodes and workflow loading and execution behavior.

### Wish List

- [ ] For each Subworkflow Input node, add an input field in the Subworkflow node for directly setting its value. This also allows for linking of nodes with same type. Similar as subgraphs. Check if this conflicts with unlinked inputs.

### Debug Logging

*Backend debug logging* is controlled by the `COMFYUI_SUBWORKFLOW_DEBUG` environment variable.

- When set to `true`, trace-style Python logs are enabled.
- When unset or set to `false`, only normal release logs are shown.

When using ComfyUI portable, adjust the launch script and add the following after 'setlocal' line:
```bash
...
setlocal
set COMFYUI_SUBWORKFLOW_DEBUG=1
...
```

*Frontend debug logging* is separate and can be enabled in the browser console:

- Enable it by setting the `swf_debug` item in `localStorage` to `"1"`:

```js
localStorage.setItem("swf_debug", "1")
```
