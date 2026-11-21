const COLUMN_GAP = 104;
const ROW_GAP = 48;
const COMPONENT_GAP = 64;
const OBSTACLE_GAP = 24;

function compareIds(left, right) {
    const a = left.id;
    const b = right.id;
    if (typeof a === "number") return typeof b === "number" ? a - b : -1;
    if (typeof b === "number") return 1;
    const aText = String(a);
    const bText = String(b);
    return aText < bText ? -1 : aText > bText ? 1 : 0;
}

function connectNodes(nodes, links) {
    const byId = new Map(nodes.map((node) => [String(node.id), node]));
    const incoming = new Map(nodes.map((node) => [node, new Set()]));
    const outgoing = new Map(nodes.map((node) => [node, new Set()]));
    for (const link of links) {
        if (!link) continue;
        const from = byId.get(String(link.origin_id));
        const to = byId.get(String(link.target_id));
        if (!from || !to || from === to) continue;
        outgoing.get(from).add(to);
        incoming.get(to).add(from);
    }
    return { incoming, outgoing };
}

function connectedComponents(nodes, incoming, outgoing) {
    const visited = new Set();
    const components = [];
    for (const node of nodes) {
        if (visited.has(node)) continue;
        const members = [node];
        visited.add(node);
        for (let i = 0; i < members.length; i++) {
            const current = members[i];
            for (const neighbors of [incoming.get(current), outgoing.get(current)]) {
                for (const neighbor of neighbors) {
                    if (visited.has(neighbor)) continue;
                    visited.add(neighbor);
                    members.push(neighbor);
                }
            }
        }
        components.push(members.sort(compareIds));
    }
    return components;
}

function finishingOrder(nodes, outgoing) {
    const visited = new Set();
    const finished = [];
    for (const node of nodes) {
        if (visited.has(node)) continue;
        visited.add(node);
        const stack = [[node, outgoing.get(node).values()]];
        while (stack.length) {
            const [current, neighbors] = stack[stack.length - 1];
            const next = neighbors.next();
            if (next.done) {
                finished.push(current);
                stack.pop();
            } else if (!visited.has(next.value)) {
                visited.add(next.value);
                stack.push([next.value, outgoing.get(next.value).values()]);
            }
        }
    }
    return finished.reverse();
}

function assignRanks(nodes, incoming, outgoing) {
    // Collapse each cycle into one column. The reverse pass visits these groups
    // in topological order, so edges between groups only advance their rank once.
    const groups = [];
    const groupByNode = new Map();
    for (const node of finishingOrder(nodes, outgoing)) {
        if (groupByNode.has(node)) continue;
        const group = { rank: 0, members: [node] };
        groupByNode.set(node, group);
        for (let i = 0; i < group.members.length; i++) {
            for (const neighbor of incoming.get(group.members[i])) {
                if (groupByNode.has(neighbor)) continue;
                groupByNode.set(neighbor, group);
                group.members.push(neighbor);
            }
        }
        groups.push(group);
    }
    for (const group of groups) {
        for (const member of group.members) {
            for (const neighbor of outgoing.get(member)) {
                const target = groupByNode.get(neighbor);
                if (target !== group) target.rank = Math.max(target.rank, group.rank + 1);
            }
        }
    }
    // A short input branch can start one column before its first consumer.
    // This keeps its edge out of earlier stages it does not use.
    for (const group of groups) {
        if (group.rank !== 0) continue;
        let firstConsumer = Infinity;
        for (const member of group.members) {
            for (const neighbor of outgoing.get(member)) {
                const target = groupByNode.get(neighbor);
                if (target !== group) firstConsumer = Math.min(firstConsumer, target.rank);
            }
        }
        if (Number.isFinite(firstConsumer)) group.rank = firstConsumer - 1;
    }
    return new Map(nodes.map((node) => [node, groupByNode.get(node).rank]));
}

function orderColumns(columns, ranks, incoming, outgoing) {
    const positions = new Map();
    const recordPositions = (column) => {
        for (let i = 0; i < column.length; i++) {
            positions.set(column[i], (i + 0.5) / column.length);
        }
    };
    for (const column of columns) recordPositions(column);
    const sweep = (start, end, step, neighbors) => {
        for (let rank = start; rank !== end; rank += step) {
            const column = columns[rank];
            if (column.length < 2) continue;
            const centers = new Map(column.map((node) => {
                let sum = 0;
                let count = 0;
                for (const neighbor of neighbors.get(node)) {
                    if (ranks.get(neighbor) === rank) continue;
                    sum += positions.get(neighbor);
                    count++;
                }
                return [node, count ? sum / count : positions.get(node)];
            }));
            column.sort((a, b) => centers.get(a) - centers.get(b));
            recordPositions(column);
        }
    };
    // A few forward/backward sweeps align branches without changing their ranks.
    for (let pass = 0; pass < 2; pass++) {
        sweep(0, columns.length, 1, incoming);
        sweep(columns.length - 1, -1, -1, outgoing);
    }
}

function measureComponent(nodes, incoming, outgoing, bounds) {
    const ranks = assignRanks(nodes, incoming, outgoing);
    const columns = [];
    for (const node of nodes) {
        const rank = ranks.get(node);
        (columns[rank] ??= []).push(node);
    }
    orderColumns(columns, ranks, incoming, outgoing);
    const sizes = columns.map((column) => {
        let width = 0;
        let height = (column.length - 1) * ROW_GAP;
        for (const node of column) {
            const [, , nodeWidth, nodeHeight] = bounds.get(node);
            width = Math.max(width, nodeWidth);
            height += nodeHeight;
        }
        return { width, height };
    });
    return {
        columns,
        sizes,
        width: sizes.reduce((sum, size) => sum + size.width, (sizes.length - 1) * COLUMN_GAP),
        height: sizes.reduce((max, size) => Math.max(max, size.height), 0),
    };
}

function clearObstacles(left, top, width, height, obstacles) {
    for (const [x, y, w, h] of obstacles) {
        if (y - OBSTACLE_GAP >= top + height) break;
        if (left + width <= x - OBSTACLE_GAP || left >= x + w + OBSTACLE_GAP) continue;
        top = Math.max(top, y + h + OBSTACLE_GAP);
    }
    return top;
}

function placeComponent(component, left, top, bounds, plan) {
    for (let i = 0; i < component.columns.length; i++) {
        const size = component.sizes[i];
        let y = top + (component.height - size.height) / 2;
        for (const node of component.columns[i]) {
            const [oldLeft, oldTop, width, height] = bounds.get(node);
            const x = left + (size.width - width) / 2;
            plan.set(node, [node.pos[0] + x - oldLeft, node.pos[1] + y - oldTop]);
            y += height + ROW_GAP;
        }
        left += size.width + COLUMN_GAP;
    }
}

export function planLayout(nodes, links, bounds, { anchor, obstacles = [] } = {}) {
    const movable = [...nodes].filter((node) => bounds.has(node)).sort(compareIds);
    const plan = new Map();
    if (!movable.length) return plan;

    const { incoming, outgoing } = connectNodes(movable, links);
    const components = connectedComponents(movable, incoming, outgoing).map((members) =>
        measureComponent(members, incoming, outgoing, bounds)
    );
    const [originX, originY] = anchor ?? movable.reduce(([left, top], node) => {
        const [x, y] = bounds.get(node);
        return [Math.min(left, x), Math.min(top, y)];
    }, [Infinity, Infinity]);
    const obstacleRects = [...obstacles].sort((a, b) => a[1] - b[1]);
    const area = components.reduce((total, component) =>
        total + (component.width + COMPONENT_GAP) * (component.height + COMPONENT_GAP), 0
    );
    const widest = components.reduce((max, component) => Math.max(max, component.width), 0);
    const shelfWidth = Math.max(widest, Math.sqrt(area * 1.6));
    let left = originX;
    let top = originY;
    let shelfHeight = 0;
    for (const component of components) {
        if (left > originX && left + component.width > originX + shelfWidth) {
            left = originX;
            top += shelfHeight + COMPONENT_GAP;
            shelfHeight = 0;
        }
        const y = clearObstacles(left, top, component.width, component.height, obstacleRects);
        placeComponent(component, left, y, bounds, plan);
        shelfHeight = Math.max(shelfHeight, y - top + component.height);
        left += component.width + COMPONENT_GAP;
    }
    return plan;
}
