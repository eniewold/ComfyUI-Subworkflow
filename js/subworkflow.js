/**
 * Frontend extension for the Subworkflow nodes.
 *
 * When the source widget changes, this extension queries the backend for the
 * inner workflow's Subworkflow Input / Subworkflow Output info and dynamically
 * updates the node's input and output slots.
 *
 * Input slots are named swf_in_0, swf_in_1, ... (matching the Python backend).
 * Output slots are named out_0, out_1, ...      (matching RETURN_NAMES).
 * Both use display labels from the inner workflow's slot_name values.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_CONFIGS = {
    SWF_Subworkflow: {
        widgetName: "workflow",
        describe: "workflow",
        infoPath(value) {
            return `/subworkflow/info?source=file&workflow=${encodeURIComponent(value)}`;
        },
    },
    SWF_SubworkflowFromURL: {
        widgetName: "url",
        describe: "workflow URL",
        infoPath(value) {
            return `/subworkflow/info?source=url&url=${encodeURIComponent(value)}`;
        },
    },
};
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

function cloneSize(size) {
    return Array.isArray(size) && size.length >= 2 ? [size[0], size[1]] : null;
}

function setNodeSizeAtLeast(node, minSize) {
    const current = cloneSize(node.size);
    if (!current || !minSize) return;
    node.setSize([
        Math.max(current[0], minSize[0]),
        Math.max(current[1], minSize[1]),
    ]);
}

async function fetchWorkflowInfo(config, value) {
    if (!value) {
        console.log(LOG, `fetchWorkflowInfo: skipping empty ${config.describe} value`);
        return null;
    }
    console.log(LOG, `fetchWorkflowInfo: fetching info for ${config.describe}`, value);
    try {
        const resp = await api.fetchApi(config.infoPath(value));
        console.log(LOG, `fetchWorkflowInfo: response status ${resp.status} for "${value}"`);
        if (!resp.ok) {
            console.warn(LOG, `fetchWorkflowInfo: HTTP ${resp.status} for "${value}"`);
            return null;
        }
        const data = await resp.json();
        console.log(LOG, "fetchWorkflowInfo: response payload", data);
        if (data.error) {
            console.warn(LOG, `fetchWorkflowInfo: server error for "${value}":`, data.error);
            return null;
        }
        console.log(LOG, `fetchWorkflowInfo: got ${data.inputs.length} input(s), ${data.outputs.length} output(s) for "${value}"`);
        return data;
    } catch (e) {
        console.error(LOG, "fetchWorkflowInfo: fetch failed:", e);
        return null;
    }
}

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

function updateOutputSlots(node, outputs) {
    const needCount = Math.min(outputs.length, MAX_SLOTS);
    console.log(LOG, "updateOutputSlots: before", slotSummary(node.outputs));

    for (let i = (node.outputs || []).length - 1; i >= 0; i--) {
        const out = node.outputs[i];
        if (!/^out_\d+$/.test(out?.name)) continue;
        const idx = parseInt(out.name.slice(4));
        if (idx >= needCount) {
            console.log(LOG, `updateOutputSlots: removing ${out.name} at index ${i}`);
            node.outputs.splice(i, 1);
        }
    }

    let n = 0;
    for (const out of (node.outputs || [])) {
        if (/^out_\d+$/.test(out.name) && n < needCount) {
            console.log(LOG, `updateOutputSlots: updating ${out.name}`, outputs[n]);
            out.label = outputs[n].slot_name;
            out.type = swfSlotType(outputs[n]);
            n++;
        }
    }

    for (let i = n; i < needCount; i++) {
        console.log(LOG, `updateOutputSlots: adding out_${i}`, outputs[i]);
        node.addOutput(`out_${i}`, swfSlotType(outputs[i]), { label: outputs[i].slot_name });
    }

    console.log(LOG, `updateOutputSlots: ${needCount} slot(s), after`, slotSummary(node.outputs));
}

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
    setNodeSizeAtLeast(node, node.computeSize());
    app.graph.setDirtyCanvas(true, true);
}

function applyWorkflowInfoOnLoad(node, info, savedInputCount, savedSize) {
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
        console.log(LOG, `applyWorkflowInfoOnLoad: input count changed (${savedInputCount}->${inputs.length}), full refresh`);
        updateInputSlots(node, inputs);
    }

    updateOutputSlots(node, outputs);

    if (savedSize) {
        console.log(LOG, "applyWorkflowInfoOnLoad: restoring saved node size", savedSize);
        node.setSize(savedSize);
    } else {
        setNodeSizeAtLeast(node, node.computeSize());
    }
    app.graph.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "SWF.Subworkflow",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const config = NODE_CONFIGS[nodeData.name];
        if (!config) return;

        console.log(LOG, "beforeRegisterNodeDef: patching", nodeData.name, nodeData);

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (serializedNode) {
            console.log(LOG, "onConfigure: restoring node from saved workflow");

            const savedInputCount = (serializedNode.inputs || [])
                .filter(i => i.name?.startsWith("swf_in_")).length;
            const savedSize = cloneSize(serializedNode.size);
            console.log(LOG, `onConfigure: serialized node has ${savedInputCount} dynamic input(s)`);

            if (origOnConfigure) origOnConfigure.call(this, serializedNode);

            const widget = this.widgets?.find(w => w.name === config.widgetName);
            const sourceValue = widget?.value;
            console.log(LOG, `onConfigure: ${config.widgetName} widget value =`, sourceValue, {
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });

            if (sourceValue) {
                fetchWorkflowInfo(config, sourceValue).then(info => {
                    applyWorkflowInfoOnLoad(this, info, savedInputCount, savedSize);
                });
            } else {
                console.warn(LOG, `onConfigure: ${config.widgetName} widget not found or empty`, { nodeId: this.id });
            }
        };

        const origOnWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name, value, oldValue, widget) {
            if (origOnWidgetChanged) origOnWidgetChanged.call(this, name, value, oldValue, widget);
            if (name === config.widgetName) {
                console.log(LOG, `onWidgetChanged: ${config.widgetName} changed from "${oldValue}" to "${value}"`, {
                    nodeId: this.id,
                    inputs: slotSummary(this.inputs),
                    outputs: slotSummary(this.outputs),
                });
                fetchWorkflowInfo(config, value).then(info => applyWorkflowInfo(this, info));
            }
        };

        const origOnAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            if (origOnAdded) origOnAdded.call(this);
            const widget = this.widgets?.find(w => w.name === config.widgetName);
            const val = widget?.value;
            console.log(LOG, `onAdded: node placed on canvas, ${config.widgetName} =`, val, {
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });
            if (val) {
                fetchWorkflowInfo(config, val).then(info => applyWorkflowInfo(this, info));
            } else {
                console.warn(LOG, `onAdded: ${config.widgetName} widget not found or empty`, { nodeId: this.id });
            }
        };
    },
});
