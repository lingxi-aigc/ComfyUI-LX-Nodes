import { app } from "../../../../scripts/app.js";

const CIRCLE_SHAPE = () => globalThis.LiteGraph?.CIRCLE_SHAPE ?? 3;
const GRID_SHAPE = () => globalThis.LiteGraph?.GRID_SHAPE ?? 6;

const SLOT_SHAPE_RULES = {
    LXImageCompare: ["图像A", "图像B", "图像_A", "图像_B"],
    LingxiBridgeImage: [/^image\d+$/],
    LingxiBridgeConcurrentImage: [/^image\d+$/],
    LXQwen3VLReverse: ["image2", "image3", "image4"],
    LXTextJoin: ["文本1", "文本2", "文本3", "文本4"],
    LingxiBridgeApiPoolMerge: [/^info\d+$/],
    LXMemoryRelease: ["触发"],
};

const OUTPUT_SLOT_SHAPE_RULES = {
    LXShowAny: [
        {
            names: ["输出"],
            shape: GRID_SHAPE,
        },
    ],
    LXShowText: [
        {
            names: ["字符串", "string"],
            shape: GRID_SHAPE,
        },
    ],
};

function matchesName(name, matcher) {
    if (matcher instanceof RegExp) return matcher.test(name);
    return name === matcher;
}

function shouldNormalizeInput(nodeType, inputName) {
    const rules = SLOT_SHAPE_RULES[nodeType];
    return Boolean(rules?.some((matcher) => matchesName(inputName, matcher)));
}

function shouldNormalizeOutput(rule, outputName) {
    return Boolean(rule.names?.some((matcher) => matchesName(outputName, matcher)));
}

function normalizeInputSlotShapes(node) {
    const nodeType = node?.comfyClass || node?.type;
    if (!nodeType || !Array.isArray(node.inputs)) return;

    let changed = false;
    for (const input of node.inputs) {
        if (!input?.name || !shouldNormalizeInput(nodeType, input.name)) continue;
        const shape = CIRCLE_SHAPE();
        if (input.shape !== shape) {
            input.shape = shape;
            changed = true;
        }
    }

    if (changed) {
        node.setDirtyCanvas?.(true, false);
        app.graph?.setDirtyCanvas(true, false);
    }
}

function normalizeOutputSlotShapes(node) {
    const nodeType = node?.comfyClass || node?.type;
    if (!nodeType || !Array.isArray(node.outputs)) return;

    const rules = OUTPUT_SLOT_SHAPE_RULES[nodeType];
    if (!rules?.length) return;

    let changed = false;
    for (const output of node.outputs) {
        if (!output?.name) continue;
        const rule = rules.find((candidate) => shouldNormalizeOutput(candidate, output.name));
        if (!rule) continue;
        const shape = rule.shape();
        if (output.shape !== shape) {
            output.shape = shape;
            changed = true;
        }
    }

    if (changed) {
        node.setDirtyCanvas?.(true, false);
        app.graph?.setDirtyCanvas(true, false);
    }
}

function normalizeSlotShapes(node) {
    normalizeInputSlotShapes(node);
    normalizeOutputSlotShapes(node);
}

function normalizeSoon(node) {
    normalizeSlotShapes(node);
    requestAnimationFrame(() => normalizeSlotShapes(node));
    setTimeout(() => normalizeSlotShapes(node), 120);
}

app.registerExtension({
    name: "LX.NormalizeInputSlotShapes",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!SLOT_SHAPE_RULES[nodeData.name] && !OUTPUT_SLOT_SHAPE_RULES[nodeData.name]) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            normalizeSoon(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            normalizeSoon(this);
            return result;
        };
    },

    async nodeCreated(node) {
        normalizeSoon(node);
    },
});
