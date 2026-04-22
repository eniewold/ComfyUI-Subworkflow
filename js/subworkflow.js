/**
 * Frontend extension for the Subworkflow node.
 *
 * When the "workflow" widget changes, this extension queries the backend for
 * the inner workflow's Subworkflow Input / Subworkflow Output info and dynamically
 * updates the node's input and output slots.
 *
 * Input slots are named  swf_in_0, swf_in_1, …  (matching the Python backend).
 * Output slots are named out_0, out_1, …         (matching RETURN_NAMES).
 * Both use display labels from the inner workflow's slot_name values.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "SWF_Subworkflow";
const MAX_SLOTS = 8;
const LOG = "[SWF]";

function slotSummary(slots) {
    return (slots || []).map((slot, index) => ({
        index,
        name: slot?.name,
        label: slot?.label,
        type: slot?.type,
        links: slot?.links,
        link: slot?.link,
    }));
}

function swfSlotType(info) {
    return info?.type || "*";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function fetchWorkflowInfo(workflowName) {
    if (!workflowName) {
        console.log(LOG, "fetchWorkflowInfo: skipping empty workflow value");
        return null;
    }
    console.log(LOG, "fetchWorkflowInfo: fetching info for", workflowName);
    try {
        const resp = await api.fetchApi(
            `/subworkflow/info?workflow=${encodeURIComponent(workflowName)}`
        );
        console.log(LOG, `fetchWorkflowInfo: response status ${resp.status} for "${workflowName}"`);
        if (!resp.ok) {
            console.warn(LOG, `fetchWorkflowInfo: HTTP ${resp.status} for "${workflowName}"`);
            return null;
        }
        const data = await resp.json();
        console.log(LOG, "fetchWorkflowInfo: response payload", data);
        if (data.error) {
            console.warn(LOG, `fetchWorkflowInfo: server error for "${workflowName}":`, data.error);
            return null;
        }
        console.log(LOG, `fetchWorkflowInfo: got ${data.inputs.length} input(s), ${data.outputs.length} output(s) for "${workflowName}"`);
        return data;
    } catch (e) {
        console.error(LOG, "fetchWorkflowInfo: fetch failed:", e);
        return null;
    }
}

/**
 * Update the dynamic input slots (swf_in_*) on a node.
 * Always does a full remove-and-add since input slots don't suffer from the
 * re-addition problem that output slots do.
 */
function updateInputSlots(node, inputs) {
    console.log(LOG, "updateInputSlots: before", slotSummary(node.inputs));
    if (node.inputs) {
        for (let i = node.inputs.length - 1; i >= 0; i--) {
            if (node.inputs[i].name?.startsWith("swf_in_")) node.removeInput(i);
        }
    }
    inputs.slice(0, MAX_SLOTS).forEach((inp, i) => {
        console.log(LOG, `updateInputSlots: adding swf_in_${i}`, inp);
        node.addInput(`swf_in_${i}`, swfSlotType(inp), { label: inp.slot_name });
    });
    console.log(LOG, "updateInputSlots: after", slotSummary(node.inputs));
}

/**
 * Update the dynamic output slots (out_*) on a node.
 *
 * We splice node.outputs directly instead of calling removeOutput().
 * removeOutput() calls graph.connectionChange() which triggers ComfyUI's
 * node-sync machinery and immediately re-adds all RETURN_TYPES slots.
 * Direct splice bypasses that callback entirely.
 */
function updateOutputSlots(node, outputs) {
    const needCount = Math.min(outputs.length, MAX_SLOTS);
    console.log(LOG, "updateOutputSlots: before", slotSummary(node.outputs));

    // Remove excess out_* slots from the end, bypassing removeOutput().
    for (let i = (node.outputs || []).length - 1; i >= 0; i--) {
        const out = node.outputs[i];
        if (!/^out_\d+$/.test(out?.name)) continue;
        const idx = parseInt(out.name.slice(4));
        if (idx >= needCount) {
            console.log(LOG, `updateOutputSlots: removing ${out.name} at index ${i}`);
            node.outputs.splice(i, 1);
        }
    }

    // Update labels on surviving slots.
    let n = 0;
    for (const out of (node.outputs || [])) {
        if (/^out_\d+$/.test(out.name) && n < needCount) {
            console.log(LOG, `updateOutputSlots: updating ${out.name}`, outputs[n]);
            out.label = outputs[n].slot_name;
            out.type = swfSlotType(outputs[n]);
            n++;
        }
    }

    // Add any slots still missing (addOutput is safe — no connectionChange).
    for (let i = n; i < needCount; i++) {
        console.log(LOG, `updateOutputSlots: adding out_${i}`, outputs[i]);
        node.addOutput(`out_${i}`, swfSlotType(outputs[i]), { label: outputs[i].slot_name });
    }

    console.log(LOG, `updateOutputSlots: ${needCount} slot(s), after`, slotSummary(node.outputs));
}

// ---------------------------------------------------------------------------
// Public slot-update entry points
// ---------------------------------------------------------------------------

/** Full refresh — used when user picks a new workflow via the combo. */
function applyWorkflowInfo(node, info) {
    if (!info) {
        console.warn(LOG, "applyWorkflowInfo: no workflow info to apply", { nodeId: node.id });
        return;
    }
    const { inputs = [], outputs = [] } = info;
    console.log(LOG, `applyWorkflowInfo: ${inputs.length} input(s), ${outputs.length} output(s)`, {
        nodeId: node.id,
        currentInputs: slotSummary(node.inputs),
        currentOutputs: slotSummary(node.outputs),
    });
    updateInputSlots(node, inputs);
    updateOutputSlots(node, outputs);
    node.setSize(node.computeSize());
    app.graph.setDirtyCanvas(true, true);
}

/**
 * Load restore — used from onConfigure.
 * For inputs: full refresh is safe (LiteGraph restores input links after
 *   onConfigure, so adding the slot before the link is restored is fine).
 * For outputs: updateOutputSlots splices the array directly, preserving any
 *   already-restored links on out_0 while removing the Python-padded extras.
 */
function applyWorkflowInfoOnLoad(node, info, savedInputCount) {
    if (!info) {
        console.warn(LOG, "applyWorkflowInfoOnLoad: no workflow info to apply", { nodeId: node.id, savedInputCount });
        return;
    }
    const { inputs = [], outputs = [] } = info;
    console.log(LOG, `applyWorkflowInfoOnLoad: server=${inputs.length}in/${outputs.length}out, savedInputs=${savedInputCount}`, {
        nodeId: node.id,
        currentInputs: slotSummary(node.inputs),
        currentOutputs: slotSummary(node.outputs),
    });

    // Inputs
    if (savedInputCount === inputs.length) {
        console.log(LOG, "applyWorkflowInfoOnLoad: input count matches, updating labels only");
        let idx = 0;
        for (const inp of (node.inputs || [])) {
            if (inp.name?.startsWith("swf_in_") && idx < inputs.length) {
                inp.label = inputs[idx].slot_name;
                inp.type = swfSlotType(inputs[idx]);
                idx++;
            }
        }
    } else {
        console.log(LOG, `applyWorkflowInfoOnLoad: input count changed (${savedInputCount}→${inputs.length}), full refresh`);
        updateInputSlots(node, inputs);
    }

    // Outputs — splice excess slots directly (avoids removeOutput callback).
    updateOutputSlots(node, outputs);

    node.setSize(node.computeSize());
    app.graph.setDirtyCanvas(true, true);
}

// ---------------------------------------------------------------------------
// Extension registration
// ---------------------------------------------------------------------------

app.registerExtension({
    name: "SWF.Subworkflow",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        console.log(LOG, "beforeRegisterNodeDef: patching", NODE_TYPE, nodeData);

        // -- onConfigure: called when a saved workflow is loaded ---------------
        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (serializedNode) {
            console.log(LOG, "onConfigure: restoring node from saved workflow");

            // Read saved dynamic input count BEFORE origOnConfigure may change things.
            const savedInputCount = (serializedNode.inputs || [])
                .filter(i => i.name?.startsWith("swf_in_")).length;
            console.log(LOG, `onConfigure: serialized node has ${savedInputCount} dynamic input(s)`);

            if (origOnConfigure) origOnConfigure.call(this, serializedNode);

            const widget = this.widgets?.find(w => w.name === "workflow");
            const workflowName = widget?.value;
            console.log(LOG, "onConfigure: workflow widget value =", workflowName, {
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });

            if (workflowName) {
                fetchWorkflowInfo(workflowName).then(info => {
                    applyWorkflowInfoOnLoad(this, info, savedInputCount);
                });
            } else {
                console.warn(LOG, "onConfigure: workflow widget not found or empty", { nodeId: this.id });
            }
        };

        // -- onWidgetChanged: called when the combo changes --------------------
        const origOnWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name, value, oldValue, widget) {
            if (origOnWidgetChanged) origOnWidgetChanged.call(this, name, value, oldValue, widget);
            if (name === "workflow") {
                console.log(LOG, `onWidgetChanged: workflow changed from "${oldValue}" to "${value}"`, {
                    nodeId: this.id,
                    inputs: slotSummary(this.inputs),
                    outputs: slotSummary(this.outputs),
                });
                fetchWorkflowInfo(value).then(info => applyWorkflowInfo(this, info));
            }
        };

        // -- onAdded: called when the node is first dragged onto the canvas ----
        const origOnAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            if (origOnAdded) origOnAdded.call(this);
            const widget = this.widgets?.find(w => w.name === "workflow");
            const val = widget?.value;
            console.log(LOG, "onAdded: node placed on canvas, workflow =", val, {
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });
            if (val) {
                fetchWorkflowInfo(val).then(info => applyWorkflowInfo(this, info));
            } else {
                console.warn(LOG, "onAdded: workflow widget not found or empty", { nodeId: this.id });
            }
        };
    },
});
