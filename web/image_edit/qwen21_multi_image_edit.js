import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXQwen21MultiImageEdit";
const NEGATIVE_PROMPT = "negative_prompt";
const CUSTOM_RATIO = "自定义比例";
const CUSTOM_SIZE = "自定义宽高";
const REFERENCE_MODE = /^参考图 (\d+) 的画幅$/u;
const REFERENCE_SLOT = /^images\.image_(\d+)$/u;
const canvasModes = new WeakMap();
const pendingReferenceUpdates = new WeakSet();
const LABELS = {
    "canvas.preset_ratio": "宽高比",
    "canvas.ratio": "宽高比",
    "canvas.long_edge": "采样分辨率",
    "canvas.width": "出图宽度（像素）",
    "canvas.height": "出图高度（像素）",
};

function updateCanvasOptions(node) {
    const canvas = node.widgets?.find((widget) => widget.name === "canvas");
    const options = canvasModes.get(node.constructor);
    if (!canvas || !options?.length) return;
    const connected = node.inputs?.filter((slot) => REFERENCE_SLOT.test(slot.name) && slot.link != null).length ?? 0;
    const usable = options.filter((option) => {
        const reference = REFERENCE_MODE.exec(option);
        return !reference || Number(reference[1]) <= connected;
    });
    canvas.options.values = usable;
    if (!usable.includes(canvas.value)) {
        canvas.value = connected ? usable[0] : CUSTOM_RATIO;
    }
    node.setDirtyCanvas?.(true, true);
}

function scheduleReferenceUpdate(node) {
    if (pendingReferenceUpdates.has(node)) return;
    pendingReferenceUpdates.add(node);
    // Autogrow can compact disconnected inputs on the next frame.
    queueMicrotask(() => requestAnimationFrame(() => {
        pendingReferenceUpdates.delete(node);
        let lastConnected = 0;
        for (const slot of node.inputs ?? []) {
            const match = REFERENCE_SLOT.exec(slot.name);
            if (match && slot.link != null) lastConnected = Math.max(lastConnected, Number(match[1]));
        }
        const spare = lastConnected + 1;
        for (let index = (node.inputs?.length ?? 0) - 1; index >= 0; index--) {
            const slot = node.inputs[index];
            const match = REFERENCE_SLOT.exec(slot.name);
            if (match && slot.link == null && Number(match[1]) > spare) node.removeInput(index);
        }
        updateCanvasOptions(node);
    }));
}

function alignedDimension(value) {
    const units = value / 16;
    const lower = Math.floor(units);
    const rounded = units - lower === 0.5 && lower % 2 === 0 ? lower : Math.round(units);
    return Math.max(16, rounded * 16);
}

function migrateCanvas(serialized, ratios) {
    const values = serialized.widgets_values ?? [];
    const named = serialized.widgets_values_named;
    const mode = named?.canvas ?? values[1];
    const follow = /^跟随图 ([12])$/u.exec(mode);
    const oldRatio = mode === "常用比例" || (mode === CUSTOM_RATIO && named?.["canvas.preset_ratio"] == null);
    if (!follow && !oldRatio) return serialized;

    const optionNames = follow ? ["canvas.long_edge"] : ["canvas.ratio", "canvas.long_edge"];
    const previousOrder = ["prompt", "canvas", ...optionNames, "appearance_max_edge", "reference_max_edge", NEGATIVE_PROMPT];
    const saved = {
        ...Object.fromEntries(previousOrder.slice(0, values.length).map((name, index) => [name, values[index]])),
        ...named,
    };
    let config;
    if (follow) {
        config = { canvas: `参考图 ${follow[1]} 的画幅`, "canvas.long_edge": saved["canvas.long_edge"] };
    } else {
        const ratio = saved["canvas.preset_ratio"] ?? saved["canvas.ratio"] ?? "16:9";
        const parsed = /^\s*([1-9]\d{0,4})\s*[:：/x×]\s*([1-9]\d{0,4})\s*$/u.exec(ratio);
        const equivalent = parsed ? `${parsed[1]}:${parsed[2]}` : "16:9";
        const requestedEdge = Number(saved["canvas.long_edge"]) || 3360;
        if (ratios.includes(equivalent) || !parsed) {
            config = {
                canvas: CUSTOM_RATIO, "canvas.preset_ratio": equivalent, "canvas.long_edge": requestedEdge,
            };
        } else {
            const width = Number(parsed[1]);
            const height = Number(parsed[2]);
            const scale = (Math.floor(requestedEdge / 16) * 16) / Math.max(width, height);
            config = {
                canvas: CUSTOM_SIZE,
                "canvas.width": alignedDimension(width * scale),
                "canvas.height": alignedDimension(height * scale),
            };
        }
    }
    const upgraded = {
        prompt: saved.prompt ?? "",
        ...config,
        appearance_max_edge: saved.appearance_max_edge ?? 2048,
        reference_max_edge: saved.reference_max_edge ?? 1536,
        [NEGATIVE_PROMPT]: saved[NEGATIVE_PROMPT] ?? "",
    };
    return { ...serialized, widgets_values: Object.values(upgraded), widgets_values_named: upgraded };
}

function placeNegativePrompt(node, besidePositive) {
    const widgets = node.widgets || [];
    const negativeIndex = widgets.findIndex((widget) => widget.name === NEGATIVE_PROMPT);
    const positive = widgets.find((widget) => widget.name === "prompt");
    if (negativeIndex < 0 || (besidePositive && !positive)) return;
    const [negative] = widgets.splice(negativeIndex, 1);
    const target = besidePositive ? widgets.indexOf(positive) + 1 : widgets.length;
    widgets.splice(target, 0, negative);
}

app.registerExtension({
    name: "LX.ImageEdit.Qwen21MultiImage",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const options = nodeData.input?.required?.canvas?.[1]?.options;
        canvasModes.set(nodeType, options?.map(({ key }) => key));
        const preset = options?.find((option) => option.key === CUSTOM_RATIO);
        const ratios = preset?.inputs?.required?.preset_ratio?.[1]?.options ?? [];

        // Comfy's DynamicCombo creates new sockets and widgets on each mode switch.
        const onInputAdded = nodeType.prototype.onInputAdded;
        nodeType.prototype.onInputAdded = function (slot, ...args) {
            const result = onInputAdded?.call(this, slot, ...args);
            const label = LABELS[slot.name];
            if (label) {
                slot.localized_name = label;
                const widget = this.widgets?.find((entry) => entry.name === slot.name);
                if (widget) widget.label = label;
            }
            return result;
        };

        const configure = nodeType.prototype.configure;
        nodeType.prototype.configure = function (serialized, ...args) {
            // Older workflows can restore widget values by position.
            placeNegativePrompt(this, false);
            try {
                const result = configure.call(this, migrateCanvas(serialized, ratios), ...args);
                const removed = this.inputs?.findIndex((slot) => slot.name === "frame_image") ?? -1;
                if (removed >= 0) this.removeInput(removed);
                return result;
            } finally {
                placeNegativePrompt(this, true);
                scheduleReferenceUpdate(this);
            }
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (...args) {
            const result = onConnectionsChange?.apply(this, args);
            scheduleReferenceUpdate(this);
            return result;
        };

        const serialize = nodeType.prototype.serialize;
        nodeType.prototype.serialize = function (...args) {
            const serialized = serialize.apply(this, args);
            const values = serialized.widgets_values;
            if (Array.isArray(values)) {
                const index = this.widgets?.filter((widget) => widget.serialize !== false)
                    .findIndex((widget) => widget.name === NEGATIVE_PROMPT) ?? -1;
                if (index >= 0 && index < values.length - 1) {
                    values.push(...values.splice(index, 1));
                }
            }
            return serialized;
        };
    },
    nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;
        placeNegativePrompt(node, true);
        scheduleReferenceUpdate(node);
    },
});
