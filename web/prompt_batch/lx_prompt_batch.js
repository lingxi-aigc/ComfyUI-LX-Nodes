import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

const DEFAULT_NODE_WIDTH = 270;
const MIN_NODE_HEIGHT = 220;
const PROGRESS_UI_KEY = "lx_prompt_progress_preview";
const PROGRESS_EVENT = "lx-prompt-batch-progress";
const PROGRESS_OUTPUT_INDEX = 5;
const STATS_OUTPUT_INDEX = 3;
let progressListenerInstalled = false;
const latestProgressByNode = new Map();

function hideInternalWidget(node, name) {
    const widget = (node.widgets || []).find((item) => item.name === name);
    if (!widget) return null;
    widget.type = "hidden";
    widget.hidden = true;
    widget.computeSize = () => [0, -4];
    widget.serializeValue = () => Number(widget.value || 0);
    return widget;
}

function bumpInternalWidget(node, name) {
    const widget = (node.widgets || []).find((item) => item.name === name);
    if (!widget) return 0;
    const nextValue = (Number(widget.value || 0) + 1) % 0x7fffffff;
    widget.value = nextValue;
    widget.callback?.(nextValue, app.canvas, node, app.canvas?.graph_mouse, {});
    return nextValue;
}

function resetIndexWidget(node) {
    const widget = (node.widgets || []).find((item) => item.name === "索引");
    if (!widget) return;
    widget.value = 0;
    widget.callback?.(0, app.canvas, node, app.canvas?.graph_mouse, {});
}

function normalizeNodeId(value) {
    return String(value ?? "").trim();
}

function findGraphNode(nodeId) {
    const targetId = normalizeNodeId(nodeId);
    if (!targetId) return null;
    const nodes = getGraphNodes(app.graph);
    return nodes.find((node) => normalizeNodeId(node?.id) === targetId) || null;
}

function getGraphNodes(graph) {
    if (Array.isArray(graph?._nodes)) return graph._nodes;
    if (Array.isArray(graph?.nodes)) return graph.nodes;
    if (graph?._nodes?.values) return [...graph._nodes.values()];
    if (graph?.nodes?.values) return [...graph.nodes.values()];
    return [];
}

function getGraphLink(graph, linkId) {
    if (!graph || linkId == null) return null;
    if (graph._links?.get) return graph._links.get(linkId);
    if (graph.links?.get) return graph.links.get(linkId);
    return graph._links?.[linkId] || graph.links?.[linkId] || null;
}

function getOutputTargets(node, outputIndex) {
    const targets = [];
    const seen = new Set();
    const output = node?.outputs?.[outputIndex];
    const linkIds = output?.links || [];
    for (const linkId of linkIds) {
        const link = getGraphLink(node?.graph, linkId);
        const targetId = Array.isArray(link)
            ? link[3]
            : (link?.target_id ?? link?.targetId);
        const target = targetId != null ? node?.graph?.getNodeById?.(targetId) : null;
        if (!target || seen.has(target.id)) continue;
        seen.add(target.id);
        targets.push(target);
    }

    // LiteGraph 0.10 and the Vue canvas use different link containers.
    // Matching the target input's link id keeps progress routing independent
    // of that internal representation.
    const expectedLinks = new Set(linkIds.map((linkId) => normalizeNodeId(linkId)));
    if (expectedLinks.size) {
        for (const target of getGraphNodes(node?.graph)) {
            if (!target || seen.has(target.id)) continue;
            const matched = (target.inputs || []).some((input) =>
                expectedLinks.has(normalizeNodeId(input?.link))
            );
            if (!matched) continue;
            seen.add(target.id);
            targets.push(target);
        }
    }
    return targets;
}

function getInputSource(node, inputIndex = 0) {
    const linkId = node?.inputs?.[inputIndex]?.link;
    const link = getGraphLink(node?.graph, linkId);
    const sourceId = Array.isArray(link)
        ? link[1]
        : (link?.origin_id ?? link?.originId);
    if (sourceId != null) {
        return node?.graph?.getNodeById?.(sourceId) || findGraphNode(sourceId);
    }

    const targetLinkId = normalizeNodeId(linkId);
    if (!targetLinkId) return null;
    return getGraphNodes(node?.graph).find((candidate) =>
        (candidate.outputs || []).some((output) =>
            (output?.links || []).some(
                (outputLinkId) => normalizeNodeId(outputLinkId) === targetLinkId
            )
        )
    ) || null;
}

function refreshNode(node) {
    node?.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function progressImageUrl(image) {
    return api.apiURL(
        `/view?filename=${encodeURIComponent(image?.filename || "")}` +
        `&type=${encodeURIComponent(image?.type || "temp")}` +
        `&subfolder=${encodeURIComponent(image?.subfolder || "")}` +
        (typeof app.getPreviewFormatParam === "function" ? app.getPreviewFormatParam() : "") +
        (typeof app.getRandParam === "function" ? app.getRandParam() : `&no-cache=${Date.now()}`)
    );
}

function applyImagesToPreviewNode(node, images) {
    if (!node) return;

    const descriptors = Array.isArray(images)
        ? images.filter((image) => image && typeof image === "object" && image.filename)
        : [];
    const loadVersion = Number(node.__lxPromptProgressLoadVersion || 0) + 1;
    node.__lxPromptProgressLoadVersion = loadVersion;

    if (!descriptors.length) {
        node.imgs = [];
        node.imageIndex = null;
        node.onResize?.(node.size);
        refreshNode(node);
        return;
    }

    const records = descriptors.map((descriptor) => {
        const image = new Image();
        const finish = () => {
            if (node.__lxPromptProgressLoadVersion === loadVersion) {
                refreshNode(node);
            }
        };
        image.onload = finish;
        image.onerror = finish;
        image.src = progressImageUrl(descriptor);
        return image;
    });

    // ComfyUI frontend >= 1.45 renders ordinary execution images from its
    // output store and no longer provides PreviewImage.onExecuted. Progress
    // cards intentionally use a private UI key so they stay out of generated
    // asset history; populate the legacy canvas preview directly instead.
    node.imgs = records;
    node.imageIndex = 0;
    node.onResize?.(node.size);
    refreshNode(node);
}

function isPreviewImageNode(node) {
    const text = `${node?.comfyClass || ""} ${node?.type || ""} ${node?.title || ""}`.toLowerCase();
    return text.includes("previewimage") || text.includes("preview image") || text.includes("预览图像");
}

function isTextDisplayNode(node) {
    const text = `${node?.comfyClass || ""} ${node?.type || ""} ${node?.title || ""}`.toLowerCase();
    return (
        text.includes("showtext")
        || text.includes("show text")
        || text.includes("show any")
        || text.includes("显示文本")
        || text.includes("展示文本")
    );
}

function updateProgressPreview(node, images) {
    if (!node) return;
    const payload = { images: Array.isArray(images) ? images : [] };
    for (const target of getOutputTargets(node, PROGRESS_OUTPUT_INDEX)) {
        if (!isPreviewImageNode(target)) continue;
        try {
            target.onExecuted?.(payload);
        } catch (error) {
            console.debug("[LX加载提示词] 刷新进度预览失败", error);
        }
        applyImagesToPreviewNode(target, payload.images);
    }
}

function updateStatsPreview(node, stats) {
    if (!node || !stats) return;
    for (const target of getOutputTargets(node, STATS_OUTPUT_INDEX)) {
        if (!isTextDisplayNode(target)) continue;
        try {
            target.onExecuted?.({ text: [String(stats)] });
        } catch (error) {
            console.debug("[LX加载提示词] 刷新数据统计失败", error);
        }
        refreshNode(target);
    }
}

function applyProgressPayload(payload) {
    const node = findGraphNode(payload?.node);
    if (!node) return;
    latestProgressByNode.set(normalizeNodeId(node.id), {
        images: Array.isArray(payload?.images) ? payload.images : [],
        stats: String(payload?.stats || ""),
        status: String(payload?.status || ""),
        updatedAt: performance.now(),
    });
    updateProgressPreview(node, payload?.images || []);
    updateStatsPreview(node, payload?.stats || "");
    refreshNode(node);
}

function handleExecutedOutput(event) {
    const detail = event?.detail || {};
    const output = detail.output || {};
    const progressImages = output?.[PROGRESS_UI_KEY];
    if (!Array.isArray(progressImages)) return;

    // New ComfyUI frontends keep execution output in a Vue store and may not
    // invoke the legacy node.onExecuted callback. Listen to the public
    // execution event as the authoritative path and paint the PreviewImage
    // node directly.
    const executedNode = findGraphNode(detail.node ?? detail.display_node);
    if (!executedNode) return;

    if (isPreviewImageNode(executedNode)) {
        const source = getInputSource(executedNode, 0);
        const latest = latestProgressByNode.get(normalizeNodeId(source?.id));
        const images = latest?.images?.length ? latest.images : progressImages;
        applyImagesToPreviewNode(executedNode, images);
        return;
    }

    if (normalizeNodeId(executedNode?.comfyClass || executedNode?.type) === "LXPromptBatch") {
        latestProgressByNode.set(normalizeNodeId(executedNode.id), {
            images: progressImages,
            stats: "",
            status: "processing",
            updatedAt: performance.now(),
        });
        updateProgressPreview(executedNode, progressImages);
    }
}

function installProgressListener() {
    if (progressListenerInstalled || !api?.addEventListener) return;
    progressListenerInstalled = true;
    api.addEventListener(PROGRESS_EVENT, (event) => {
        applyProgressPayload(event?.detail || {});
    });
    api.addEventListener("executed", handleExecutedOutput);
}

async function resetBackendCounter(node) {
    try {
        const response = await api.fetchApi("/lx/prompt_batch/reset", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ node_id: String(node?.id ?? "") }),
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return true;
    } catch (error) {
        console.warn("[LX加载提示词] 后端计数器重置失败，已使用版本重置兜底", error);
        return false;
    }
}

app.registerExtension({
    name: "LX.PromptBatch",

    setup() {
        installProgressListener();
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "PreviewImage") {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const progressImages = message?.[PROGRESS_UI_KEY];
                if (Array.isArray(progressImages) && !message?.images) {
                    const source = getInputSource(this, 0);
                    const latest = latestProgressByNode.get(normalizeNodeId(source?.id));
                    const images = latest?.images?.length ? latest.images : progressImages;
                    const result = onExecuted?.call(this, {
                        ...message,
                        images,
                    });
                    applyImagesToPreviewNode(this, images);
                    return result;
                }
                return onExecuted?.apply(this, arguments);
            };
            return;
        }

        if (nodeData.name !== "LXPromptBatch") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        const onExecuted = nodeType.prototype.onExecuted;

        nodeType.prototype.onExecuted = function (message) {
            const result = onExecuted?.apply(this, arguments);
            const progressImages = message?.[PROGRESS_UI_KEY];
            if (Array.isArray(progressImages)) {
                latestProgressByNode.set(normalizeNodeId(this.id), {
                    images: progressImages,
                    stats: "",
                    status: "processing",
                    updatedAt: performance.now(),
                });
                updateProgressPreview(this, progressImages);
            }
            return result;
        };

        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            hideInternalWidget(this, "重置版本");

            this.addWidget("button", "重置计数器", null, async () => {
                resetIndexWidget(this);
                bumpInternalWidget(this, "重置版本");
                latestProgressByNode.delete(normalizeNodeId(this.id));
                updateProgressPreview(this, []);
                this.setDirtyCanvas(true, true);
                await resetBackendCounter(this);
                console.log("[LX加载提示词] 计数器已重置，下次从第 1 条开始");
            }, { serialize: false });

            const compactSize = this.computeSize?.();
            if (compactSize) {
                this.setSize([
                    DEFAULT_NODE_WIDTH,
                    Math.max(MIN_NODE_HEIGHT, Number(compactSize[1] || 0)),
                ]);
            }
            return result;
        };
    },
});
