import { app } from "../../../../scripts/app.js";
import {
    GPT_IMAGE2_SIZES,
    IMAGE_RATIOS_BASE,
    IMAGE_RATIOS_BY_PLATFORM,
    getLinkedOriginNode,
    hideWidget,
    isWidgetHidden,
    showWidget,
} from "../lingxi_bridge/shared.js";

function linkedNode(node, inputName) {
    const input = node.inputs?.find((item) => item.name === inputName);
    return getLinkedOriginNode(node, input);
}

function platformFromNode(node) {
    if (!node) return null;
    const widget = node.widgets?.find((item) => item.name === "platform");
    return widget?.value || null;
}

function connectedPlatforms(node) {
    const platforms = [];
    const poolPlatform = platformFromNode(linkedNode(node, "api_pool"));
    if (poolPlatform) platforms.push(poolPlatform);
    return [...new Set(platforms)];
}

function refreshComboWidget(node, widgetName) {
    const widget = node.widgets?.find((item) => item.name === widgetName);
    const el = widget?.inputEl;
    if (!widget || !el || el.tagName !== "SELECT") return;
    const values = widget.options?.values || [];
    el.options.length = 0;
    for (const value of values) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = value;
        el.appendChild(opt);
    }
    el.value = widget.value;
    node.setDirtyCanvas(true, true);
}

function unionRatios(platforms) {
    if (!platforms.length) {
        const seen = new Set();
        const all = [];
        for (const ratios of Object.values(IMAGE_RATIOS_BY_PLATFORM)) {
            for (const ratio of ratios || IMAGE_RATIOS_BASE) {
                if (!seen.has(ratio)) {
                    seen.add(ratio);
                    all.push(ratio);
                }
            }
        }
        return all.length ? all : IMAGE_RATIOS_BASE;
    }
    const seen = new Set();
    const result = [];
    for (const platform of platforms) {
        const ratios = IMAGE_RATIOS_BY_PLATFORM[platform] || IMAGE_RATIOS_BASE;
        for (const ratio of ratios) {
            if (!seen.has(ratio)) {
                seen.add(ratio);
                result.push(ratio);
            }
        }
    }
    return result.length ? result : IMAGE_RATIOS_BASE;
}

function syncNode(node) {
    if (!node.widgets) return;
    const platforms = connectedPlatforms(node);
    const hasGptImage2 = platforms.length === 0 || platforms.some(platform => ["gpt-image2", "gpt-image2.5"].includes(platform));

    const ratio = node.widgets.find((item) => item.name === "ratio");
    if (ratio) {
        const values = unionRatios(platforms);
        ratio.options.values = values;
        if (!values.includes(ratio.value)) {
            ratio.value = values.includes("auto") ? "auto" : values[0];
        }
        refreshComboWidget(node, "ratio");
    }

    const size = node.widgets.find((item) => item.name === "size");
    if (size) {
        const values = hasGptImage2 ? GPT_IMAGE2_SIZES : ["1K", "2K", "4K"];
        size.options.values = values;
        if (!values.includes(size.value)) {
            size.value = "2K";
        }
        refreshComboWidget(node, "size");
    }

    for (const name of ["quality", "moderation"]) {
        const widget = node.widgets.find((item) => item.name === name);
        if (!widget) continue;
        if (hasGptImage2) {
            showWidget(widget);
        } else if (!isWidgetHidden(widget)) {
            hideWidget(widget);
        }
    }

    if (typeof node.computeSize === "function" && Array.isArray(node.size)) {
        requestAnimationFrame(() => {
            const [width, height] = node.computeSize();
            node.setSize([Math.max(node.size[0], width, 420), height]);
            node.setDirtyCanvas(true, true);
        });
    }
}

app.registerExtension({
    name: "LingxiBridge.Concurrent.Image",

    async nodeCreated(node) {
        if (node.comfyClass !== "LingxiBridgeConcurrentImage") return;
        await new Promise((resolve) => setTimeout(resolve, 100));
        syncNode(node);

        node._lxConcurrentLastKey = "";
        const intervalId = setInterval(() => {
            if (!node.widgets) {
                clearInterval(intervalId);
                return;
            }
            const platforms = connectedPlatforms(node).join("|");
            if (platforms !== node._lxConcurrentLastKey) {
                node._lxConcurrentLastKey = platforms;
                syncNode(node);
            }
        }, 250);

        node._lxConcurrentInterval = intervalId;
        const originalOnRemoved = node.onRemoved;
        node.onRemoved = function () {
            clearInterval(node._lxConcurrentInterval);
            if (originalOnRemoved) originalOnRemoved.call(this);
        };
    },
});
