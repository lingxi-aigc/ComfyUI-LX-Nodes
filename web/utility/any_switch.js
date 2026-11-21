import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXAnySwitch";
const INPUT_PREFIX = "输入";
const OUTPUT_NAME = "输出";
const MIN_INPUTS = 5;
const STABILIZE_DELAY = 64;

function inputName(index) {
    return `${INPUT_PREFIX}${index}`;
}

function inputIndex(name) {
    const match = String(name || "").match(/^输入(\d+)$/);
    return match ? Number.parseInt(match[1], 10) : 0;
}

function isSwitchInput(input) {
    return inputIndex(input?.name) > 0;
}

function getSwitchInputs(node) {
    return (node.inputs || []).filter(isSwitchInput).sort((a, b) => inputIndex(a.name) - inputIndex(b.name));
}

function isInputConnected(node, input) {
    return node.isInputConnected?.(node.inputs.indexOf(input)) ?? (input.link != null);
}

function canRemoveInput(node, index) {
    const input = node.inputs[index];
    if (!input || isInputConnected(node, input)) return false;
    for (const link of node.graph?.floatingLinks?.values?.() || []) {
        if (link.target_id === node.id && link.target_slot === index) return false;
    }
    return true;
}

function removeNonSwitchInputs(node) {
    let changed = false;
    for (let index = (node.inputs || []).length - 1; index >= 0; index -= 1) {
        if (isSwitchInput(node.inputs[index]) || !canRemoveInput(node, index)) continue;
        node.removeInput(index);
        changed = true;
    }
    return changed;
}

function normalizeInputNames(node) {
    let changed = false;
    const inputs = getSwitchInputs(node);
    inputs.forEach((input, index) => {
        const name = inputName(index + 1);
        if (input.name !== name) {
            input.name = name;
            changed = true;
        }
        input.label = name;
    });
    return changed;
}

function getLink(graph, linkId) {
    if (linkId == null) return null;
    return graph?.getLink?.(linkId) ?? graph?.links?.get?.(linkId) ?? graph?._links?.get?.(linkId)
        ?? graph?.links?.[linkId] ?? graph?._links?.[linkId] ?? null;
}

function getInputLinkType(node) {
    const graph = node.graph || app.graph;
    for (const input of getSwitchInputs(node)) {
        const link = node.graph && typeof node.getInputLink === "function"
            ? node.getInputLink(node.inputs.indexOf(input)) : getLink(graph, input.link);
        const origin = graph?.getNodeById?.(link?.origin_id);
        const output = origin?.outputs?.[link?.origin_slot];
        const type = output?.type || link?.type;
        if (type && type !== "*") {
            return { type, label: output?.label || output?.name || String(type) };
        }
    }
    return null;
}

function getOutputLinkType(node) {
    const graph = node.graph || app.graph;
    for (const output of node.outputs || []) {
        for (const linkId of output?.links || []) {
            const link = getLink(graph, linkId);
            const target = graph?.getNodeById?.(link?.target_id);
            const input = target?.inputs?.[link?.target_slot];
            const type = input?.type || link?.type;
            if (type && type !== "*") {
                return { type, label: input?.label || input?.name || String(type) };
            }
        }
    }
    return null;
}

function resolveConnectedType(node) {
    return getInputLinkType(node) || getOutputLinkType(node) || { type: "*", label: "*" };
}

function applySlotType(node, slotType) {
    for (const input of node.inputs || []) {
        if (!isSwitchInput(input)) continue;
        input.type = slotType.type;
        input.label = input.name;
        input.optional = true;
    }

    if (!Array.isArray(node.outputs) || !node.outputs.length) return;
    const output = node.outputs[0];
    output.name = OUTPUT_NAME;
    output.label = OUTPUT_NAME;
    output.type = slotType.type;
}

function ensureInput(node, index, slotType) {
    const name = inputName(index);
    let input = (node.inputs || []).find((item) => item?.name === name);
    if (!input) {
        node.addInput(name, slotType.type, { optional: true });
        input = node.inputs?.[node.inputs.length - 1];
    }
    if (input) {
        input.type = slotType.type;
        input.label = name;
        input.optional = true;
    }
}

function ensureMinimumInputs(node, slotType) {
    for (let index = 1; index <= MIN_INPUTS; index += 1) {
        ensureInput(node, index, slotType);
    }
}

function trimTrailingInputs(node) {
    let changed = false;
    while (getSwitchInputs(node).length > MIN_INPUTS) {
        const inputs = getSwitchInputs(node);
        const last = inputs[inputs.length - 1];
        const index = node.inputs.indexOf(last);
        if (!canRemoveInput(node, index)) break;
        const count = node.inputs.length;
        node.removeInput(index);
        if (node.inputs.length === count) break;
        changed = true;
    }
    return changed;
}

function allInputsConnected(node) {
    const inputs = getSwitchInputs(node);
    return inputs.length > 0 && inputs.every((input) => isInputConnected(node, input));
}

function refreshSize(node) {
    if (typeof node.computeSize === "function" && typeof node.setSize === "function") {
        const size = node.computeSize();
        if (Array.isArray(size)) {
            node.setSize([Math.max(node.size?.[0] || 0, size[0]), size[1]]);
        }
    }
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function stabilize(node) {
    if (!node || !Array.isArray(node.inputs)) return;

    const slotType = resolveConnectedType(node);
    let changed = removeNonSwitchInputs(node);
    ensureMinimumInputs(node, slotType);
    changed = normalizeInputNames(node) || changed;
    changed = trimTrailingInputs(node) || changed;
    changed = normalizeInputNames(node) || changed;

    if (allInputsConnected(node)) {
        ensureInput(node, getSwitchInputs(node).length + 1, slotType);
        changed = true;
    }

    applySlotType(node, slotType);
    if (changed) {
        refreshSize(node);
        requestAnimationFrame(() => refreshSize(node));
    } else {
        app.graph?.setDirtyCanvas(true, true);
    }
}

function scheduleStabilize(node) {
    if (!node) return;
    window.clearTimeout(node.__lxAnySwitchTimer);
    node.__lxAnySwitchTimer = window.setTimeout(() => stabilize(node), STABILIZE_DELAY);
}

function install(node) {
    scheduleStabilize(node);
}

app.registerExtension({
    name: "LX.Utility.AnySwitch",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            install(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            install(this);
            return result;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = onConnectionsChange?.apply(this, arguments);
            scheduleStabilize(this);
            return result;
        };
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            install(node);
        }
    },
});
