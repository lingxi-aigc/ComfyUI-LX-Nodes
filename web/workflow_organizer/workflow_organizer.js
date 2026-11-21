import { app } from "../../../../scripts/app.js";
import { collectGuideNotes, isAutoPositionedGuide, isGuideNote, recordGuidePosition, syncGuideNotes } from "./annotations.js";
import { planGroups } from "./grouping.js";
import { planLayout } from "./layout.js";

const MENU_TITLE = "智能工作流排版";
const ORGANIZE = "一键整理工作流";
const ORGANIZE_WITH_NOTES = "整理并添加说明";
const ORGANIZE_WITH_GROUPS = "整理并生成分组";
const ORGANIZE_WITH_GROUPS_AND_NOTES = "整理并生成分组及说明";
const AUTO_GROUP_FLAG = "lx_auto_workflow_layout";
const ORGANIZE_COMMAND = "LX.WorkflowOrganizer.Arrange";
const NOTES_COMMAND = "LX.WorkflowOrganizer.ArrangeWithNotes";
const GROUPS_COMMAND = "LX.WorkflowOrganizer.ArrangeWithGroups";
const GROUPS_AND_NOTES_COMMAND = "LX.WorkflowOrganizer.ArrangeWithGroupsAndNotes";
const GROUP_PADDING = 28;

function getGraph(canvas = app.canvas) {
    return canvas?.graph || app.graph;
}

function getNodes(graph) {
    return Array.from(graph?.nodes ?? graph?._nodes ?? []);
}

function getGroups(graph) {
    return Array.from(graph?.groups ?? graph?._groups ?? []);
}

function getValues(collection) {
    if (!collection) return [];
    return typeof collection.values === "function" ? [...collection.values()] : Object.values(collection);
}

function getBounds(item) {
    const bounds = item.getBounding?.() ?? item.boundingRect ?? item._bounding;
    if (bounds?.length === 4 && Array.from(bounds).every(Number.isFinite) && bounds[2] > 0 && bounds[3] > 0) {
        return Array.from(bounds);
    }
    return [item.pos?.[0] ?? 0, item.pos?.[1] ?? 0, item.size?.[0] || 16, item.size?.[1] || 16];
}

function union(rects) {
    const left = Math.min(...rects.map(([x]) => x));
    const top = Math.min(...rects.map(([, y]) => y));
    const right = Math.max(...rects.map(([x, , w]) => x + w));
    const bottom = Math.max(...rects.map(([, y, , h]) => y + h));
    return [left, top, right - left, bottom - top];
}

function containsPoint([x, y, w, h], [px, py]) {
    return px >= x && px <= x + w && py >= y && py <= y + h;
}

function containsRect(outer, [x, y, w, h]) {
    return containsPoint(outer, [x, y]) && containsPoint(outer, [x + w, y + h]);
}

function intersects([x, y, w, h], [a, b, c, d]) {
    return x < a + c && a < x + w && y < b + d && b < y + h;
}

function offsetBounds([x, y, w, h], dx, dy) {
    return [x + dx, y + dy, w, h];
}

function isPinned(item) {
    return Boolean(item.pinned ?? item.flags?.pinned);
}

function isManualNote(node) {
    return !isGuideNote(node) && ["Note", "MarkdownNote", "备注", "LXCanvasTitle"].includes(node.type ?? node.comfyClass);
}

function getSelection(canvas) {
    const items = canvas?.selectedItems;
    return new Set(items?.[Symbol.iterator] ? items : getValues(items ?? canvas?.selected_nodes));
}

function selectedNodes(canvas, graph, selected = getSelection(canvas)) {
    return getNodes(graph).filter((node) => selected.has(node) && !isGuideNote(node) && !isManualNote(node));
}

function area([, , w, h]) {
    return w * h;
}

function captureScene(graph, canvas) {
    const nodes = getNodes(graph);
    const groups = getGroups(graph);
    const reroutes = getValues(graph.reroutes);
    const links = getValues(graph.links ?? graph._links);
    const items = [...nodes, ...groups, ...reroutes];
    for (const node of nodes) node.updateArea?.(canvas?.ctx);
    const bounds = new Map(items.map((item) => [item, getBounds(item)]));
    const groupSet = new Set(groups);
    const groupsBySize = [...groups].sort((a, b) => area(bounds.get(a)) - area(bounds.get(b)));
    const owners = new Map();
    for (const item of items) {
        const rect = bounds.get(item);
        const [x, y, w, h] = rect;
        const owner = groupsBySize.find((group) => group !== item && (groupSet.has(item)
            ? area(bounds.get(group)) > area(rect) && containsRect(bounds.get(group), rect)
            : containsPoint(bounds.get(group), [x + w / 2, y + h / 2])));
        if (owner) owners.set(item, owner);
    }
    return { nodes, groups, reroutes, links, bounds, owners, notes: collectGuideNotes(graph) };
}

function within(scene, item, group) {
    for (let owner = scene.owners.get(item); owner; owner = scene.owners.get(owner)) {
        if (owner === group) return true;
    }
    return false;
}

function isProtected(scene, item) {
    if (isPinned(item)) return true;
    for (let owner = scene.owners.get(item); owner; owner = scene.owners.get(owner)) {
        if (isPinned(owner)) return true;
    }
    return false;
}

function createUnit(scene, parts, id) {
    const rect = union(parts.map((part) => scene.bounds.get(part)));
    const locked = parts.some((part) => isProtected(scene, part));
    return { id, pos: rect.slice(0, 2), rect, parts, locked };
}

function groupLayoutId(id) {
    const key = String(id);
    return `group:${/^\d+$/.test(key) ? key.padStart(16, "0") : key}`;
}

function createAutoGroupUnit(scene, cluster, index, GroupClass) {
    const group = new GroupClass(cluster.title);
    group.color = cluster.color;
    group.flags[AUTO_GROUP_FLAG] = true;
    const [left, top] = union(cluster.nodes.map((node) => scene.bounds.get(node)));
    const header = Number(group.titleHeight) || 30;
    const positions = planLayout(cluster.nodes, scene.links, scene.bounds, {
        anchor: [left + GROUP_PADDING, top + header + GROUP_PADDING],
    });
    const content = union([...positions].map(([node, [x, y]]) =>
        offsetBounds(scene.bounds.get(node), x - node.pos[0], y - node.pos[1])
    ));
    const rect = [
        left, top,
        Math.max(GroupClass.minWidth || 140, Math.ceil(content[2] + GROUP_PADDING * 2)),
        Math.max(GroupClass.minHeight || 80, Math.ceil(content[3] + header + GROUP_PADDING * 2)),
    ];
    return { id: groupLayoutId(`~${String(index).padStart(8, "0")}`), pos: rect.slice(0, 2), rect, parts: cluster.nodes, positions, group };
}

function makeUnits(scene, withinGroup, selection, flowableNotes, autoUnits) {
    const { nodes, groups, reroutes, owners } = scene;
    const units = [...autoUnits];
    const selected = selection && new Set(selection);
    if (!selected) {
        for (const group of groups.filter((item) => owners.get(item) === withinGroup)) {
            const children = [...nodes, ...groups, ...reroutes].filter((item) => within(scene, item, group));
            units.push(createUnit(scene, [group, ...children], groupLayoutId(group.id)));
        }
    }

    const plannedNodes = new Set(autoUnits.flatMap((unit) => unit.parts));
    const direct = nodes.filter((node) => owners.get(node) === withinGroup && !isGuideNote(node));
    for (const node of direct) {
        if ((selected && !selected.has(node)) || isManualNote(node) || plannedNodes.has(node)) continue;
        plannedNodes.add(node);
        units.push(createUnit(scene, [node], `node:${node.id}`));
    }
    const stationary = direct.filter((node) => !plannedNodes.has(node));
    stationary.push(...nodes.filter((item) => owners.get(item) === withinGroup && isGuideNote(item) && !flowableNotes.has(item)));
    if (selected) stationary.push(...groups.filter((group) => owners.get(group) === withinGroup));
    return { units, stationary };
}

function planScope(scene, moves, arrangedNodes, group, selected, allowExpand, flowableNotes, autoUnits = []) {
    const { units, stationary } = makeUnits(scene, group, selected, flowableNotes, autoUnits);
    const movable = units.filter((unit) => !unit.locked);
    if (!movable.length) return { skipped: false };
    const unitByNodeId = new Map();
    const nodeSet = new Set(scene.nodes);
    for (const unit of units) {
        for (const node of unit.parts.filter((part) => nodeSet.has(part))) {
            unitByNodeId.set(String(node.id), unit.id);
        }
    }
    const links = scene.links.map((link) => ({
        origin_id: unitByNodeId.get(String(link.origin_id)),
        target_id: unitByNodeId.get(String(link.target_id)),
    }));
    const obstacles = [...units.filter((unit) => unit.locked).map((unit) => unit.rect), ...stationary.map((item) => scene.bounds.get(item))];
    const groupBounds = group && scene.bounds.get(group);
    const titleHeight = Number(group?.titleHeight) || 28;
    const anchor = groupBounds && [groupBounds[0] + GROUP_PADDING, groupBounds[1] + titleHeight + GROUP_PADDING];
    const planned = planLayout(movable, links, new Map(movable.map((unit) => [unit, unit.rect])), { anchor, obstacles });
    let expanded = null;
    if (groupBounds && planned.size) {
        const plannedBounds = [...planned].map(([unit, [x, y]]) =>
            offsetBounds(unit.rect, x - unit.pos[0], y - unit.pos[1])
        );
        const fitted = union(plannedBounds);
        const right = Math.max(groupBounds[0] + groupBounds[2], fitted[0] + fitted[2] + GROUP_PADDING);
        const bottom = Math.max(groupBounds[1] + groupBounds[3], fitted[1] + fitted[3] + GROUP_PADDING);
        expanded = [groupBounds[0], groupBounds[1], Math.ceil(right - groupBounds[0]), Math.ceil(bottom - groupBounds[1])];
        const changedBounds = expanded[2] !== groupBounds[2] || expanded[3] !== groupBounds[3];
        if (changedBounds) {
            if (!allowExpand || scene.owners.has(group)) return { skipped: true };
            const collides = [...scene.nodes, ...scene.groups].some((item) => {
                if (item === group || within(scene, item, group)) return false;
                const rect = scene.bounds.get(item);
                if (!intersects(expanded, rect)) return false;
                if (!intersects(groupBounds, rect)) return true;
                const [x, y, w, h] = rect;
                const center = [x + w / 2, y + h / 2];
                return !containsPoint(groupBounds, center) && containsPoint(expanded, center);
            });
            if (collides) return { skipped: true };
        } else {
            expanded = null;
        }
    }
    const newGroups = [];
    for (const [unit, [x, y]] of planned) {
        for (const item of unit.parts) if (nodeSet.has(item)) arrangedNodes.add(item);
        const dx = x - unit.pos[0];
        const dy = y - unit.pos[1];
        if (unit.group) {
            newGroups.push({ group: unit.group, bounds: offsetBounds(unit.rect, dx, dy), nodes: unit.parts });
        }
        if (!unit.positions && !dx && !dy) continue;
        for (const item of unit.parts) {
            const [itemX, itemY] = unit.positions?.get(item) ?? item.pos;
            moves.set(item, [itemX + dx, itemY + dy]);
        }
    }
    return { skipped: false, expanded, newGroups };
}

function planReroutes(scene, moves, arrangedNodes) {
    const reroutes = new Map(scene.reroutes.map((point) => [String(point.id), point]));
    const nodesById = new Map(scene.nodes.map((node) => [String(node.id), node]));
    const connected = new Map();
    for (const link of scene.links) {
        let point = reroutes.get(String(link.parentId));
        const visited = new Set();
        while (point && !visited.has(point)) {
            visited.add(point);
            if (!connected.has(point)) connected.set(point, { sources: new Set(), targets: new Set() });
            const { sources, targets } = connected.get(point);
            sources.add(nodesById.get(String(link.origin_id)));
            targets.add(nodesById.get(String(link.target_id)));
            point = reroutes.get(String(point.parentId));
        }
    }
    const shift = (node) => {
        const [x, y] = moves.get(node) ?? node.pos;
        return [x - node.pos[0], y - node.pos[1]];
    };
    for (const [point, { sources, targets }] of connected) {
        const endpoints = [...new Set([...sources, ...targets])];
        const owner = scene.owners.get(point);
        if (moves.has(point) || isProtected(scene, point) ||
            endpoints.some((node) => !arrangedNodes.has(node) || scene.owners.get(node) !== owner)) continue;
        const shifts = endpoints.map(shift);
        if (shifts.every(([x, y]) => !x && !y)) continue;
        let x = point.pos[0] + shifts.reduce((sum, move) => sum + move[0], 0) / shifts.length;
        let y = point.pos[1] + shifts.reduce((sum, move) => sum + move[1], 0) / shifts.length;
        if (!shifts.every(([dx, dy]) => dx === shifts[0][0] && dy === shifts[0][1])) {
            const nextBounds = (node) => offsetBounds(scene.bounds.get(node), ...shift(node));
            const left = Math.max(...[...sources].map((node) => {
                const [x, , w] = nextBounds(node);
                return x + w + 12;
            }));
            const right = Math.min(...[...targets].map((node) => nextBounds(node)[0] - 12));
            const centers = endpoints.map((node) => {
                const [, y, , h] = nextBounds(node);
                return y + h / 2;
            });
            if (left <= right) x = Math.max(left, Math.min(right, x));
            y = Math.max(Math.min(...centers) - 40, Math.min(Math.max(...centers) + 40, y));
        }
        if (!owner || containsPoint(scene.bounds.get(owner), [x, y])) {
            moves.set(point, [Math.round(x), Math.round(y)]);
        }
    }
}

function applyMoves(canvas, scene, moves) {
    const nodes = scene.nodes.filter((node) => moves.has(node));
    const guides = nodes.filter(isAutoPositionedGuide);
    if (nodes.length && typeof canvas?.applyNodePositions === "function") {
        canvas.applyNodePositions(nodes.map((node) => {
            const [x, y] = moves.get(node);
            return { node, newPos: { x, y } };
        }));
    } else {
        for (const node of nodes) node.pos = moves.get(node);
    }
    for (const item of [...scene.groups, ...scene.reroutes]) {
        if (moves.has(item)) item.pos = moves.get(item);
    }
    for (const node of nodes) node.updateArea?.(canvas?.ctx);
    for (const guide of guides) recordGuidePosition(guide);
}

function withGraphChange(canvas, graph, change) {
    graph.beforeChange?.();
    canvas?.emitBeforeChange?.();
    try {
        return change();
    } finally {
        graph.afterChange?.();
        canvas?.emitAfterChange?.();
        graph.change?.();
        graph.setDirtyCanvas?.(true, true);
        canvas?.setDirty?.(true, true);
    }
}

function notify(detail, severity = "info") {
    app.extensionManager?.toast?.add({ severity, summary: MENU_TITLE, detail, life: 3400 });
}

function addPlannedGroups(graph, plans) {
    const owners = new Map();
    for (const { group, bounds, nodes } of plans) {
        group.pos = bounds.slice(0, 2);
        group.size = bounds.slice(2);
        graph.add(group);
        // ComfyUI may snap a group when adding it. Keep the obstacle-checked placement.
        if (Math.abs(group.pos[0] - bounds[0]) > 0.01 || Math.abs(group.pos[1] - bounds[1]) > 0.01) {
            group.pos = bounds.slice(0, 2);
        }
        for (const node of nodes) owners.set(node, group);
    }
    return owners;
}

function organize(canvas = app.canvas, { scope = "auto", group, includeNotes = false, includeGroups = false } = {}) {
    const graph = getGraph(canvas);
    if (!graph) return;
    if (canvas?.read_only) {
        notify("画布已锁定，解锁后可整理。", "warn");
        return;
    }
    const items = getSelection(canvas);
    const selected = selectedNodes(canvas, graph, items);
    if (scope === "auto" && items.size && !selected.length) {
        const onlyItem = [...items][0];
        if (items.size !== 1 || !getGroups(graph).includes(onlyItem)) {
            notify("请选择要整理的节点，或单独选择一个分组。");
            return;
        }
        scope = "group";
        group = onlyItem;
    }
    const scene = captureScene(graph, canvas);
    const useSelection = scope === "selection" || (scope === "auto" && selected.length > 0);
    const allNodes = scene.nodes.filter((node) => !isGuideNote(node) && !isManualNote(node));
    const targetNodes = scope === "group"
        ? allNodes.filter((node) => within(scene, node, group))
        : useSelection ? selected : allNodes;
    if (!targetNodes.length) {
        notify(useSelection ? "请先选中需要整理的节点。" : "当前范围没有可整理的节点。");
        return;
    }
    if (scope === "group" && (!group || isProtected(scene, group))) {
        notify("该分组已固定。", "warn");
        return;
    }

    const moves = new Map();
    const arrangedNodes = new Set();
    const protectedNodes = new Set(scene.nodes.filter((node) => isProtected(scene, node)));
    const GroupClass = globalThis.LiteGraph?.LGraphGroup ?? globalThis.LGraphGroup;
    const candidates = includeGroups && !group && GroupClass
        ? targetNodes.filter((node) => !scene.owners.has(node) && !protectedNodes.has(node)) : [];
    const titles = new Set(scene.groups.map((item) => item.title));
    const autoUnits = planGroups(candidates, scene.links).map((cluster, index) => {
        const base = cluster.title;
        for (let suffix = 2; titles.has(cluster.title); suffix++) cluster.title = `${base} ${suffix}`;
        titles.add(cluster.title);
        return createAutoGroupUnit(scene, cluster, index, GroupClass);
    });
    const flowableNotes = new Set(targetNodes.flatMap((node) => {
        const note = scene.notes.get(String(node.id));
        return !protectedNodes.has(node) && isAutoPositionedGuide(note) && !protectedNodes.has(note) ? [note] : [];
    }));
    let skipped = false;
    let expanded;
    let newGroups = [];
    if (useSelection) {
        for (const owner of new Set(selected.map((node) => scene.owners.get(node)))) {
            const plan = planScope(scene, moves, arrangedNodes, owner, selected, false, flowableNotes, owner ? [] : autoUnits);
            skipped = plan.skipped || skipped;
            if (plan.newGroups) newGroups.push(...plan.newGroups);
        }
    } else {
        ({ skipped, expanded, newGroups = [] } = planScope(scene, moves, arrangedNodes, group, null, scope === "group", flowableNotes, autoUnits));
    }
    planReroutes(scene, moves, arrangedNodes);
    if (!moves.size && !expanded && !newGroups.length && !includeNotes) {
        const message = includeGroups ? "当前范围没有适合新建分组的相连节点。" : "当前布局已整理或节点已固定。";
        notify(skipped ? "分组内空间不足，未移动选中节点。" : message, skipped ? "warn" : "info");
        return;
    }

    const notes = withGraphChange(canvas, graph, () => {
        applyMoves(canvas, scene, moves);
        if (expanded) {
            const [x, y, w, h] = expanded;
            if (typeof group.setBounds === "function") group.setBounds(x, y, w, h);
            else group.size = [w, h];
        }
        const groupOwners = addPlannedGroups(graph, newGroups);
        if (!includeNotes && !flowableNotes.size) return null;
        const existingGroups = getGroups(graph);
        return syncGuideNotes(graph, targetNodes, {
            getBounds,
            protectedNodes,
            addMissing: includeNotes,
            getObstacles: (node) => existingGroups.map((item) => {
                const bounds = getBounds(item);
                if (item === groupOwners.get(node) || within(scene, node, item)) {
                    bounds[3] = Number(item.titleHeight) || 30;
                }
                return bounds;
            }),
            getContainer: (node) => {
                const container = groupOwners.get(node) ?? scene.owners.get(node);
                return container && getBounds(container);
            },
        });
    });
    if (!group && !useSelection && !selected.length && (moves.size || newGroups.length || notes?.added) && canvas === app.canvas) {
        requestAnimationFrame(() => {
            if (getGraph(canvas) === graph && !canvas.selectedItems?.size) {
                app.extensionManager?.command?.execute?.("Comfy.Canvas.FitView");
            }
        });
    }
    const summary = [];
    if (includeGroups) summary.push(newGroups.length ? `新建 ${newGroups.length} 个分组` : "没有需要新增的分组");
    if (includeNotes) summary.push(notes?.added ? `添加 ${notes.added} 条说明` : "没有需要新增的说明");
    if (skipped) summary.push("空间不足的分组保留原布局");
    if (summary.length) notify(summary.join("，") + "。", skipped ? "warn" : "info");
}

function groupAtPointer(canvas, graph) {
    const point = canvas?.graph_mouse;
    if (!point?.length) return null;
    if (typeof graph?.getGroupOnPos === "function") return graph.getGroupOnPos(point[0], point[1]);
    return getGroups(graph).filter((group) => containsPoint(getBounds(group), point))
        .sort((a, b) => area(getBounds(a)) - area(getBounds(b)))[0] ?? null;
}

function clearAutoGroups(canvas, graph) {
    if (canvas?.read_only) return;
    const autoGroups = getGroups(graph).filter((group) => group.flags?.[AUTO_GROUP_FLAG] && !isPinned(group));
    if (autoGroups.length) withGraphChange(canvas, graph, () => autoGroups.forEach((group) => graph.remove(group)));
}

app.registerExtension({
    name: "LX.WorkflowOrganizer",
    commands: [
        { id: ORGANIZE_COMMAND, label: ORGANIZE, icon: "icon-[lucide--workflow]", function: () => organize() },
        { id: NOTES_COMMAND, label: ORGANIZE_WITH_NOTES, function: () => organize(app.canvas, { includeNotes: true }) },
        { id: GROUPS_COMMAND, label: ORGANIZE_WITH_GROUPS, function: () => organize(app.canvas, { includeGroups: true }) },
        { id: GROUPS_AND_NOTES_COMMAND, label: ORGANIZE_WITH_GROUPS_AND_NOTES, function: () => organize(app.canvas, { includeGroups: true, includeNotes: true }) },
    ],
    menuCommands: [{ path: ["Extensions", "灵犀工具"], commands: [ORGANIZE_COMMAND, NOTES_COMMAND, GROUPS_COMMAND, GROUPS_AND_NOTES_COMMAND] }],
    getSelectionToolboxCommands(item) {
        const graph = getGraph();
        if (!item || item.graph !== graph) return [];
        if (graph.getNodeById?.(item.id) === item && !isGuideNote(item) && !isManualNote(item)) return [ORGANIZE_COMMAND];
        return getGroups(graph).includes(item) ? [ORGANIZE_COMMAND] : [];
    },
    getCanvasMenuItems(canvas) {
        const graph = getGraph(canvas);
        const group = groupAtPointer(canvas, graph);
        const hasNodes = getNodes(graph).length > 0;
        const options = [
            { content: ORGANIZE, disabled: !hasNodes, callback: () => organize(canvas) },
            { content: ORGANIZE_WITH_NOTES, disabled: !hasNodes, callback: () => organize(canvas, { includeNotes: true }) },
            { content: ORGANIZE_WITH_GROUPS, disabled: !hasNodes, callback: () => organize(canvas, { includeGroups: true }) },
            { content: ORGANIZE_WITH_GROUPS_AND_NOTES, disabled: !hasNodes, callback: () => organize(canvas, { includeGroups: true, includeNotes: true }) },
            null,
            { content: "整理当前画布", disabled: !hasNodes, callback: () => organize(canvas, { scope: "canvas" }) },
            { content: "整理选中节点", disabled: !selectedNodes(canvas, graph).length, callback: () => organize(canvas, { scope: "selection" }) },
            { content: "整理当前分组", disabled: !group || isPinned(group), callback: () => organize(canvas, { scope: "group", group }) },
        ];
        if (getGroups(graph).some((item) => item.flags?.[AUTO_GROUP_FLAG] && !isPinned(item))) {
            options.push(null, { content: "清除自动分组", callback: () => clearAutoGroups(canvas, graph) });
        }
        return [null, { content: MENU_TITLE, has_submenu: true, submenu: { options } }];
    },
});
