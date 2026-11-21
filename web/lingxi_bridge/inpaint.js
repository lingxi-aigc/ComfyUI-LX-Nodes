import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LingxiBridgeInpaint";
const BOTTOM_SPACER_NAME = "__lx_lingxi_bridge_inpaint_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 5;

function ensureBottomSpacer(node) {
    node.widgets = node.widgets || [];
    let spacer = node.widgets.find((widget) => widget?.name === BOTTOM_SPACER_NAME);

    if (!spacer) {
        spacer = {
            name: BOTTOM_SPACER_NAME,
            type: "custom",
            value: "",
            serialize: false,
            options: { canvasOnly: true },
            computeSize: () => [0, BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.type = "custom";
        spacer.value = "";
        spacer.serialize = false;
        spacer.options = { ...(spacer.options || {}), canvasOnly: true };
        spacer.computeSize = () => [0, BOTTOM_SPACER_HEIGHT];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function refreshSize(node) {
    if (!node || typeof node.computeSize !== "function" || typeof node.setSize !== "function") return;
    ensureBottomSpacer(node);
    const size = node.computeSize();
    if (!Array.isArray(size)) return;
    node.setSize([
        Math.max(node.size?.[0] || 0, size[0]),
        Math.max(node.size?.[1] || 0, size[1]),
    ]);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function install(node) {
    ensureBottomSpacer(node);
    refreshSize(node);
    requestAnimationFrame(() => refreshSize(node));
    window.setTimeout(() => refreshSize(node), 150);
}

app.registerExtension({
    name: "LXRelay.LingxiBridge.Inpaint.BottomSpacer",

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
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            install(node);
        }
    },
});
