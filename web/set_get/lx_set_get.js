/*
 * SPDX-License-Identifier: GPL-3.0-only
 * Adapted from ComfyUI-KJNodes setgetnodes.js (kijai and contributors),
 * originally based on diffus3/ComfyUI-extensions SetGet.
 * Modified for LX-Nodes: node identities, UI, graph traversal and integration.
 * See NOTICE and LICENSE.
 */
import { app } from "../../../../scripts/app.js";

const SET_NODE_TYPE = "LingxiSetPoint";
const GET_NODE_TYPE = "LingxiGetPoint";
const INPUT_NAME = "输入";
const OUTPUT_NAME = "输出";
const SET_TITLE = "设置点";
const GET_TITLE = "获取点";
const MENU_TITLE = "设置点/获取点";
const CATEGORY = "灵犀/实用工具";
const AUX_ID_FORMAT = /^[^/]+\/[^/]+$/;

const SETTINGS = {
    naming: "Lingxi.SetGet.naming",
    showLinks: "Lingxi.SetGet.showLinks",
    autoColor: "Lingxi.SetGet.autoColor",
    hideTitlePrefix: "Lingxi.SetGet.hideTitlePrefix",
    showInConnectionMenu: "Lingxi.SetGet.showInConnectionMenu",
    filterGetOptions: "Lingxi.SetGet.filterGetOptions",
    altMiddleClick: "Lingxi.SetGet.altMiddleClick",
};

const SETUP_DONE = Symbol("lingxiSetGetSetupDone");
const SAVED_WIDGET_VALUES = Symbol("lingxiSetGetSavedWidgetValues");
const pendingTypeRefresh = new WeakSet();

let forceShowAllLinks = false;
let setNameSourceMap = new Map();
let typeColorMap = null;
let lastRestoreSnapshot = null;

function settingValue(id, fallback) {
    try {
        const value = app.ui?.settings?.getSettingValue?.(id);
        return value ?? fallback;
    } catch {
        return fallback;
    }
}

function toast(severity, detail, life = 3000) {
    const summary = MENU_TITLE;
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary, detail, life });
    } else if (severity === "warn") {
        console.warn(`[${summary}] ${detail}`);
    } else {
        console.info(`[${summary}] ${detail}`);
    }
}

function getNodeLabel(node) {
    const title = node?.title || node?.type || "";
    const pos = node?.pos ? ` [${Math.round(node.pos[0])}, ${Math.round(node.pos[1])}]` : "";
    return `${title}${pos}`;
}

function warn(message, nodes) {
    const list = Array.isArray(nodes) ? nodes : nodes ? [nodes] : [];
    toast("warn", list.length ? `${message}：${list.map(getNodeLabel).join("，")}` : message, 5000);
}

function getShowLinksMode() {
    if (forceShowAllLinks) return "总是";
    return settingValue(SETTINGS.showLinks, "从不");
}

function getInputName(node) {
    return node?.widgets?.[0]?.value || "";
}

function setInputName(node, value) {
    if (node?.widgets?.[0]) node.widgets[0].value = value || "";
}

function prefixedTitle(prefix, name) {
    const hidePrefix = settingValue(SETTINGS.hideTitlePrefix, false);
    if (!name) return prefix;
    return hidePrefix ? String(name) : `${prefix}: ${name}`;
}

function initTypeColorMap() {
    if (typeColorMap) return typeColorMap;
    typeColorMap = {
        DEFAULT: LGraphCanvas.node_colors?.gray,
        MODEL: LGraphCanvas.node_colors?.blue,
        LATENT: LGraphCanvas.node_colors?.purple,
        VAE: LGraphCanvas.node_colors?.red,
        WANVAE: LGraphCanvas.node_colors?.red,
        CONDITIONING: LGraphCanvas.node_colors?.brown,
        IMAGE: LGraphCanvas.node_colors?.pale_blue,
        CLIP: LGraphCanvas.node_colors?.yellow,
        FLOAT: LGraphCanvas.node_colors?.green,
        MASK: { color: "#1c5715", bgcolor: "#1f401b" },
        INT: { color: "#1b4669", bgcolor: "#29699c" },
        CONTROL_NET: { color: "#156653", bgcolor: "#1c453b" },
        NOISE: { color: "#2e2e2e", bgcolor: "#242121" },
        GUIDER: { color: "#3c7878", bgcolor: "#1c453b" },
        SAMPLER: { color: "#614a4a", bgcolor: "#3b2c2c" },
        SIGMAS: { color: "#485248", bgcolor: "#272e27" },
    };
    return typeColorMap;
}

function setColorAndBgColor(node, type) {
    const colors = initTypeColorMap()[type] || LGraphCanvas.node_colors?.gray;
    if (!colors) return;
    node.color = colors.color;
    node.bgcolor = colors.bgcolor;
}

function autoColor(node, type) {
    if (!settingValue(SETTINGS.autoColor, true)) return;
    if (!type || type === "*") {
        node.color = null;
        node.bgcolor = null;
        return;
    }
    setColorAndBgColor(node, type);
}

function normalizeTypeList(type) {
    if (!type || type === "*") return ["*"];
    if (typeof type !== "string") return [type];
    const types = type.split(",").map((item) => item.trim()).filter(Boolean);
    return types.length ? types : ["*"];
}

function typeCompatible(sourceType, targetType) {
    const sourceTypes = normalizeTypeList(sourceType);
    const targetTypes = normalizeTypeList(targetType);
    if (sourceTypes.includes("*") || targetTypes.includes("*")) return true;
    return sourceTypes.some((source) => targetTypes.some((target) => (
        LiteGraph.isValidConnection?.(source, target)
        ?? (String(source).toLowerCase() === String(target).toLowerCase())
    )));
}

function getLink(graph, linkId) {
    if (linkId == null || !graph) return null;
    if (typeof graph.getLink === "function") return graph.getLink(linkId);
    if (graph._links instanceof Map) return graph._links.get(linkId) || null;
    return graph.links?.get?.(linkId) ?? graph._links?.[linkId] ?? graph.links?.[linkId] ?? null;
}

function getPhysicalInputLink(node, slot) {
    if (!node.graph) return null;
    if (typeof node.getInputLink === "function") return node.getInputLink(slot);
    return getLink(node.graph, node.inputs?.[slot]?.link);
}

function hasLegacySetterInput(node) {
    return node.inputs?.length === 2 && node.inputs[0]?.name === INPUT_NAME
        && node.inputs[1]?.name != null && node.inputs[1].name !== INPUT_NAME;
}

function getSetterInputLink(node, slot = 0) {
    return getPhysicalInputLink(node, slot) ?? (slot === 0 && hasLegacySetterInput(node)
        ? getPhysicalInputLink(node, 1) : null);
}

function getLinkedSourceSlot(graph, link) {
    if (!link) return null;
    const resolved = link.resolve?.(graph);
    return resolved?.subgraphInput ?? resolved?.output
        ?? graph.getNodeById(link.origin_id)?.outputs?.[link.origin_slot];
}

function getOutputTargetTypes(node) {
    if (!node.graph) return [];
    const types = [];
    for (const id of node.outputs?.[0]?.links || []) {
        const link = getLink(node.graph, id);
        if (!link) continue;
        const resolved = link.resolve?.(node.graph);
        const slot = resolved?.subgraphOutput ?? resolved?.input
            ?? node.graph.getNodeById(link.target_id)?.inputs?.[link.target_slot];
        if (slot && !normalizeTypeList(slot.type).includes("*")) types.push(slot.type);
    }
    return types;
}

function getOutputConnections(graph, output) {
    const result = [];
    for (const linkId of [...(output?.links || [])]) {
        const link = getLink(graph, linkId);
        if (!link) continue;
        result.push({ targetId: link.target_id, targetSlot: link.target_slot });
    }
    return result;
}

function findRootGraph(graph) {
    if (!graph) return null;
    return graph.rootGraph || graph.root_graph || graph;
}

function findSubgraphNodeFor(parentGraph, inner) {
    const targetGraph = inner?._nodes ? inner : inner?.graph;
    if (!parentGraph?._nodes || !targetGraph) return null;
    for (const node of parentGraph._nodes) {
        if (node.subgraph === targetGraph) return node;
    }
    return null;
}

function getDirectSubgraphs(graph) {
    const subgraphs = [];
    if (!graph?._nodes) return subgraphs;
    for (const node of graph._nodes) {
        if (node.subgraph) subgraphs.push(node.subgraph);
    }
    const known = graph._subgraphs || graph.subgraphs;
    if (known?.values) {
        for (const subgraph of known.values()) {
            if (subgraph && !subgraphs.includes(subgraph)) subgraphs.push(subgraph);
        }
    }
    return subgraphs;
}

function getGraphDescendants(graph, visited = new Set()) {
    if (!graph || visited.has(graph)) return [];
    visited.add(graph);
    const result = [];
    for (const subgraph of getDirectSubgraphs(graph)) {
        if (!subgraph || visited.has(subgraph)) continue;
        result.push(subgraph);
        result.push(...getGraphDescendants(subgraph, visited));
    }
    return result;
}

function getAllGraphs(graph) {
    const root = findRootGraph(graph);
    if (!root) return [];
    return [root, ...getGraphDescendants(root)];
}

function getGraphAncestors(graph) {
    if (!graph) return [];
    const root = findRootGraph(graph);
    if (!root || graph === root) return root ? [root] : [];

    const chain = [graph];
    const visited = new Set([graph]);
    let current = graph;
    while (current && current !== root) {
        let parent = null;
        for (const candidate of getAllGraphs(root)) {
            if (candidate === current || !candidate?._nodes) continue;
            if (candidate._nodes.some((node) => node.subgraph === current)) {
                parent = candidate;
                break;
            }
        }
        if (!parent || visited.has(parent)) break;
        chain.push(parent);
        visited.add(parent);
        current = parent;
    }
    if (!chain.includes(root)) chain.push(root);
    return chain;
}

function collectNodesOfType(graphs, type) {
    const result = [];
    for (const graph of graphs) {
        if (!graph?._nodes) continue;
        for (const node of graph._nodes) {
            if (node?.type === type) result.push({ node, graph });
        }
    }
    return result;
}

function findAllNodesOfType(graph, type) {
    return collectNodesOfType(getAllGraphs(graph), type);
}

function findSetterByName(graph, name, renamedSetter) {
    if (!name) return null;
    for (const scopeGraph of getGraphAncestors(graph)) {
        for (const node of scopeGraph?._nodes || []) {
            if (node.type === SET_NODE_TYPE && (node === renamedSetter || getInputName(node) === name)) {
                return { node, graph: scopeGraph };
            }
        }
    }
    return null;
}

function findGettersByName(graph, name) {
    if (!graph || !name) return [];
    return collectNodesOfType([graph, ...getGraphDescendants(graph)], GET_NODE_TYPE)
        .filter(({ node }) => getInputName(node) === name);
}

function getVisibleSetNames(graph, targetTypes) {
    const sourceMap = new Map();
    const seen = new Set();
    for (const entry of collectNodesOfType(getGraphAncestors(graph), SET_NODE_TYPE)) {
        const name = getInputName(entry.node);
        if (!name || seen.has(name)) continue;
        seen.add(name);
        const setType = entry.node.inputs?.[0]?.type || "*";
        if (targetTypes.some((target) => !typeCompatible(setType, target))) continue;
        sourceMap.set(name, entry.graph === graph ? "local" : "parent");
    }
    setNameSourceMap = sourceMap;
    return [...sourceMap.keys()].sort((a, b) => String(a).localeCompare(String(b), "zh-Hans-CN"));
}

function refreshAllGetPointCombos(graph) {
    for (const entry of findAllNodesOfType(graph, GET_NODE_TYPE)) {
        entry.node._refreshComboOptions?.();
    }
}

function queueSetGetTypeRefresh(graph) {
    const root = findRootGraph(graph);
    if (!root || pendingTypeRefresh.has(root)) return;
    pendingTypeRefresh.add(root);
    queueMicrotask(() => {
        pendingTypeRefresh.delete(root);
        const graphs = getAllGraphs(root);
        for (const { node } of collectNodesOfType(graphs, SET_NODE_TYPE)) {
            repairLegacySetterInput(node);
            refreshSetPointType(node);
        }
        for (const { node } of collectNodesOfType(graphs, GET_NODE_TYPE)) node.onRename?.();
    });
}

function graphChangeStart(graph) {
    const root = findRootGraph(graph) || graph;
    root?.beforeChange?.();
    return root;
}

function graphChangeEnd(graph) {
    const root = findRootGraph(graph) || graph;
    root?.afterChange?.();
    root?.change?.();
    app.canvas?.setDirty(true, true);
}

function snapshotGraph(label) {
    const graph = app.graph;
    if (!graph?.serialize) return;
    try {
        const data = graph.serialize();
        lastRestoreSnapshot = {
            label,
            createdAt: Date.now(),
            data: cloneSerializable(data),
        };
    } catch (error) {
        console.warn(`[${MENU_TITLE}] 保存临时快照失败`, error);
        lastRestoreSnapshot = null;
    }
}

async function restoreLastSnapshot() {
    if (!lastRestoreSnapshot?.data) {
        toast("warn", "没有可恢复的上一次还原记录", 3000);
        return;
    }
    const ok = confirm("将恢复到上一次“全部转为真实连线”之前的工作流。当前之后的修改会被覆盖，继续吗？");
    if (!ok) return;

    const data = cloneSerializable(lastRestoreSnapshot.data);
    try {
        if (typeof app.loadGraphData === "function") {
            await app.loadGraphData(data, true);
        } else if (app.graph?.configure) {
            app.graph.clear?.();
            app.graph.configure(data);
            app.canvas?.setDirty(true, true);
        } else {
            throw new Error("当前前端没有可用的工作流恢复接口");
        }
        lastRestoreSnapshot = null;
        toast("info", "已恢复上一次还原前的状态", 3000);
    } catch (error) {
        console.error(`[${MENU_TITLE}] 恢复快照失败`, error);
        toast("error", `恢复失败：${error.message || error}`, 5000);
    }
}

function createNode(type, graph, pos) {
    const node = LiteGraph.createNode(type);
    if (!node || !graph) return null;
    node.pos = pos ? [pos[0], pos[1]] : [0, 0];
    graph.add(node);
    return node;
}

function findBestOutputSlot(node) {
    const outputs = node?.outputs || [];
    if (!outputs.length) return -1;
    const linked = outputs.findIndex((output) => output?.links?.length);
    return linked >= 0 ? linked : 0;
}

function findBestInputSlot(node) {
    const inputs = node?.inputs || [];
    if (!inputs.length) return -1;
    const free = inputs.findIndex((input) => input?.link == null);
    return free >= 0 ? free : 0;
}

function addNodeNear(type, nextTo, options = {}) {
    const graph = nextTo?.graph || app.canvas?.graph || app.graph;
    if (!graph) return null;
    const side = options.side || "right";
    const offset = options.offset ?? 30;
    const node = createNode(type, graph);
    if (!node) return null;

    node.pos = [
        side === "left" ? nextTo.pos[0] - (node.size?.[0] || 200) - offset : nextTo.pos[0] + (nextTo.size?.[0] || 200) + offset,
        nextTo.pos[1] + (options.shiftY || 0),
    ];

    if (side === "left") {
        const inputSlot = findBestInputSlot(nextTo);
        if (inputSlot >= 0) node.connect(0, nextTo, inputSlot);
    } else {
        const outputSlot = findBestOutputSlot(nextTo);
        if (outputSlot >= 0) nextTo.connect(outputSlot, node, 0);
    }

    if (options.select !== false) app.canvas?.selectNode(node, false);
    app.canvas?.setDirty(true, true);
    return node;
}

function addNodeToSelectedOrCursor(type, side) {
    const selected = Object.values(app.canvas?.selected_nodes || {});
    if (selected.length) {
        for (const node of selected) addNodeNear(type, node, { side, offset: 30 });
        return;
    }
    const canvas = app.canvas;
    const graph = canvas?.graph || app.graph;
    if (!canvas || !graph) return;
    const pos = canvas.graph_mouse || [0, 0];
    const node = createNode(type, graph, pos);
    if (!node) return;
    canvas.selectNode(node, false);
    canvas.setDirty(true, true);
}

function snapshotSelectedNodes(node, typeFilter) {
    const selected = Object.values(app.canvas?.selected_nodes || {});
    const nodes = new Set(selected);
    if (node) nodes.add(node);
    const result = [...nodes];
    return typeFilter ? result.filter((item) => item?.type === typeFilter) : result;
}

function applyNameFromSource(node, type, slotName) {
    const current = getInputName(node);
    if (current && current !== "*") return false;
    const mode = settingValue(SETTINGS.naming, "空");
    if (mode === "空") return false;
    const base = slotName || type || "";
    if (!base) return false;
    if (mode === "插槽名小写") setInputName(node, String(base).toLowerCase());
    else if (mode === "插槽名大写") setInputName(node, String(base).toUpperCase());
    else setInputName(node, base);
    return true;
}

function setSlotDisplayType(slot, type) {
    if (!slot) return;
    slot.type = type;
    slot.label = type === "*" ? undefined : String(type);
}

function setSetPointType(node, type) {
    const slotType = type || "*";
    setSlotDisplayType(node.inputs?.[0], slotType);
    setSlotDisplayType(node.outputs?.[0], slotType);
    autoColor(node, slotType);
}

function refreshSetPointType(node) {
    const link = getSetterInputLink(node);
    const source = getLinkedSourceSlot(node.graph, link);
    // A restored link may exist before its source slot has been hydrated.
    if (link && !source) return null;
    let type = source?.type;
    if (normalizeTypeList(type).includes("*")) {
        const targets = getOutputTargetTypes(node);
        const possible = [...new Set(targets.flatMap(normalizeTypeList))];
        const common = possible.filter((candidate) => targets.every((target) => typeCompatible(candidate, target)));
        type = common.length > 1 ? common.join(",") : common[0] || "*";
    }
    setSetPointType(node, type);
    return source;
}

function onSetPointConnectionsChange(slotType, slot, isConnected) {
    if (app.configuringGraph || this.__lingxiSetGetConfiguring) return;
    if (slot !== 0 && !(slotType === LiteGraph.INPUT && slot === 1 && hasLegacySetterInput(this))) return;
    const source = refreshSetPointType(this);
    if (slotType === LiteGraph.INPUT && isConnected && source && applyNameFromSource(this, source.type, source.name)) {
        this.validateName?.(this.graph);
        this.title = getInputName(this) ? prefixedTitle(SET_TITLE, getInputName(this)) : SET_TITLE;
        this.properties.previousName = getInputName(this);
    }
    this.updateGetters?.();
    app.canvas?.setDirty(true, true);
}

function validateSetPointName(graph, sameGraphOnly = false) {
    let value = getInputName(this);
    if (!graph || !value) return false;

    const scopeGraphs = sameGraphOnly ? [graph] : getGraphAncestors(graph);
    const existing = new Set();
    for (const entry of collectNodesOfType(scopeGraphs, SET_NODE_TYPE)) {
        if (entry.node !== this) existing.add(getInputName(entry.node));
    }

    const original = value;
    const base = this._justAdded ? value.replace(/_\d+$/, "") : value;
    let index = 0;
    while (existing.has(value)) {
        value = `${base}_${index}`;
        index += 1;
    }
    setInputName(this, value);
    this.title = value ? prefixedTitle(SET_TITLE, value) : SET_TITLE;
    return value !== original;
}

function setPointUpdateGetters() {
    if (!this.graph) return;
    const name = getInputName(this);
    const previousName = this.properties?.previousName;
    if (name && previousName && previousName !== name) {
        for (const { node, graph } of findGettersByName(this.graph, previousName)) {
            if (findSetterByName(graph, previousName, this)?.node === this) node.setName?.(name);
        }
    }
    if (name) {
        for (const { node, graph } of findGettersByName(this.graph, name)) {
            if (findSetterByName(graph, name)?.node === this) node.setType?.(this.inputs?.[0]?.type || "*");
        }
    }
    refreshAllGetPointCombos(this.graph);
    app.canvas?.setDirty(true, true);
}

function setPointFindGetters(checkPreviousName = false) {
    const name = checkPreviousName ? this.properties?.previousName : getInputName(this);
    return findGettersByName(this.graph, name).map(({ node }) => node);
}

function addPairedGetPoint(setNode) {
    const graph = setNode.graph;
    const getNode = createNode(GET_NODE_TYPE, graph, [setNode.pos[0] + (setNode.size?.[0] || 200) + 30, setNode.pos[1]]);
    if (!getNode) return;
    setInputName(getNode, getInputName(setNode));
    getNode.onRename?.();
    app.canvas?.selectNode(getNode, false);
    app.canvas?.setDirty(true, true);
}

function setPointMenu(_, options) {
    options.unshift(
        {
            content: "添加配对获取点",
            callback: () => addPairedGetPoint(this),
        },
        {
            content: "转为真实连线",
            callback: () => convertSelectedSetGetToLinks(this),
        },
        {
            content: this.drawConnection ? "隐藏关联线" : "显示关联线",
            callback: () => {
                this.drawConnection = !this.drawConnection;
                const linkType = this.inputs?.[0]?.type;
                this.slotColor = app.canvas?.default_connection_color_byType?.[linkType] || "#FFF";
                app.canvas?.setDirty(true, true);
            },
        },
        {
            content: "隐藏全部关联线",
            callback: () => {
                for (const { node } of findAllNodesOfType(this.graph, SET_NODE_TYPE)) node.drawConnection = false;
                for (const { node } of findAllNodesOfType(this.graph, GET_NODE_TYPE)) node.drawConnection = false;
                app.canvas?.setDirty(true, true);
            },
        },
    );

    const getters = this.findGetters?.() || [];
    if (getters.length) {
        options.unshift({
            content: "关联获取点",
            has_submenu: true,
            submenu: {
                title: "获取点",
                options: getters.map((getter) => ({
                    content: `${getter.title || GET_TITLE} id: ${getter.id}`,
                    callback: () => goToNode(getter),
                })),
            },
        });
    }
}

function normalizeSetPointSlots(node) {
    // Keep the native slot objects, whose link accessors read the graph store.
    if (!node.inputs?.length) node.addInput(INPUT_NAME, "*");
    if (node.inputs?.length === 1) node.inputs[0].name = INPUT_NAME;
    normalizePointOutputSlot(node, node.inputs?.[0]?.type || "*");
}

function normalizePointOutputSlot(node, fallbackType = "*") {
    if (!node.outputs?.length) node.addOutput(OUTPUT_NAME, fallbackType);
    if (node.outputs?.length === 1) node.outputs[0].name = OUTPUT_NAME;
}

function repairLegacySetterInput(node) {
    if (!node.graph || !hasLegacySetterInput(node)) return;
    if (getPhysicalInputLink(node, 0) || !getPhysicalInputLink(node, 1)) return;
    for (const link of node.graph.floatingLinks?.values?.() || []) {
        if (link.target_id === node.id && link.target_slot === 0) return;
    }
    // Native removeInput shifts surviving link endpoints by slot identity.
    node.removeInput?.(0);
    if (node.inputs.length === 1) node.inputs[0].name = INPUT_NAME;
}

function normalizeSerializedSlotNames(node, kind) {
    if (!node) return;
    if (kind === "set" && node.inputs?.length === 1 && node.inputs[0]) node.inputs[0].name = INPUT_NAME;
    if (node.outputs?.length === 1 && node.outputs[0]) node.outputs[0].name = OUTPUT_NAME;
}

function readSerializedLinkTarget(link) {
    return Array.isArray(link)
        ? { id: link[0], node: link[3], slot: link[4] }
        : { id: link?.id, node: link?.target_id, slot: link?.target_slot };
}

function normalizeSetGetWorkflow(data) {
    if (!data) return;
    const legacyInputs = new Map();
    for (const node of Array.isArray(data.nodes) ? data.nodes : []) {
        const kind = setGetKind(node);
        if (!kind) continue;
        normalizeSerializedSlotNames(node, kind);
        if (kind === "set" && hasLegacySetterInput(node) && node.inputs[0].link == null && node.inputs[1].link != null) {
            legacyInputs.set(String(node.id), { node, links: [], floating: [] });
        }
    }
    if (legacyInputs.size) {
        for (const [links, key] of [[data.links, "links"], [data.floatingLinks, "floating"]]) {
            for (const link of Array.isArray(links) ? links : []) {
                const target = readSerializedLinkTarget(link);
                legacyInputs.get(String(target.node))?.[key].push({ link, ...target });
            }
        }
        for (const { node, links, floating } of legacyInputs.values()) {
            if (links.length !== 1 || floating.some(({ slot }) => slot === 0)) continue;
            const [inputLink] = links;
            if (String(inputLink.id) !== String(node.inputs[1].link) || ![0, 1].includes(inputLink.slot)) continue;
            node.inputs = [node.inputs[1]];
            normalizeSerializedSlotNames(node, "set");
            for (const { link, slot } of [inputLink, ...floating]) {
                if (slot !== 1) continue;
                if (Array.isArray(link)) link[4] = 0;
                else link.target_slot = 0;
            }
        }
    }
    const subgraphs = data.definitions?.subgraphs;
    if (Array.isArray(subgraphs)) for (const subgraph of subgraphs) normalizeSetGetWorkflow(subgraph);
}

function cloneSerializable(value) {
    if (value == null) return value;
    const seen = new WeakSet();
    return JSON.parse(JSON.stringify(value, (key, item) => {
        if (key === "_node") return undefined;
        if (typeof item === "function") return undefined;
        if (item && typeof item === "object") {
            if (seen.has(item)) return undefined;
            seen.add(item);
        }
        return item;
    }));
}

function clearInvalidAuxId(node) {
    const properties = node?.properties;
    if (!properties || !Object.prototype.hasOwnProperty.call(properties, "aux_id")) return;
    if (typeof properties.aux_id !== "string" || !AUX_ID_FORMAT.test(properties.aux_id)) {
        delete properties.aux_id;
    }
}

function setGetKind(node) {
    if (node?.type === SET_NODE_TYPE) return "set";
    if (node?.type === GET_NODE_TYPE) return "get";
    return null;
}

function patchClipboardTargetSlots() {
    const proto = LGraphCanvas.prototype;
    // Only supply link hints to native paste implementations which consume them.
    if (proto.__lingxiClipboardTargetSlots || !proto._serializeItems
        || !String(proto._deserializeItems).includes("recordClipboardTargetSlots")) return;
    proto.__lingxiClipboardTargetSlots = true;
    const serialize = proto._serializeItems;

    proto._serializeItems = function (items) {
        const selected = [...(items ?? this.selectedItems)];
        const data = serialize.call(this, selected);
        if (!Array.isArray(data?.links) || !Array.isArray(data.nodes)) return data;

        const originals = new Map(selected.filter((item) => item?.graph === this.graph && item.inputs)
            .map((node) => [String(node.id), node]));
        const copies = new Map(data.nodes.map((node) => [String(node.id), node]));
        for (const link of data.links) {
            const id = String(link.target_id);
            const originalInputs = originals.get(id)?.inputs;
            const input = originalInputs?.[link.target_slot];
            const copiedInputs = copies.get(id)?.inputs;
            if (!input?.name || input.link == null || String(input.link) !== String(link.id) || !copiedInputs) continue;
            if (originalInputs.filter((slot) => slot?.name === input.name).length !== 1) continue;

            // Clone/configure can reorder dynamic inputs. Keep the original ID on
            // the copied name so native paste can resolve the new target index.
            const matches = copiedInputs.filter((slot) => slot?.name === input.name);
            if (matches.length === 1 && matches[0].link == null) matches[0].link = link.id;
        }
        return data;
    };
}

function setupSetPointNode(node) {
    clearInvalidAuxId(node);
    const savedName = getInputName(node)
        || (Array.isArray(node[SAVED_WIDGET_VALUES]) ? node[SAVED_WIDGET_VALUES][0] : "")
        || "";
    normalizeSetPointSlots(node);
    if (node[SETUP_DONE]) {
        if (node.widgets?.[0] && savedName) node.widgets[0].value = savedName;
        node.title = getInputName(node) ? prefixedTitle(SET_TITLE, getInputName(node)) : SET_TITLE;
        return;
    }
    node[SETUP_DONE] = true;
    node.title = SET_TITLE;
    node.serialize_widgets = true;
    node.drawConnection = false;
    node.slotColor = "#FFF";
    node.isVirtualNode = true;
    node.properties = {
        ...(node.properties || {}),
        previousName: node.properties?.previousName || "",
        "Node name for S&R": SET_NODE_TYPE,
    };
    node.widgets = [];
    node.addWidget("text", "名称", "", () => {
        if (!node.graph || app.configuringGraph) return;
        node.validateName?.(node.graph);
        node.title = getInputName(node) ? prefixedTitle(SET_TITLE, getInputName(node)) : SET_TITLE;
        node.updateGetters?.();
        node.properties.previousName = getInputName(node);
    }, {});
    setInputName(node, savedName);
    node.size = node.computeSize?.() || node.size;
}

const setPointMethods = {
    onConnectionsChange: onSetPointConnectionsChange,
    validateName: validateSetPointName,
    updateGetters: setPointUpdateGetters,
    findGetters: setPointFindGetters,
    getExtraMenuOptions: setPointMenu,
    onAdded() {
        this._justAdded = true;
        if (LiteGraph.vueNodesMode && this.graph && !app.configuringGraph) {
            refreshAllGetPointCombos(this.graph);
        }
    },
    onRemoved() {
        const graph = this.graph;
        if (graph) setTimeout(() => refreshAllGetPointCombos(graph), 0);
    },
    onConfigure() {
        if (Array.isArray(this[SAVED_WIDGET_VALUES]) && this.widgets?.[0]) {
            this.widgets[0].value = this[SAVED_WIDGET_VALUES][0] || this.widgets[0].value || "";
        }
        if (app.configuringGraph || hasLegacySetterInput(this)) {
            queueSetGetTypeRefresh(this.graph);
        } else if (this._justAdded && this.graph) {
            this.validateName?.(this.graph, true);
            this.properties.previousName = getInputName(this);
            refreshSetPointType(this);
        }
        this._justAdded = false;
        this.title = getInputName(this) ? prefixedTitle(SET_TITLE, getInputName(this)) : SET_TITLE;
    },
};

function getFilterTypesForGetPoint(node) {
    return settingValue(SETTINGS.filterGetOptions, true) ? getOutputTargetTypes(node) : [];
}

function getSetPointOptionColor(graph, name, canvas) {
    const setter = findSetterByName(graph, name);
    const type = setter?.node?.inputs?.[0]?.type;
    const mapped = initTypeColorMap()[type];
    return canvas?.default_connection_color_byType?.[type]
        || LGraphCanvas.link_type_colors?.[type]
        || mapped?.groupcolor
        || mapped?.bgcolor
        || mapped?.color
        || "#888";
}

function setupGetCombo(node) {
    const comboOptions = {
        getOptionLabel: (value) => {
            if (!value) return "";
            const source = setNameSourceMap.get(value);
            return !source || source === "local" ? value : `${value} (${source})`;
        },
    };
    Object.defineProperty(comboOptions, "values", {
        get: () => (node.graph ? getVisibleSetNames(node.graph, getFilterTypesForGetPoint(node)) : []),
        enumerable: true,
        configurable: true,
    });
    const widget = node.addWidget("combo", "名称", "", () => {
        if (!app.configuringGraph) node.onRename?.();
    }, comboOptions);
    const originalOnClick = widget.onClick?.bind(widget);
    widget.onClick = (params) => {
        const { e, canvas, node: ownerNode } = params || {};
        if (!e || !canvas || !ownerNode) return originalOnClick?.(params);
        const x = e.canvasX - ownerNode.pos[0];
        const width = widget.width || ownerNode.size?.[0] || 160;
        if (x < 40) return widget.decrementValue?.({ e, node: ownerNode, canvas });
        if (x > width - 40) return widget.incrementValue?.({ e, node: ownerNode, canvas });

        const rawValues = comboOptions.values || [];
        const labels = rawValues.map((value) => comboOptions.getOptionLabel(value) || value);
        const menu = new LiteGraph.ContextMenu(labels, {
            scale: Math.max(1, canvas.ds?.scale || 1),
            event: e,
            className: "dark",
            callback: (selectedLabel) => {
                const index = labels.indexOf(selectedLabel);
                if (index < 0) return;
                if (typeof widget.setValue === "function") {
                    widget.setValue(rawValues[index], { e, node: ownerNode, canvas });
                } else {
                    widget.value = rawValues[index];
                    ownerNode.onRename?.();
                }
            },
        });

        const entries = menu.root?.querySelectorAll(".litemenu-entry");
        rawValues.forEach((name, index) => {
            if (!entries?.[index]) return;
            entries[index].style.borderLeft = `4px solid ${getSetPointOptionColor(ownerNode.graph, name, canvas)}`;
            entries[index].style.paddingLeft = "8px";
        });
        return menu;
    };
    node._refreshComboOptions = () => {
        if (!widget) return;
        const options = { getOptionLabel: comboOptions.getOptionLabel };
        Object.defineProperty(options, "values", Object.getOwnPropertyDescriptor(comboOptions, "values"));
        widget.options = options;
        const index = node.widgets?.indexOf(widget) ?? -1;
        if (index >= 0) {
            node.widgets.splice(index, 1);
            node.widgets.splice(index, 0, widget);
        }
    };
}

function getPointSetType(type) {
    const slotType = type || "*";
    setSlotDisplayType(this.outputs?.[0], slotType);
    autoColor(this, slotType);
}

function getPointSetName(name) {
    setInputName(this, name);
    this.onRename?.();
    this.serialize?.();
}

function getPointFindSetter(graph) {
    const result = findSetterByName(graph || this.graph, getInputName(this));
    return result?.node;
}

function getPointOnRename() {
    const setter = this.findSetter?.(this.graph);
    const name = getInputName(this);
    if (setter) {
        this.setType?.(setter.inputs?.[0]?.type || "*");
        this.title = prefixedTitle(GET_TITLE, getInputName(setter));
    } else {
        this.setType?.("*");
        this.title = name ? prefixedTitle(GET_TITLE, name) : GET_TITLE;
    }
    app.canvas?.setDirty(true, true);
}

function goToNode(node) {
    const canvas = app.canvas;
    if (!canvas || !node) return;
    if (node.graph && node.graph !== canvas.graph) {
        canvas.setGraph?.(node.graph);
        setTimeout(() => {
            canvas.centerOnNode?.(node);
            canvas.selectNode?.(node, false);
            canvas.setDirty?.(true, true);
        }, 0);
    } else {
        canvas.centerOnNode?.(node);
        canvas.selectNode?.(node, false);
        canvas.setDirty?.(true, true);
    }
}

function getPointGoToSetter() {
    this.currentSetter = this.findSetter?.(this.graph);
    if (this.currentSetter) goToNode(this.currentSetter);
}

function getPointInputLink(slot) {
    const name = getInputName(this);
    if (!name || !this.graph) return null;
    const localSetter = this.graph._nodes?.find((node) => node.type === SET_NODE_TYPE && getInputName(node) === name);
    if (localSetter) {
        return getSetterInputLink(localSetter, slot);
    }
    if (!findSetterByName(this.graph, name)) {
        warn(`没有找到名称为“${name}”的设置点`, this);
    }
    return null;
}

function getPointResolveVirtualOutput(slot) {
    const result = findSetterByName(this.graph, getInputName(this));
    if (!result || result.graph === this.graph) return undefined;

    const duplicates = collectNodesOfType(getGraphAncestors(this.graph), SET_NODE_TYPE)
        .filter(({ node }) => getInputName(node) === getInputName(this));
    if (duplicates.length > 1) {
        warn(`作用域内存在多个同名设置点“${getInputName(this)}”，请改名或转为真实连线`, [this, ...duplicates.map(({ node }) => node)]);
        return undefined;
    }

    const link = getSetterInputLink(result.node, slot);
    if (!link) return undefined;
    const sourceNode = result.graph.getNodeById(link.origin_id);
    if (!sourceNode) return undefined;
    return { node: sourceNode, slot: link.origin_slot };
}

function getPointMenu(_, options) {
    this.currentSetter = this.findSetter?.(this.graph);
    if (!this.currentSetter) return;
    options.unshift(
        {
            content: "转为真实连线",
            callback: () => convertSelectedSetGetToLinks(this),
        },
        {
            content: "跳转到设置点",
            callback: () => this.goToSetter?.(),
        },
        {
            content: this.drawConnection ? "隐藏关联线" : "显示关联线",
            callback: () => {
                if (!this.currentSetter) return;
                this.currentSetter.drawConnection = !this.currentSetter.drawConnection;
                this.drawConnection = this.currentSetter.drawConnection;
                app.canvas?.setDirty(true, true);
            },
        },
    );
}

function setupGetPointNode(node) {
    clearInvalidAuxId(node);
    const savedName = getInputName(node)
        || (Array.isArray(node[SAVED_WIDGET_VALUES]) ? node[SAVED_WIDGET_VALUES][0] : "")
        || "";
    normalizePointOutputSlot(node);
    if (node[SETUP_DONE]) {
        if (node.widgets?.[0] && savedName) node.widgets[0].value = savedName;
        node.title = getInputName(node) ? prefixedTitle(GET_TITLE, getInputName(node)) : GET_TITLE;
        return;
    }
    node[SETUP_DONE] = true;
    node.title = GET_TITLE;
    node.serialize_widgets = true;
    node.drawConnection = false;
    node.currentSetter = null;
    node.isVirtualNode = true;
    node.properties = {
        ...(node.properties || {}),
        "Node name for S&R": GET_NODE_TYPE,
    };
    node.widgets = [];
    setupGetCombo(node);
    setInputName(node, savedName);
    node.size = node.computeSize?.() || node.size;
}

const getPointMethods = {
    setType: getPointSetType,
    setName: getPointSetName,
    findSetter: getPointFindSetter,
    onRename: getPointOnRename,
    goToSetter: getPointGoToSetter,
    getInputLink: getPointInputLink,
    resolveVirtualOutput: getPointResolveVirtualOutput,
    getExtraMenuOptions: getPointMenu,
    onAdded() {
        this._justAdded = true;
    },
    onConfigure() {
        if (Array.isArray(this[SAVED_WIDGET_VALUES]) && this.widgets?.[0]) {
            this.widgets[0].value = this[SAVED_WIDGET_VALUES][0] || this.widgets[0].value || "";
        }
        if (this.graph && (app.configuringGraph || this._justAdded)) {
            queueSetGetTypeRefresh(this.graph);
        } else {
            this.onRename?.();
        }
        this._justAdded = false;
    },
};

function clipboardPointName(node) {
    const name = node?.widgets_values?.[0] ?? node?.widgets_values_named?.["名称"];
    return typeof name === "string" ? name : "";
}

function renameClipboardPoint(node, name) {
    const widgets = Array.isArray(node.widgets_values) ? [...node.widgets_values] : [];
    widgets[0] = name;
    const renamed = { ...node, widgets_values: widgets };
    if (node.widgets_values_named) renamed.widgets_values_named = { ...node.widgets_values_named, "名称": name };
    if (node.type === SET_NODE_TYPE) renamed.properties = { ...node.properties, previousName: name };
    return renamed;
}

function renameClipboardGetter(node, names) {
    if (node?.type !== GET_NODE_TYPE) return node;
    const name = names.get(clipboardPointName(node));
    return name ? renameClipboardPoint(node, name) : node;
}

function renameNestedClipboardGetters(definitions, nodes, rootNames) {
    if (!Array.isArray(definitions) || !definitions.length || !rootNames.size) return definitions;
    const byId = new Map(definitions.map((definition) => [definition.id, definition]));
    const inheritedByGraph = new Map();
    const queue = [{ nodes, inherited: rootNames }];
    for (let index = 0; index < queue.length; index += 1) {
        const { nodes, inherited } = queue[index];
        for (const node of nodes) {
            const definition = byId.get(node?.type);
            if (!Array.isArray(definition?.nodes)) continue;
            const localNames = new Set(definition.nodes.filter((node) => node?.type === SET_NODE_TYPE).map(clipboardPointName));
            const previous = inheritedByGraph.get(definition);
            // Shared definitions can be reached through different ancestor scopes.
            const safe = new Map([...(previous || inherited)].filter(([name]) => inherited.has(name) && !localNames.has(name)));
            if (previous && safe.size === previous.size) continue;
            inheritedByGraph.set(definition, safe);
            queue.push({ nodes: definition.nodes, inherited: safe });
        }
    }
    return definitions.map((definition) => {
        const inherited = inheritedByGraph.get(definition);
        if (!inherited?.size) return definition;
        return { ...definition, nodes: definition.nodes.map((node) => renameClipboardGetter(node, inherited)) };
    });
}

function prepareSetGetPaste(items, graph) {
    if (!graph || !Array.isArray(items?.nodes)) return items;
    const setters = items.nodes.filter((node) => node?.type === SET_NODE_TYPE && clipboardPointName(node));
    if (!setters.length) return items;
    const occupied = new Set((graph._nodes || []).filter((node) => node.type === SET_NODE_TYPE).map(getInputName));
    const reserved = new Set([...occupied, ...setters.map(clipboardPointName)]);
    // A generated root name must stay visible inside its copied subgraphs.
    for (const definition of Array.isArray(items.subgraphs) ? items.subgraphs : []) {
        for (const node of Array.isArray(definition?.nodes) ? definition.nodes : []) {
            if (node?.type === SET_NODE_TYPE) reserved.add(clipboardPointName(node));
        }
    }
    const setterChanges = new Map();
    const getterChanges = new Map();
    for (const node of setters) {
        const name = clipboardPointName(node);
        let renamed = name;
        if (occupied.has(name)) {
            const base = name.replace(/_\d+$/, "");
            let index = 0;
            do {
                renamed = `${base}_${index}`;
                index += 1;
            } while (reserved.has(renamed));
            reserved.add(renamed);
            setterChanges.set(node, renamed);
        }
        occupied.add(renamed);
        // A name that belonged to multiple copied setters is ambiguous.
        getterChanges.set(name, getterChanges.has(name) ? null : renamed);
    }
    if (!setterChanges.size) return items;
    const renamedBindings = new Map([...getterChanges].filter(([name, renamed]) => renamed && renamed !== name));
    const subgraphs = renameNestedClipboardGetters(items.subgraphs, items.nodes, renamedBindings);
    return {
        ...items,
        nodes: items.nodes.map((node) => {
            const name = setterChanges.get(node);
            return name ? renameClipboardPoint(node, name) : renameClipboardGetter(node, renamedBindings);
        }),
        ...(subgraphs === items.subgraphs ? {} : { subgraphs }),
    };
}

function patchSetGetPastePairing() {
    const proto = LGraphCanvas.prototype;
    const deserialize = proto._deserializeItems;
    if (typeof deserialize !== "function" || proto.__lingxiSetGetPastePairing) return;
    proto.__lingxiSetGetPastePairing = true;
    proto._deserializeItems = function (items, ...args) {
        return deserialize.call(this, prepareSetGetPaste(items, this.graph), ...args);
    };
}

function patchNodeType(nodeType, kind) {
    const proto = nodeType.prototype;
    if (proto.__lingxiSetGetPatched) return;
    proto.__lingxiSetGetPatched = true;
    const methods = kind === "set" ? setPointMethods : getPointMethods;
    nodeType.category = CATEGORY;
    nodeType.title = kind === "set" ? SET_TITLE : GET_TITLE;
    nodeType.prototype.serialize_widgets = true;

    const originalOnNodeCreated = proto.onNodeCreated;
    const originalConfigure = proto.configure;
    const originalOnConfigure = proto.onConfigure;
    const originalOnSerialize = proto.onSerialize;
    Object.assign(proto, methods);

    proto.onNodeCreated = function () {
        const result = originalOnNodeCreated?.apply(this, arguments);
        if (kind === "set") setupSetPointNode(this);
        else setupGetPointNode(this);
        return result;
    };

    proto.configure = function (info) {
        normalizeSerializedSlotNames(info, kind);
        if (Array.isArray(info?.widgets_values)) this[SAVED_WIDGET_VALUES] = [...info.widgets_values];
        this.__lingxiSetGetConfiguring = true;
        let result;
        try {
            result = originalConfigure?.apply(this, arguments);
        } finally {
            this.__lingxiSetGetConfiguring = false;
        }
        if (kind === "set") setupSetPointNode(this);
        else setupGetPointNode(this);
        methods.onConfigure?.call(this);
        return result;
    };

    proto.onConfigure = function () {
        const result = originalOnConfigure?.apply(this, arguments);
        if (!this.__lingxiSetGetConfiguring) methods.onConfigure?.call(this);
        return result;
    };

    proto.onSerialize = function (data) {
        const result = originalOnSerialize?.apply(this, arguments);
        clearInvalidAuxId(data);
        return result;
    };
}

function removeNodeIfPresent(graph, node) {
    if (graph?._nodes?.includes(node)) graph.remove(node);
}

function removeDanglingSetAndGet(graph, setNode) {
    const name = getInputName(setNode);
    for (const getter of findGettersByName(graph, name).filter(({ graph: g }) => g === graph).map(({ node }) => node)) {
        removeNodeIfPresent(graph, getter);
    }
    removeNodeIfPresent(graph, setNode);
}

function convertCrossGraphSetGet(setNode, setGraph, crossGraphGetters) {
    const input = setNode.inputs?.[0];
    const sourceLink = input?.link == null ? null : getLink(setGraph, input.link);
    if (!sourceLink) return 0;
    const sourceNode = setGraph.getNodeById(sourceLink.origin_id);
    if (!sourceNode) return 0;

    let converted = 0;
    const sourceSlot = sourceLink.origin_slot;
    const linkType = input.type || "*";
    const rootGraph = findRootGraph(setGraph);
    const setSubgraphNode = findSubgraphNodeFor(rootGraph, setNode);

    for (const { node: getter, graph: getterGraph } of crossGraphGetters) {
        const connections = getOutputConnections(getterGraph, getter.outputs?.[0]);
        if (!connections.length) {
            removeNodeIfPresent(getterGraph, getter);
            converted += 1;
            continue;
        }

        const getterSubgraphNode = findSubgraphNodeFor(rootGraph, getter);
        try {
            if (getterSubgraphNode && setGraph === rootGraph && getterSubgraphNode.subgraph?.addInput) {
                const subgraph = getterSubgraphNode.subgraph;
                const newInput = subgraph.addInput(getInputName(setNode) || linkType, linkType);
                const inputIndex = subgraph.inputs.indexOf(newInput);
                sourceNode.connect(sourceSlot, getterSubgraphNode, inputIndex);

                for (const conn of connections) {
                    const targetNode = getterGraph.getNodeById(conn.targetId);
                    if (!targetNode) continue;
                    if (conn.targetId === subgraph.outputNode?.id) {
                        const parentOutput = getterSubgraphNode.outputs?.[conn.targetSlot];
                        for (const parentLinkId of [...(parentOutput?.links || [])]) {
                            const parentLink = getLink(rootGraph, parentLinkId);
                            const parentTarget = parentLink ? rootGraph.getNodeById(parentLink.target_id) : null;
                            if (parentTarget) sourceNode.connect(sourceSlot, parentTarget, parentLink.target_slot);
                        }
                        const subgraphOutput = subgraph.outputs?.[conn.targetSlot];
                        if (subgraphOutput && subgraph.removeOutput) subgraph.removeOutput(subgraphOutput);
                    } else if (newInput?.connect && targetNode.inputs?.[conn.targetSlot]) {
                        newInput.connect(targetNode.inputs[conn.targetSlot], targetNode);
                    }
                }
                if (newInput?.linkIds?.length === 0 && subgraph.removeInput) subgraph.removeInput(newInput);
                removeNodeIfPresent(getterGraph, getter);
                converted += 1;
            } else if (setSubgraphNode && getterGraph === rootGraph && setSubgraphNode.subgraph?.addOutput) {
                const subgraph = setSubgraphNode.subgraph;
                const newOutput = subgraph.addOutput(getInputName(setNode) || linkType, linkType);
                const outputIndex = subgraph.outputs.indexOf(newOutput);
                if (newOutput?.connect && sourceNode.outputs?.[sourceSlot]) {
                    newOutput.connect(sourceNode.outputs[sourceSlot], sourceNode);
                }
                for (const conn of connections) {
                    const targetNode = getterGraph.getNodeById(conn.targetId);
                    if (targetNode) setSubgraphNode.connect(outputIndex, targetNode, conn.targetSlot);
                }
                removeNodeIfPresent(getterGraph, getter);
                converted += 1;
            } else {
                console.warn(`[${MENU_TITLE}] 暂不支持在两个兄弟子图之间自动还原“${getInputName(setNode)}”`);
            }
        } catch (error) {
            console.warn(`[${MENU_TITLE}] 跨子图还原失败`, error);
        }
    }

    const sameGraphLeft = (setGraph._nodes || []).some(
        (node) => node.type === GET_NODE_TYPE && getInputName(node) === getInputName(setNode),
    );
    if (!sameGraphLeft) removeNodeIfPresent(setGraph, setNode);
    return converted;
}

function convertSetGetToLinks(graph, setNode, options = {}) {
    if (!graph || !setNode) return 0;
    const name = getInputName(setNode);
    const getters = name ? findGettersByName(graph, name) : [];
    const sameGraphGetters = getters.filter(({ graph: g }) => g === graph).map(({ node }) => node);
    const crossGraphGetters = getters.filter(({ graph: g }) => g !== graph);

    let converted = 0;
    if (crossGraphGetters.length) converted += convertCrossGraphSetGet(setNode, graph, crossGraphGetters);
    if (!graph._nodes?.includes(setNode)) return converted;

    const input = setNode.inputs?.[0];
    const sourceLink = input?.link == null ? null : getLink(graph, input.link);
    if (!sourceLink) {
        if (options.removeDangling) {
            removeDanglingSetAndGet(graph, setNode);
            return converted;
        }
        warn("这个设置点没有输入，无法还原为真实连线", setNode);
        return converted;
    }

    const sourceNode = graph.getNodeById(sourceLink.origin_id);
    if (!sourceNode) return converted;
    const sourceSlot = sourceLink.origin_slot;

    const connections = [];
    for (const getter of sameGraphGetters) {
        connections.push(...getOutputConnections(graph, getter.outputs?.[0]));
    }
    connections.push(...getOutputConnections(graph, setNode.outputs?.[0]));

    for (const getter of sameGraphGetters) removeNodeIfPresent(graph, getter);
    removeNodeIfPresent(graph, setNode);

    for (const conn of connections) {
        const targetNode = graph.getNodeById(conn.targetId);
        if (targetNode) {
            sourceNode.connect(sourceSlot, targetNode, conn.targetSlot);
            converted += 1;
        }
    }
    return converted;
}

function convertSelectedSetGetToLinks(contextNode) {
    const graph = contextNode?.graph || app.canvas?.graph || app.graph;
    if (!graph) return;
    const changedGraph = graphChangeStart(graph);
    let count = 0;
    try {
        const selected = snapshotSelectedNodes(contextNode);
        const setNodes = selected.filter((node) => node.type === SET_NODE_TYPE);
        const getterNodes = selected.filter((node) => node.type === GET_NODE_TYPE);
        for (const setNode of setNodes) count += convertSetGetToLinks(setNode.graph || graph, setNode);
        const setters = new Set(getterNodes.map((node) => findSetterByName(node.graph, getInputName(node))?.node).filter(Boolean));
        for (const setNode of setters) count += convertSetGetToLinks(setNode.graph || graph, setNode);
    } finally {
        graphChangeEnd(changedGraph);
    }
    if (count) toast("info", `已转为真实连线：${count} 条`, 2500);
}

function convertAllSetGetToLinks(graph, options = {}) {
    const root = findRootGraph(graph || app.graph);
    if (!root) return;
    if (options.snapshot !== false) snapshotGraph("全部转为真实连线");
    const changedGraph = graphChangeStart(root);
    let count = 0;
    try {
        for (const { node: setNode, graph: setGraph } of [...findAllNodesOfType(root, SET_NODE_TYPE)]) {
            if (!setGraph._nodes?.includes(setNode)) continue;
            const name = getInputName(setNode);
            const cross = findGettersByName(root, name).filter(({ graph: g }) => g !== setGraph);
            if (cross.length) count += convertCrossGraphSetGet(setNode, setGraph, cross);
        }
        for (const { node: setNode, graph: setGraph } of [...findAllNodesOfType(root, SET_NODE_TYPE)]) {
            if (setGraph._nodes?.includes(setNode)) {
                count += convertSetGetToLinks(setGraph, setNode, { removeDangling: true });
            }
        }
        for (const { node, graph: getterGraph } of [...findAllNodesOfType(root, GET_NODE_TYPE)]) {
            removeNodeIfPresent(getterGraph, node);
        }
    } finally {
        graphChangeEnd(changedGraph);
    }
    toast("info", count ? `已还原真实连线：${count} 条` : "已清理设置点/获取点", 3000);
}

function convertOutputsToSetGet(graph, node) {
    if (!graph || !node?.outputs?.length) return;
    const changedGraph = graphChangeStart(graph);
    let created = 0;
    try {
        for (let slotIndex = 0; slotIndex < node.outputs.length; slotIndex += 1) {
            const output = node.outputs[slotIndex];
            if (!output?.links?.length) continue;
            const targets = [];
            const removeLinks = [];
            for (const linkId of [...output.links]) {
                const link = getLink(graph, linkId);
                const targetNode = link ? graph.getNodeById(link.target_id) : null;
                if (!targetNode || targetNode.type === SET_NODE_TYPE || targetNode.type === GET_NODE_TYPE) continue;
                targets.push({ targetId: link.target_id, targetSlot: link.target_slot });
                removeLinks.push(linkId);
            }
            if (!targets.length) continue;

            const linkType = output.type || "*";
            const linkName = output.name || linkType;
            const setNode = createNode(SET_NODE_TYPE, graph, [
                node.pos[0] + (node.size?.[0] || 200) + 30,
                node.pos[1] + slotIndex * 60,
            ]);
            if (!setNode) continue;
            setNode.flags = { ...(setNode.flags || {}), collapsed: true };

            for (const linkId of removeLinks) graph.removeLink(linkId);
            node.connect(slotIndex, setNode, 0);
            setInputName(setNode, linkName);
            setNode.validateName?.(graph);
            setNode.properties.previousName = getInputName(setNode);
            setNode.title = prefixedTitle(SET_TITLE, getInputName(setNode));
            const finalName = getInputName(setNode);

            for (const target of targets) {
                const targetNode = graph.getNodeById(target.targetId);
                if (!targetNode) continue;
                const getNode = createNode(GET_NODE_TYPE, graph, [
                    targetNode.pos[0] - 230,
                    targetNode.pos[1],
                ]);
                if (!getNode) continue;
                getNode.flags = { ...(getNode.flags || {}), collapsed: true };
                setInputName(getNode, finalName);
                getNode.onRename?.();
                getNode.connect(0, targetNode, target.targetSlot);
                created += 1;
            }
        }
    } finally {
        graphChangeEnd(changedGraph);
    }
    if (created) toast("info", `已创建 ${created} 个获取点`, 2500);
}

function convertLinkToSetGet(canvas, graph, link) {
    const originNode = graph.getNodeById(link.origin_id);
    const targetNode = graph.getNodeById(link.target_id);
    if (!originNode || !targetNode) return;
    const changedGraph = graphChangeStart(graph);
    try {
        const output = originNode.outputs?.[link.origin_slot];
        const linkType = output?.type || link.type || "*";
        const linkName = output?.name || linkType;

        const setNode = createNode(SET_NODE_TYPE, graph, [
            originNode.pos[0] + (originNode.size?.[0] || 200) + 30,
            originNode.pos[1],
        ]);
        const getNode = createNode(GET_NODE_TYPE, graph, [
            targetNode.pos[0] - 230,
            targetNode.pos[1],
        ]);
        if (!setNode || !getNode) return;

        graph.removeLink(link.id);
        originNode.connect(link.origin_slot, setNode, 0);
        setInputName(setNode, linkName);
        setNode.validateName?.(graph);
        setNode.properties.previousName = getInputName(setNode);

        setInputName(getNode, getInputName(setNode));
        getNode.onRename?.();
        getNode.connect(0, targetNode, link.target_slot);
    } finally {
        graphChangeEnd(changedGraph);
        canvas?.setDirty?.(true, true);
    }
}

function activeElementAllowsShortcut() {
    if (document.querySelector(".litecontextmenu")) return false;
    const active = document.activeElement;
    if (!active || active === document.body || active === app.canvas?.canvas) return true;
    const tag = active.tagName;
    if (active.isContentEditable) return false;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return false;
    return app.canvas?.canvas?.matches?.(":hover") || false;
}

function handleShortcut(event) {
    if (event.defaultPrevented || event.repeat) return;
    if (!event.ctrlKey || event.altKey || event.shiftKey || event.metaKey) return;
    if (!activeElementAllowsShortcut()) return;

    if (event.key === "[" || event.code === "BracketLeft") {
        event.preventDefault();
        addNodeToSelectedOrCursor(SET_NODE_TYPE, "right");
    } else if (event.key === "]" || event.code === "BracketRight") {
        event.preventDefault();
        addNodeToSelectedOrCursor(GET_NODE_TYPE, "left");
    } else if (event.key === "\\" || event.code === "Backslash") {
        event.preventDefault();
        forceShowAllLinks = !forceShowAllLinks;
        app.canvas?.setDirty(true, true);
        toast("info", forceShowAllLinks ? "已临时显示全部关联线" : "已恢复关联线显示设置", 1500);
    }
}

function patchCanvasDrawing() {
    const proto = LGraphCanvas.prototype;
    if (!proto.__lingxiSetGetVisiblePatch) {
        proto.__lingxiSetGetVisiblePatch = true;
        const originalComputeVisibleNodes = proto.computeVisibleNodes;
        proto.computeVisibleNodes = function () {
            const visible = originalComputeVisibleNodes?.apply(this, arguments) || [];
            for (const node of this.graph?._nodes || []) {
                if ((node.type === SET_NODE_TYPE || node.type === GET_NODE_TYPE) && node.drawConnection && !visible.includes(node)) {
                    visible.push(node);
                }
            }
            return visible;
        };
    }

    if (app.canvas?.__lingxiSetGetDrawPatch) return;
    app.canvas.__lingxiSetGetDrawPatch = true;
    const originalOnDrawBackground = app.canvas.onDrawBackground;
    app.canvas.onDrawBackground = function (ctx, visibleArea) {
        originalOnDrawBackground?.call(this, ctx, visibleArea);
        const graph = this.graph || app.graph;
        if (!graph?._nodes) return;

        const mode = getShowLinksMode();
        let selectedNames = null;
        const selected = Object.values(this.selected_nodes || {});
        if (mode === "选中时") {
            selectedNames = new Set();
            for (const node of selected) {
                if (node.type === SET_NODE_TYPE || node.type === GET_NODE_TYPE) {
                    const name = getInputName(node);
                    if (name) selectedNames.add(name);
                }
            }
        }
        if (mode === "从不" && !graph._nodes.some((node) => node.type === SET_NODE_TYPE && node.drawConnection)) return;
        if (mode === "选中时" && !selectedNames?.size && !graph._nodes.some((node) => node.type === SET_NODE_TYPE && node.drawConnection)) return;

        const gettersByName = new Map();
        for (const scopeGraph of [graph, ...getGraphDescendants(graph)]) {
            for (const node of scopeGraph?._nodes || []) {
                if (node.type !== GET_NODE_TYPE) continue;
                const name = getInputName(node);
                if (!name) continue;
                if (!gettersByName.has(name)) gettersByName.set(name, []);
                gettersByName.get(name).push(node);
            }
        }

        for (const setNode of graph._nodes) {
            if (setNode.type !== SET_NODE_TYPE) continue;
            const name = getInputName(setNode);
            const showByMode = mode === "总是" || (mode === "选中时" && selectedNames?.has(name));
            if (!showByMode && !setNode.drawConnection) continue;

            const targets = [];
            const seenSubgraphs = new Set();
            for (const getter of gettersByName.get(name) || []) {
                if (getter.graph === graph) {
                    targets.push(getter);
                } else {
                    const subgraphNode = findSubgraphNodeFor(graph, getter);
                    if (subgraphNode && !seenSubgraphs.has(subgraphNode)) {
                        seenSubgraphs.add(subgraphNode);
                        targets.push(subgraphNode);
                    }
                }
            }
            if (!targets.length) continue;

            const linkType = setNode.inputs?.[0]?.type;
            const color = app.canvas?.default_connection_color_byType?.[linkType]
                || LGraphCanvas.link_type_colors?.[linkType]
                || setNode.bgcolor
                || setNode.slotColor
                || "#aaa";
            const start = setNode.getConnectionPos(false, 0);
            for (const target of targets) {
                const end = target.getConnectionPos(true, 0);
                const highlighted = setNode.is_selected || target.is_selected;
                this.renderLink(ctx, start, end, null, false, null, highlighted ? "#fff" : color, LiteGraph.RIGHT, LiteGraph.LEFT);
            }
        }
    };
}

function patchMiddleClick() {
    const proto = LGraphCanvas.prototype;
    if (proto.__lingxiSetGetMiddlePatch) return;
    proto.__lingxiSetGetMiddlePatch = true;

    let fromMiddleClick = false;
    let lastMiddleAlt = false;
    const originalProcessMiddle = proto._processMiddleButton;
    const originalCreateDefault = proto.createDefaultNodeForSlot;
    if (!originalProcessMiddle || !originalCreateDefault) return;

    proto._processMiddleButton = function (event, node) {
        fromMiddleClick = true;
        lastMiddleAlt = !!event.altKey;
        const wantSetGet = lastMiddleAlt && settingValue(SETTINGS.altMiddleClick, false);
        const saved = LiteGraph.middle_click_slot_add_default_node;
        if (wantSetGet) LiteGraph.middle_click_slot_add_default_node = true;
        const result = originalProcessMiddle.call(this, event, node);
        LiteGraph.middle_click_slot_add_default_node = saved;
        return result;
    };

    proto.createDefaultNodeForSlot = function (optPass) {
        if (!fromMiddleClick) return originalCreateDefault.call(this, optPass);
        fromMiddleClick = false;
        const wantSetGet = lastMiddleAlt && settingValue(SETTINGS.altMiddleClick, false);
        if (!wantSetGet) return originalCreateDefault.call(this, optPass);

        const isFrom = optPass.nodeFrom && optPass.slotFrom != null;
        const sourceNode = isFrom ? optPass.nodeFrom : optPass.nodeTo;
        const slotIndex = isFrom ? optPass.slotFrom : optPass.slotTo;
        const graph = this.graph || app.graph;
        if (!sourceNode || slotIndex == null || !graph) return originalCreateDefault.call(this, optPass);

        const newNode = LiteGraph.createNode(isFrom ? SET_NODE_TYPE : GET_NODE_TYPE);
        if (!newNode) return false;
        const bounds = sourceNode.getBounding?.() || [sourceNode.pos[0], sourceNode.pos[1], sourceNode.size?.[0] || 200, sourceNode.size?.[1] || 80];
        newNode.pos = [
            isFrom ? bounds[0] + bounds[2] + 30 : bounds[0] - 230,
            optPass.position?.[1] ?? bounds[1],
        ];
        graph.add(newNode);
        if (isFrom) sourceNode.connect(slotIndex, newNode, 0);
        else newNode.connect(0, sourceNode, slotIndex);
        graph.change?.();
        this.setDirty(true, true);
        return true;
    };
}

function patchConnectionMenu() {
    if (app.canvas?.__lingxiSetGetConnectionMenuPatch || !app.canvas?.showConnectionMenu) return;
    app.canvas.__lingxiSetGetConnectionMenuPatch = true;
    const originalShowConnectionMenu = app.canvas.showConnectionMenu.bind(app.canvas);
    app.canvas.showConnectionMenu = function (optPass) {
        if (!settingValue(SETTINGS.showInConnectionMenu, true)) return originalShowConnectionMenu(optPass);

        const isFrom = optPass.nodeFrom && optPass.slotFrom != null;
        const nodeType = isFrom ? SET_NODE_TYPE : GET_NODE_TYPE;
        const label = isFrom ? "添加设置点" : "添加获取点";
        const OriginalContextMenu = LiteGraph.ContextMenu;
        let active = true;

        LiteGraph.ContextMenu = function (options, menuOptions) {
            LiteGraph.ContextMenu = OriginalContextMenu;
            if (!active) return new OriginalContextMenu(options, menuOptions);
            active = false;

            const insertIndex = options.indexOf("Add Reroute");
            if (insertIndex >= 0) options.splice(insertIndex + 1, 0, label);
            else options.unshift(label);

            const originalCallback = menuOptions.callback;
            menuOptions.callback = function (value, callbackOptions, event) {
                if (value === label) {
                    const graph = app.canvas?.graph || app.graph;
                    const node = createNode(nodeType, graph, [optPass.e?.canvasX ?? 0, optPass.e?.canvasY ?? 0]);
                    if (!node) return;
                    if (isFrom && optPass.nodeFrom) {
                        const slotIndex = typeof optPass.slotFrom === "number"
                            ? optPass.slotFrom
                            : optPass.nodeFrom.findOutputSlot?.(optPass.slotFrom.name);
                        optPass.nodeFrom.connect(slotIndex, node, 0);
                    } else if (optPass.nodeTo) {
                        const slotIndex = typeof optPass.slotTo === "number"
                            ? optPass.slotTo
                            : optPass.nodeTo.findInputSlot?.(optPass.slotTo.name);
                        node.connect(0, optPass.nodeTo, slotIndex);
                    }
                    graph?.change?.();
                    app.canvas?.setDirty(true, true);
                    return;
                }
                return originalCallback?.call(this, value, callbackOptions, event);
            };
            return new OriginalContextMenu(options, menuOptions);
        };
        LiteGraph.ContextMenu.prototype = OriginalContextMenu.prototype;

        const result = originalShowConnectionMenu(optPass);
        LiteGraph.ContextMenu = OriginalContextMenu;
        active = false;
        return result;
    };
}

function patchLinkMenu() {
    const proto = LGraphCanvas.prototype;
    if (proto.__lingxiSetGetLinkMenuPatch || !proto.showLinkMenu) return;
    proto.__lingxiSetGetLinkMenuPatch = true;
    const originalShowLinkMenu = proto.showLinkMenu;
    proto.showLinkMenu = function (segment, event) {
        const menusBefore = document.querySelectorAll(".litecontextmenu").length;
        const result = originalShowLinkMenu.call(this, segment, event);
        const graph = this.graph;
        const link = getLink(graph, segment?.id);
        if (!graph || !link || link.origin_id == null || link.target_id == null) return result;

        const menus = document.querySelectorAll(".litecontextmenu");
        if (menus.length <= menusBefore) return result;
        const menu = menus[menus.length - 1];
        const entries = menu?.querySelector(".litemenu-entry")?.parentElement;
        if (!entries) return result;

        const separator = document.createElement("div");
        separator.className = "litemenu-entry separator";
        entries.appendChild(separator);

        const item = document.createElement("div");
        item.className = "litemenu-entry submenu";
        item.textContent = "转换为设置点/获取点";
        item.addEventListener("click", () => {
            menu.remove();
            convertLinkToSetGet(this, graph, link);
        });
        entries.appendChild(item);
        return result;
    };
}

function patchCrossGraphPrompt() {
    if (app.__lingxiSetGetCrossGraphPatch || !app.graphToPrompt) return;
    app.__lingxiSetGetCrossGraphPatch = true;
    const originalGraphToPrompt = app.graphToPrompt.bind(app);
    let patchedDto = false;

    app.graphToPrompt = async function (...args) {
        if (!patchedDto) {
            try {
                const subgraphNode = app.graph?._nodes?.find((node) => typeof node.getInnerNodes === "function");
                if (subgraphNode) {
                    const map = new Map();
                    const dtos = subgraphNode.getInnerNodes(map, []);
                    if (dtos?.length) {
                        const proto = Object.getPrototypeOf(dtos[0]);
                        if (!String(proto.resolveOutput).includes("resolveVirtualOutput")) {
                            const DtoClass = proto.constructor;
                            const originalResolveOutput = proto.resolveOutput;
                            proto.resolveOutput = function (slot, type, visited) {
                                const virtualSource = this.node?.resolveVirtualOutput?.(slot);
                                if (virtualSource) {
                                    const inputDto = [...this.nodesByExecutionId.values()]
                                        .find((dto) => dto instanceof DtoClass && dto.node === virtualSource.node);
                                    if (inputDto) return inputDto.resolveOutput(virtualSource.slot, type, visited);
                                    throw new Error(`${MENU_TITLE}: 没有找到跨子图来源节点 ${virtualSource.node?.id}`);
                                }
                                return originalResolveOutput.call(this, slot, type, visited);
                            };
                        }
                        patchedDto = true;
                    }
                }
            } catch (error) {
                console.warn(`[${MENU_TITLE}] 跨子图解析补丁未启用`, error);
            }
        }
        return originalGraphToPrompt(...args);
    };
}

function installDoubleClickJump() {
    if (window.__lingxiSetGetDoubleClickInstalled) return;
    window.__lingxiSetGetDoubleClickInstalled = true;
    document.addEventListener("dblclick", () => {
        if (document.querySelector(".litecontextmenu")) return;
        const selected = Object.values(app.canvas?.selected_nodes || {});
        if (selected.length !== 1) return;
        const node = selected[0];
        if (node?.type === GET_NODE_TYPE) node.goToSetter?.();
    });
    document.addEventListener("litegraph:canvas", (event) => {
        if (event.detail?.subType !== "node-double-click") return;
        const node = event.detail.node;
        if (node?.type === GET_NODE_TYPE && node.flags?.collapsed) event.stopImmediatePropagation();
    });
}

function installShortcutListener() {
    if (window.__lingxiSetGetShortcutsInstalled) return;
    window.__lingxiSetGetShortcutsInstalled = true;
    document.addEventListener("keydown", handleShortcut, true);
}

function convertAllWithConfirm() {
    const ok = confirm("将删除全部设置点/获取点，并尽量恢复为真实连线。操作前会保留一次临时回退记录，继续吗？");
    if (!ok) return;
    convertAllSetGetToLinks(app.graph, { snapshot: true });
}

app.registerExtension({
    name: "Lingxi.SetGet",
    settings: [
        {
            id: SETTINGS.naming,
            name: "默认设置点名称",
            category: ["灵犀", "设置点/获取点", "默认设置点名称"],
            tooltip: "设置点第一次连上线时，名称框自动填什么",
            type: "combo",
            options: ["空", "插槽名", "插槽名小写", "插槽名大写"],
            defaultValue: "空",
        },
        {
            id: SETTINGS.showLinks,
            name: "关联线显示",
            category: ["灵犀", "设置点/获取点", "关联线显示"],
            tooltip: "控制设置点和获取点之间的辅助关联线何时显示",
            type: "combo",
            options: ["从不", "选中时", "总是"],
            defaultValue: "从不",
            onChange: () => app.canvas?.setDirty(true, true),
        },
        {
            id: SETTINGS.autoColor,
            name: "按类型自动上色",
            category: ["灵犀", "设置点/获取点", "按类型自动上色"],
            tooltip: "按 IMAGE、MODEL、LATENT 等连接类型给设置点和获取点自动上色",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: SETTINGS.hideTitlePrefix,
            name: "隐藏标题前缀",
            category: ["灵犀", "设置点/获取点", "隐藏标题前缀"],
            tooltip: "开启后，节点标题只显示名称，不显示设置点/获取点前缀",
            type: "boolean",
            defaultValue: false,
        },
        {
            id: SETTINGS.showInConnectionMenu,
            name: "连接菜单显示入口",
            category: ["灵犀", "设置点/获取点", "连接菜单显示入口"],
            tooltip: "在插槽连接菜单中显示添加设置点和添加获取点",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: SETTINGS.filterGetOptions,
            name: "获取点按类型过滤",
            category: ["灵犀", "设置点/获取点", "获取点按类型过滤"],
            tooltip: "获取点已连接目标输入时，只显示类型兼容的设置点名称",
            type: "boolean",
            defaultValue: true,
        },
        {
            id: SETTINGS.altMiddleClick,
            name: "Alt+中键创建设置/获取点",
            category: ["灵犀", "设置点/获取点", "Alt+中键创建设置/获取点"],
            tooltip: "开启后，在输出插槽 Alt+中键创建设置点，在输入插槽 Alt+中键创建获取点",
            type: "boolean",
            defaultValue: false,
        },
    ],
    commands: [
        {
            id: "Lingxi.SetGet.AddSetPoint",
            label: "添加设置点",
            function: () => addNodeToSelectedOrCursor(SET_NODE_TYPE, "right"),
        },
        {
            id: "Lingxi.SetGet.AddGetPoint",
            label: "添加获取点",
            function: () => addNodeToSelectedOrCursor(GET_NODE_TYPE, "left"),
        },
        {
            id: "Lingxi.SetGet.ToggleLinks",
            label: "临时显示/隐藏全部关联线",
            function: () => {
                forceShowAllLinks = !forceShowAllLinks;
                app.canvas?.setDirty(true, true);
            },
        },
    ],
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === SET_NODE_TYPE) patchNodeType(nodeType, "set");
        if (nodeData.name === GET_NODE_TYPE) patchNodeType(nodeType, "get");
    },
    beforeConfigureGraph: normalizeSetGetWorkflow,
    getNodeMenuItems(node) {
        const items = [];
        if (node?.outputs?.length) {
            const selected = snapshotSelectedNodes(node);
            items.push({
                content: "输出转为设置点/获取点",
                callback: () => {
                    for (const selectedNode of selected) convertOutputsToSetGet(selectedNode.graph || node.graph, selectedNode);
                },
            });
        }
        if (node?.inputs?.length) {
            items.push(
                {
                    content: "添加获取点",
                    callback: () => addNodeNear(GET_NODE_TYPE, node, { side: "left", offset: 30 }),
                },
                {
                    content: "添加设置点",
                    callback: () => addNodeNear(SET_NODE_TYPE, node, { side: "right", offset: 30 }),
                },
            );
        }
        return items;
    },
    getCanvasMenuItems() {
        return [
            {
                content: MENU_TITLE,
                has_submenu: true,
                submenu: {
                    options: [
                        {
                            content: "添加设置点",
                            callback: () => addNodeToSelectedOrCursor(SET_NODE_TYPE, "right"),
                        },
                        {
                            content: "添加获取点",
                            callback: () => addNodeToSelectedOrCursor(GET_NODE_TYPE, "left"),
                        },
                        {
                            content: "选中节点输出转为设置点/获取点",
                            callback: () => {
                                for (const node of Object.values(app.canvas?.selected_nodes || {})) {
                                    convertOutputsToSetGet(node.graph || app.canvas?.graph || app.graph, node);
                                }
                            },
                        },
                        {
                            content: "选中的设置点/获取点转为真实连线",
                            callback: () => convertSelectedSetGetToLinks(null),
                        },
                        {
                            content: "全部转为真实连线",
                            callback: convertAllWithConfirm,
                        },
                        {
                            content: "撤销上次全部还原",
                            callback: restoreLastSnapshot,
                        },
                    ],
                },
            },
        ];
    },
    setup() {
        installShortcutListener();
        installDoubleClickJump();
        patchCanvasDrawing();
        patchConnectionMenu();
        patchLinkMenu();
        patchMiddleClick();
        patchClipboardTargetSlots();
        patchCrossGraphPrompt();
        patchSetGetPastePairing();

        app.ui?.settings?.addSetting?.({
            id: "Lingxi.SetGet.convertAll",
            name: "全部转为真实连线",
            category: ["灵犀", "设置点/获取点", "全部转为真实连线"],
            tooltip: "删除全部设置点/获取点，并把能恢复的连接恢复成真实连线",
            type: () => {
                const button = document.createElement("button");
                button.textContent = "全部转为真实连线";
                button.style.cssText = "padding: 6px 12px; cursor: pointer;";
                button.onclick = convertAllWithConfirm;
                return button;
            },
            defaultValue: false,
        });
        app.ui?.settings?.addSetting?.({
            id: "Lingxi.SetGet.restoreLast",
            name: "撤销上次全部还原",
            category: ["灵犀", "设置点/获取点", "撤销上次全部还原"],
            tooltip: "恢复到上一次全部转为真实连线之前的临时快照，只保留最近一次",
            type: () => {
                const button = document.createElement("button");
                button.textContent = "撤销上次全部还原";
                button.style.cssText = "padding: 6px 12px; cursor: pointer;";
                button.onclick = restoreLastSnapshot;
                return button;
            },
            defaultValue: false,
        });
    },
});

window.lingxiSetGet = {
    addSetPoint: () => addNodeToSelectedOrCursor(SET_NODE_TYPE, "right"),
    addGetPoint: () => addNodeToSelectedOrCursor(GET_NODE_TYPE, "left"),
    convertOutputsToSetGet,
    convertSelectedSetGetToLinks,
    convertAllSetGetToLinks,
    restoreLastSnapshot,
};
