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
import { $el, ComfyDialog } from "../../scripts/ui.js";

const NODE_CONFIGS = {
    SWF_Subworkflow: {
        kind: "main",
        widgetName: "workflow",
        refreshWidgetNames: ["workflow"],
        describe: "workflow",
        staticWidgetCount: 2, // workflow, reload_each_execution
        infoPath(value) {
            return `/subworkflow/info?source=file&workflow=${encodeURIComponent(value)}`;
        },
    },
    SWF_SubworkflowFromURL: {
        kind: "main",
        widgetName: "url",
        refreshWidgetNames: ["url", "verify_ssl"],
        describe: "workflow URL",
        staticWidgetCount: 3, // url, verify_ssl, reload_each_execution
        infoPath(value, node) {
            const verifySsl = node?.widgets?.find(w => w.name === "verify_ssl")?.value !== false;
            return `/subworkflow/info?source=url&url=${encodeURIComponent(value)}&verify_ssl=${verifySsl ? "true" : "false"}`;
        },
    },
    SWF_SubworkflowModifierSource: {
        kind: "modifier_source",
        widgetName: "workflow",
        refreshWidgetNames: ["workflow"],
        describe: "workflow",
        infoPath(value) {
            return `/subworkflow/info?source=file&workflow=${encodeURIComponent(value)}`;
        },
    },
    SWF_SubworkflowModifierSourceFromURL: {
        kind: "modifier_source",
        widgetName: "url",
        refreshWidgetNames: ["url", "verify_ssl"],
        describe: "workflow URL",
        infoPath(value, node) {
            const verifySsl = node?.widgets?.find(w => w.name === "verify_ssl")?.value !== false;
            return `/subworkflow/info?source=url&url=${encodeURIComponent(value)}&verify_ssl=${verifySsl ? "true" : "false"}`;
        },
    },
};
const MAX_SLOTS = 8;
const LOG = "[SWF]";
const DEBUG = window.localStorage?.getItem("swf_debug") === "1";
let workflowErrorDialog = null;
let lastWorkflowErrorKey = null;

const debugLog = (...args) => {
    if (DEBUG) console.log(LOG, ...args);
};

const debugWarn = (...args) => {
    if (DEBUG) console.warn(LOG, ...args);
};

debugLog("extension module loaded", {
    configuredNodeTypes: Object.keys(NODE_CONFIGS),
});

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

function clearWorkflowError() {
    lastWorkflowErrorKey = null;
    if (
        workflowErrorDialog &&
        workflowErrorDialog.element &&
        workflowErrorDialog.element.style.display !== "none" &&
        typeof workflowErrorDialog.close === "function"
    ) {
        workflowErrorDialog.close();
    }
}

function showWorkflowError(config, value, message) {
    const text = String(message || `Unable to load ${config.describe}`);
    const key = `${config.describe}\n${value || ""}\n${text}`;
    if (key === lastWorkflowErrorKey) return;
    lastWorkflowErrorKey = key;

    if (!workflowErrorDialog) {
        workflowErrorDialog = new ComfyDialog();
    }

    workflowErrorDialog.show(
        $el("div", {
            style: {
                display: "flex",
                flexDirection: "column",
                gap: "10px",
                maxWidth: "720px",
            },
        }, [
            $el("h3", {
                textContent: "Subworkflow load failed",
                style: {
                    margin: "0",
                    color: "#fff",
                    fontFamily: "sans-serif",
                },
            }),
            $el("div", {
                textContent: `Could not load ${config.describe}${value ? `: ${value}` : ""}`,
                style: {
                    color: "#ddd",
                    fontFamily: "sans-serif",
                    overflowWrap: "anywhere",
                },
            }),
            $el("pre", {
                textContent: text,
                style: {
                    margin: "0",
                    padding: "10px",
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    maxHeight: "320px",
                    overflow: "auto",
                    color: "#fff",
                    background: "#221111",
                    border: "1px solid #6f2b2b",
                    borderRadius: "4px",
                },
            }),
        ])
    );
}

async function fetchWorkflowInfo(config, value, node) {
    if (!value) {
        debugLog(`fetchWorkflowInfo: skipping empty ${config.describe} value`);
        clearWorkflowError();
        return null;
    }
    const path = config.infoPath(value, node);
    debugLog(`fetchWorkflowInfo: fetching info for ${config.describe}`, {
        value,
        path,
    });
    try {
        const resp = await api.fetchApi(path);
        debugLog(`fetchWorkflowInfo: response status ${resp.status} for "${value}"`, {
            url: resp.url,
            redirected: resp.redirected,
        });
        let data = null;
        try {
            data = await resp.json();
            debugLog("fetchWorkflowInfo: response payload", data);
        } catch (e) {
            debugWarn(`fetchWorkflowInfo: failed to parse JSON response for "${value}"`, e);
        }
        if (!resp.ok) {
            debugWarn(`fetchWorkflowInfo: HTTP ${resp.status} for "${value}"`);
            showWorkflowError(config, value, data?.error || `HTTP ${resp.status} while loading ${config.describe}`);
            return null;
        }
        if (!data) {
            const message = `Invalid response while loading ${config.describe}: expected JSON`;
            debugWarn(`fetchWorkflowInfo: ${message}`);
            showWorkflowError(config, value, message);
            return null;
        }
        if (data.error) {
            debugWarn(`fetchWorkflowInfo: server error for "${value}":`, data.error);
            showWorkflowError(config, value, data.error);
            return null;
        }
        clearWorkflowError();
        debugLog(`fetchWorkflowInfo: got ${data.inputs.length} input(s), ${data.outputs.length} output(s) for "${value}"`);
        return data;
    } catch (e) {
        console.error(LOG, "fetchWorkflowInfo: fetch failed:", e);
        showWorkflowError(config, value, e);
        return null;
    }
}

function updateInputSlots(node, inputs) {
    debugLog("updateInputSlots: before", slotSummary(node.inputs));
    if (node.inputs) {
        for (let i = node.inputs.length - 1; i >= 0; i--) {
            if (node.inputs[i].name?.startsWith("swf_in_")) node.removeInput(i);
        }
    }
    inputs.slice(0, MAX_SLOTS).forEach((inp, i) => {
        debugLog(`updateInputSlots: adding swf_in_${i}`, inp);
        node.addInput(`swf_in_${i}`, swfSlotType(inp), { label: inp.slot_name });
    });
    debugLog("updateInputSlots: after", slotSummary(node.inputs));
}

function updateOutputSlots(node, outputs) {
    const needCount = Math.min(outputs.length, MAX_SLOTS);
    debugLog("updateOutputSlots: before", slotSummary(node.outputs));

    for (let i = (node.outputs || []).length - 1; i >= 0; i--) {
        const out = node.outputs[i];
        if (!/^out_\d+$/.test(out?.name)) continue;
        const idx = parseInt(out.name.slice(4));
        if (idx >= needCount) {
            debugLog(`updateOutputSlots: removing ${out.name} at index ${i}`);
            node.outputs.splice(i, 1);
        }
    }

    let n = 0;
    for (const out of (node.outputs || [])) {
        if (/^out_\d+$/.test(out.name) && n < needCount) {
            debugLog(`updateOutputSlots: updating ${out.name}`, outputs[n]);
            out.label = outputs[n].slot_name;
            out.type = swfSlotType(outputs[n]);
            n++;
        }
    }

    for (let i = n; i < needCount; i++) {
        debugLog(`updateOutputSlots: adding out_${i}`, outputs[i]);
        node.addOutput(`out_${i}`, swfSlotType(outputs[i]), { label: outputs[i].slot_name });
    }

    debugLog(`updateOutputSlots: ${needCount} slot(s), after`, slotSummary(node.outputs));
}

function getModifierSourceInputs(info, selectedModifier) {
    return [];
}

function updateModifierSourceOutputs(node, modifiers) {
    updateOutputSlots(node, modifiers || []);
}

const _OW_MARGIN = 15;
const _OW_VAL_W = 80;  // value area width
// Toggle track width = H * _OW_TOG_RATIO (matches ComfyUI boolean widget style)
const _OW_TOG_RATIO = 1.5;

/**
 * Build a single custom widget that shows a toggle checkbox and a number input
 * in one row.  The widget's .value is { use: bool, val: number } so both pieces
 * are serialised together as one entry in widgets_values.
 */
function _makeOverrideWidget(node, slotIndex, inp, useVal, numVal) {
    const isInt = inp.type === "INT";
    const M = _OW_MARGIN;
    const TOG = _OW_TOG_RATIO;
    const VAL_W = _OW_VAL_W;

    const widget = {
        name: `swf_override_${slotIndex}`,
        type: "swf_override",
        value: { use: Boolean(useVal), val: numVal },
        options: {},

        computeSize(width) {
            return [width, LiteGraph.NODE_WIDGET_HEIGHT ?? 20];
        },

        draw(ctx, node, width, y, H) {
            const slot = node.inputs?.find(s => s.name === `swf_in_${slotIndex}`);
            const linked = slot?.link != null;
            const useOverride = !linked && Boolean(this.value?.use);
            const val = this.value?.val ?? 0;
            const togW = H * TOG;  // total toggle slot width

            ctx.save();

            // Background pill — symmetric margins and outline to match ComfyUI widgets
            ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
            ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(M, y, width - 2 * M, H, [H * 0.5]);
            ctx.fill();
            ctx.stroke();

            ctx.textBaseline = "middle";

            if (linked) {
                ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
                ctx.textAlign = "left";
                ctx.fillText(inp.slot_name, M + 8, y + H * 0.5);
                ctx.textAlign = "right";
                ctx.fillText("linked", width - M - 8, y + H * 0.5);
            } else {
                // Toggle switch (ComfyUI boolean widget style)
                const togX = M + 6;
                const knobR = H * 0.3;
                const trackX = togX + 4;
                const trackY = y + 4;
                const trackW = togW - 8;
                const trackH = H - 8;

                // Track: semi-transparent white background
                ctx.beginPath();
                ctx.roundRect(trackX, trackY, trackW, trackH, [trackH * 0.5]);
                ctx.globalAlpha = 0.25;
                ctx.fillStyle = "rgba(255,255,255,0.45)";
                ctx.fill();
                ctx.globalAlpha = 1;

                // Knob
                const knobX = useOverride ? togX + H : togX + H * 0.5;
                ctx.beginPath();
                ctx.arc(knobX, y + H * 0.5, knobR, 0, Math.PI * 2);
                ctx.fillStyle = useOverride ? "#89B" : "#888";
                ctx.fill();

                // Label (slot name, capped so it doesn't overflow into value area)
                const valAreaX = width - M - VAL_W - 4;
                const labelX = M + 6 + togW + 5;
                ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
                ctx.textAlign = "left";
                ctx.fillText(inp.slot_name, labelX, y + H * 0.5, valAreaX - labelX - 4);

                // Value area
                if (useOverride) {
                    ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
                    ctx.beginPath();
                    ctx.roundRect(valAreaX, y + 2, VAL_W, H - 4, [H * 0.5 - 2]);
                    ctx.fill();

                    const displayStr = isInt
                        ? String(Math.round(val))
                        : String(parseFloat(val.toPrecision(4)));
                    ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
                    ctx.textAlign = "right";
                    ctx.fillText(displayStr, valAreaX + VAL_W - 6, y + H * 0.5, VAL_W - 10);
                } else {
                    ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
                    ctx.textAlign = "right";
                    ctx.fillText("(inner fallback)", width - M - 8, y + H * 0.5);
                }
            }

            ctx.restore();
        },

        mouse(event, pos, node) {
            const [x] = pos;
            const slot = node.inputs?.find(s => s.name === `swf_in_${slotIndex}`);
            if (slot?.link != null) return false;

            const H = LiteGraph.NODE_WIDGET_HEIGHT ?? 20;
            const togX = M + 6;
            const togEnd = togX + H * TOG + 4;
            const valAreaX = node.size[0] - M - VAL_W - 4;

            if (event.type === "mousedown" || event.type === "pointerdown") {
                if (x >= togX && x < togEnd) {
                    // Toggle
                    this.value = { ...this.value, use: !this.value.use };
                    app.graph.setDirtyCanvas(true, false);
                    if (node.onWidgetChanged) node.onWidgetChanged(this.name, this.value, null, this);
                    return true;
                }
                if (x >= valAreaX && this.value?.use) {
                    app.canvas.prompt(inp.slot_name, this.value?.val ?? 0, (v) => {
                        let num = parseFloat(v);
                        if (!isNaN(num)) {
                            if (isInt) num = Math.round(num);
                            this.value = { ...this.value, val: num };
                            app.graph.setDirtyCanvas(true, false);
                            if (node.onWidgetChanged) node.onWidgetChanged(this.name, this.value, null, this);
                        }
                    }, event);
                    return true;
                }
            }
            return false;
        },
    };

    node.widgets ??= [];
    node.widgets.push(widget);
    return widget;
}

/**
 * Synchronise override widgets for all INT/FLOAT input slots.
 *
 * Removes stale swf_override_* widgets, then for each primitive-typed slot adds one
 * combined custom widget (swf_override_i) and links the swf_in_i input slot to it so
 * the connection dot appears inline at the widget row instead of in a separate inputs
 * section above the widgets.
 *
 * pendingOverrideValues: flat array of saved widget VALUES — one entry per primitive
 * slot, each being the serialised { use, val } object.  Pass null when no saved state.
 */
function _syncOverrideWidgets(node, inputs, config, pendingOverrideValues) {
    if (config?.kind !== "main") return;

    // Remove stale override widgets.
    if (node.widgets) {
        for (let i = node.widgets.length - 1; i >= 0; i--) {
            if (node.widgets[i].name?.startsWith("swf_override_")) {
                node.widgets.splice(i, 1);
            }
        }
    }

    let pendingOffset = 0;

    inputs.slice(0, MAX_SLOTS).forEach((inp, i) => {
        if (inp.type !== "INT" && inp.type !== "FLOAT") return;

        const defaultVal = (inp.default != null) ? inp.default : (inp.type === "INT" ? 0 : 0.0);
        const savedOverride = pendingOverrideValues?.[pendingOffset];
        pendingOffset += 1;

        const useVal = savedOverride?.use ?? false;
        const numVal = savedOverride?.val ?? defaultVal;

        const widget = _makeOverrideWidget(node, i, inp, useVal, numVal);

        // Link the input slot to this widget: LiteGraph then draws the connection dot
        // at the widget's y-position rather than as a separate slot in the inputs list.
        const slot = node.inputs?.find(s => s.name === `swf_in_${i}`);
        if (slot) slot.widget = { name: widget.name };
    });
}

function applyWorkflowInfo(node, info, config) {
    if (!info) {
        debugWarn("applyWorkflowInfo: no workflow info to apply", { nodeId: node.id });
        return;
    }
    node.__swfWorkflowInfo = info;
    const { inputs = [], outputs = [] } = info;
    debugLog(`applyWorkflowInfo: ${inputs.length} input(s), ${outputs.length} output(s)`, {
        nodeId: node.id,
        currentInputs: slotSummary(node.inputs),
        currentOutputs: slotSummary(node.outputs),
    });
    if (config?.kind === "modifier_source") {
        updateInputSlots(node, []);
        updateModifierSourceOutputs(node, info.modifiers || []);
    } else {
        updateInputSlots(node, inputs);
        updateOutputSlots(node, outputs);
        _syncOverrideWidgets(node, inputs, config, null);
    }
    setNodeSizeAtLeast(node, node.computeSize());
    app.graph.setDirtyCanvas(true, true);
}

function applyWorkflowInfoOnLoad(node, info, savedInputCount, savedSize, config, pendingOverrideValues) {
    if (!info) {
        debugWarn("applyWorkflowInfoOnLoad: no workflow info to apply", { nodeId: node.id, savedInputCount });
        return;
    }
    node.__swfWorkflowInfo = info;
    const { inputs = [], outputs = [] } = info;
    debugLog(`applyWorkflowInfoOnLoad: server=${inputs.length}in/${outputs.length}out, savedInputs=${savedInputCount}`, {
        nodeId: node.id,
        currentInputs: slotSummary(node.inputs),
        currentOutputs: slotSummary(node.outputs),
    });

    if (config?.kind === "modifier_source") {
        const sourceInputs = [];
        if (savedInputCount === sourceInputs.length) {
            debugLog("applyWorkflowInfoOnLoad: modifier source input count matches, updating labels only");
            let idx = 0;
            for (const inp of (node.inputs || [])) {
                if (inp.name?.startsWith("swf_in_") && idx < sourceInputs.length) {
                    inp.label = sourceInputs[idx].slot_name;
                    inp.type = swfSlotType(sourceInputs[idx]);
                    idx++;
                }
            }
        } else {
            debugLog(`applyWorkflowInfoOnLoad: modifier source input count changed (${savedInputCount}->${sourceInputs.length}), full refresh`);
            updateInputSlots(node, sourceInputs);
        }
        updateModifierSourceOutputs(node, info.modifiers || []);
    } else if (savedInputCount === inputs.length) {
        debugLog("applyWorkflowInfoOnLoad: input count matches, updating labels only");
        let idx = 0;
        for (const inp of (node.inputs || [])) {
            if (inp.name?.startsWith("swf_in_") && idx < inputs.length) {
                inp.label = inputs[idx].slot_name;
                inp.type = swfSlotType(inputs[idx]);
                idx++;
            }
        }
        // Override widgets are not yet present even on the fast path — add them now.
        _syncOverrideWidgets(node, inputs, config, pendingOverrideValues);
    } else {
        debugLog(`applyWorkflowInfoOnLoad: input count changed (${savedInputCount}->${inputs.length}), full refresh`);
        updateInputSlots(node, inputs);
        _syncOverrideWidgets(node, inputs, config, pendingOverrideValues);
    }

    if (config?.kind !== "modifier_source") {
        updateOutputSlots(node, outputs);
    }

    if (savedSize) {
        debugLog("applyWorkflowInfoOnLoad: restoring saved node size", savedSize);
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
        if (!config) {
            if (String(nodeData.name || "").startsWith("SWF_")) {
                debugLog("beforeRegisterNodeDef: ignoring unconfigured SWF node", nodeData.name);
            }
            return;
        }

        debugLog("beforeRegisterNodeDef: patching", nodeData.name, nodeData);

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (serializedNode) {
            debugLog("onConfigure: restoring node from saved workflow", {
                nodeType: nodeData.name,
                nodeId: this.id,
                serializedWidgetValues: serializedNode?.widgets_values,
                serializedProperties: serializedNode?.properties,
                serializedInputCount: serializedNode?.inputs?.length,
                serializedOutputCount: serializedNode?.outputs?.length,
            });

            const savedInputCount = (serializedNode.inputs || [])
                .filter(i => i.name?.startsWith("swf_in_")).length;
            const savedSize = cloneSize(serializedNode.size);
            debugLog(`onConfigure: serialized node has ${savedInputCount} dynamic input(s)`);

            // Stash override widget values that follow the static widgets in widgets_values.
            // These are restored after the async workflow-info fetch completes.
            const staticCount = config.staticWidgetCount ?? 0;
            const pendingOverrideValues = (serializedNode.widgets_values || []).slice(staticCount);
            debugLog(`onConfigure: stashed ${pendingOverrideValues.length} pending override value(s)`, {
                staticCount,
                pendingOverrideValues,
            });

            // Prepare INT/FLOAT slots so origOnConfigure sees both the link AND slot.widget
            // together in the serialized data.  ComfyUI handles that combination correctly
            // (same as a freshly-saved new workflow).  Without this patch, old workflows
            // (saved before override widgets existed) arrive with no slot.widget; when we
            // set it later via _syncOverrideWidgets ComfyUI treats it as a "convert widget
            // to input" operation and silently drops the existing link.
            if (config?.kind === "main") {
                // Remove any stale stubs first.
                if (this.widgets) {
                    for (let i = this.widgets.length - 1; i >= 0; i--) {
                        if (this.widgets[i].name?.startsWith("swf_override_")) {
                            this.widgets.splice(i, 1);
                        }
                    }
                }
                let primIdx = 0;
                for (const sinp of (serializedNode.inputs || [])) {
                    if (!sinp.name?.startsWith("swf_in_")) continue;
                    if (sinp.type !== "INT" && sinp.type !== "FLOAT") continue;
                    const slotIdx = parseInt(sinp.name.slice(7)); // "swf_in_".length === 7
                    const saved = pendingOverrideValues[primIdx++];
                    // Create the stub widget so the name exists when origOnConfigure validates it.
                    _makeOverrideWidget(this, slotIdx,
                        { type: sinp.type, slot_name: sinp.label || sinp.name, default: null },
                        saved?.use ?? false,
                        saved?.val ?? 0,
                    );
                    // Patch the serialized input so origOnConfigure sees slot.widget in the JSON.
                    // New workflows already have this; for old ones we add it here so the
                    // link+widget pair is restored atomically rather than link-first then widget.
                    if (!sinp.widget) {
                        sinp.widget = { name: `swf_override_${slotIdx}` };
                    }
                }
                debugLog(`onConfigure: prepared ${primIdx} override stub(s) before origOnConfigure`);
            }

            if (origOnConfigure) origOnConfigure.call(this, serializedNode);
            debugLog("onConfigure: after original handler", {
                nodeType: nodeData.name,
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({
                    name: w.name,
                    value: w.value,
                    type: w.type,
                    hasCallback: !!w.callback,
                })),
            });

            const widget = this.widgets?.find(w => w.name === config.widgetName);
            const sourceValue = widget?.value;
            debugLog(`onConfigure: ${config.widgetName} widget value =`, sourceValue, {
                nodeType: nodeData.name,
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });

            if (sourceValue) {
                fetchWorkflowInfo(config, sourceValue, this).then(info => {
                    applyWorkflowInfoOnLoad(this, info, savedInputCount, savedSize, config, pendingOverrideValues);
                });
            } else {
                clearWorkflowError();
                debugWarn(`onConfigure: ${config.widgetName} widget not found or empty`, { nodeId: this.id });
            }
        };

        const origOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, slotIndex, connected, linkInfo) {
            if (origOnConnectionsChange) origOnConnectionsChange.call(this, type, slotIndex, connected, linkInfo);
            if (config?.kind !== "main") return;
            if (type !== LiteGraph.INPUT) return;

            const inp = (this.inputs || [])[slotIndex];
            if (!inp?.name?.startsWith("swf_in_")) return;

            // The custom widget's draw() checks the link state itself — just redraw.
            app.graph.setDirtyCanvas(true, false);
        };

        const origOnWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name, value, oldValue, widget) {
            if (origOnWidgetChanged) origOnWidgetChanged.call(this, name, value, oldValue, widget);
            debugLog("onWidgetChanged: observed widget change", {
                nodeType: nodeData.name,
                nodeId: this.id,
                name,
                value,
                oldValue,
                watchedWidget: config.widgetName,
                widgetType: widget?.type,
            });
            if (config.refreshWidgetNames.includes(name)) {
                const sourceValue = this.widgets?.find(w => w.name === config.widgetName)?.value;
                debugLog(`onWidgetChanged: ${config.widgetName} changed from "${oldValue}" to "${value}"`, {
                    nodeId: this.id,
                    inputs: slotSummary(this.inputs),
                    outputs: slotSummary(this.outputs),
                });
                fetchWorkflowInfo(config, sourceValue, this).then(info => applyWorkflowInfo(this, info, config));
            }
        };

        const origOnAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            if (origOnAdded) origOnAdded.call(this);
            const widget = this.widgets?.find(w => w.name === config.widgetName);
            const val = widget?.value;
            debugLog(`onAdded: node placed on canvas, ${config.widgetName} =`, val, {
                nodeType: nodeData.name,
                nodeId: this.id,
                widgets: (this.widgets || []).map(w => ({ name: w.name, value: w.value, type: w.type })),
                inputs: slotSummary(this.inputs),
                outputs: slotSummary(this.outputs),
            });
            if (val) {
                fetchWorkflowInfo(config, val, this).then(info => applyWorkflowInfo(this, info, config));
            } else {
                clearWorkflowError();
                debugWarn(`onAdded: ${config.widgetName} widget not found or empty`, { nodeId: this.id });
            }
        };
    },
});
