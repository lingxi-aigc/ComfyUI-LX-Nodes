const DRAG_TYPE = "application/x-lx-workflow-paths+json";
const STORAGE_KEY = `lx.workflow-library.expanded:${location.pathname}`;
const ORDER_STORAGE_KEY = `lx.workflow-library.order:${location.pathname}`;
const PIN_STORAGE_KEY = `lx.workflow-library.pinned:${location.pathname}`;
const ROOT_LABEL = "工作流根目录";
const HOVER_EXPAND_MS = 420;
let lastSearch = "";

function element(tag, className, text, testId) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    if (testId) result.dataset.testid = `workflow-library-${testId}`;
    return result;
}

function button(text, callback, testId, className = "") {
    const result = element("button", `lx-wl-button ${className}`, text, testId);
    result.type = "button";
    result.addEventListener("click", callback);
    return result;
}

function pathName(path) {
    return path.slice(path.lastIndexOf("/") + 1);
}

function displayEntryName({ name, type }) {
    return type === "file" ? name.replace(/\.json$/i, "") || name : name;
}

function parentPath(path) {
    return path.slice(0, Math.max(0, path.lastIndexOf("/")));
}

function joinPath(parent, name) {
    return parent ? `${parent}/${name}` : name;
}

function readPaths(key) {
    try {
        const value = JSON.parse(localStorage.getItem(key) || "[]");
        return new Set(Array.isArray(value) ? value.filter((path) => typeof path === "string") : []);
    } catch {
        return new Set();
    }
}

function savePaths(key, paths) {
    try {
        localStorage.setItem(key, JSON.stringify([...paths]));
    } catch {
        // Keep the state for this session when storage is disabled.
    }
}

function readManualOrder() {
    try {
        const saved = JSON.parse(localStorage.getItem(ORDER_STORAGE_KEY) || "[]");
        return new Map(saved.filter((entry) => Array.isArray(entry) && typeof entry[0] === "string"
            && Array.isArray(entry[1]) && entry[1].every((path) => typeof path === "string")));
    } catch {
        return new Map();
    }
}

function saveManualOrder(order) {
    try {
        localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify([...order]));
    } catch {
        // Keep the order for this session when storage is disabled.
    }
}

function sortName(name) {
    // Treat spacing around chapter separators like `LX定制 》》 16.` as decorative.
    return name.normalize("NFKC").replace(/\s*[〉》>»]+\s*(?=\d)/gu, "》");
}

const nameOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function sortChildren(children, order = [], pinned = null) {
    const ranks = new Map(order.map((path, index) => [path, index]));
    return children.sort((a, b) => Number(pinned?.has(b.path) ?? false) - Number(pinned?.has(a.path) ?? false)
        || (ranks.get(a.path) ?? order.length) - (ranks.get(b.path) ?? order.length)
        || Number(b.type === "directory") - Number(a.type === "directory")
        || nameOrder.compare(sortName(a.name), sortName(b.name))
        || nameOrder.compare(a.name, b.name));
}

function installStyles() {
    const url = new URL("./panel.css", import.meta.url).href;
    if ([...document.head.querySelectorAll("link[data-lx-workflow-library]")].some((link) => link.href === url)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    link.dataset.lxWorkflowLibrary = "";
    document.head.append(link);
}

function makeTree(entries, manualOrder, pinned) {
    const records = new Map([["", { path: "", name: ROOT_LABEL, type: "directory", children: [] }]]);
    function ensureDirectory(path) {
        if (records.has(path)) return records.get(path);
        const parent = ensureDirectory(parentPath(path));
        const entry = { path, name: pathName(path), type: "directory", children: [] };
        records.set(path, entry);
        parent.children.push(entry);
        return entry;
    }
    for (const entry of entries) {
        if (!entry.path) continue;
        if (entry.type === "directory") {
            const directory = ensureDirectory(entry.path);
            directory.name = entry.name;
            directory.stamp = entry.stamp;
        } else if (!records.has(entry.path)) {
            const parent = ensureDirectory(parentPath(entry.path));
            const file = { ...entry, children: [] };
            records.set(file.path, file);
            parent.children.push(file);
        }
    }
    const sorted = [];
    function walk(parent, depth) {
        sortChildren(parent.children, manualOrder.get(parent.path), pinned);
        let workflows = 0;
        for (const child of parent.children) {
            child.depth = depth;
            child.parent = parent.path;
            sorted.push(child);
            if (child.type === "directory") {
                child.workflowCount = walk(child, depth + 1);
                workflows += child.workflowCount;
            } else if (/\.json$/i.test(child.path)) {
                workflows++;
            }
        }
        return workflows;
    }
    walk(records.get(""), 1);
    return { records, sorted };
}

function fileIcon(name, className = "") {
    const result = element("span", `lx-wl-glyph lx-wl-file-glyph pi pi-${name} ${className}`);
    result.setAttribute("aria-hidden", "true");
    return result;
}

function nativeIcon(name, className = "") {
    const result = element("span", `lx-wl-glyph icon-[lucide--${name}] ${className}`);
    result.setAttribute("aria-hidden", "true");
    return result;
}

function toolbarButton(name, label, callback, testId) {
    const control = button(undefined, callback, testId, "lx-wl-square");
    control.append(nativeIcon(name));
    control.setAttribute("aria-label", label);
    control.title = label;
    return control;
}

export function mountWorkflowPanel(container, actions) {
    installStyles();
    let manualOrder = readManualOrder();
    let pinned = readPaths(PIN_STORAGE_KEY);
    let data = { entries: [], showNative: true, busy: false };
    let entries = makeTree([], manualOrder, pinned);
    let selected = new Set();
    let expanded = readPaths(STORAGE_KEY);
    let selectionAnchor = null;
    let focusedPath = "";
    let tabStop = null;
    let rows = new Map();
    let visiblePaths = [];
    let visibleIndex = new Map();
    let searchText = lastSearch.trim().toLocaleLowerCase();
    let dragPaths = [];
    let dropTarget = null;
    let hoverTimer = null;
    let pendingMove = null;
    let contextOrigin = null;

    const root = element("section", "lx-wl");
    root.dataset.testid = "workflow-library";
    root.setAttribute("aria-label", "工作流管理");
    const header = element("header", "lx-wl-header", undefined, "header");
    const heading = element("h2", "lx-wl-heading", "工作流");
    heading.title = "工作流管理";
    const headerButtons = element("div", "lx-wl-header-buttons");
    const newFolder = toolbarButton("folder-plus", "新建文件夹", () => showCreate(""), "new-folder");
    newFolder.title = "在根目录新建文件夹";
    newFolder.classList.add("lx-wl-create-button");
    newFolder.append(element("span", "lx-wl-create-label", "新建文件夹"));
    const refresh = toolbarButton("refresh-cw", "重新扫描工作流文件", () => actions.refresh(), "refresh");
    const more = element("details", "lx-wl-more");
    const moreButton = element("summary", "lx-wl-button lx-wl-square", undefined, "more");
    moreButton.append(nativeIcon("ellipsis"));
    moreButton.setAttribute("aria-label", "更多设置");
    moreButton.title = "更多设置";
    const moreContent = element("div", "lx-wl-more-content");
    const nativeLabel = element("label", "lx-wl-check");
    const nativeCheckbox = element("input", "", undefined, "native");
    nativeCheckbox.type = "checkbox";
    nativeCheckbox.addEventListener("change", () => actions.setShowNative(nativeCheckbox.checked));
    nativeLabel.append(nativeCheckbox, document.createTextNode("显示原生工作流入口"));
    moreContent.append(nativeLabel);
    more.append(moreButton, moreContent);
    headerButtons.append(newFolder, refresh, more);
    header.append(heading, headerButtons);

    const searchBox = element("div", "lx-wl-search-box");
    const search = element("input", "lx-wl-search", undefined, "search");
    search.type = "search";
    search.placeholder = "搜索工作流…";
    search.value = lastSearch;
    search.setAttribute("aria-label", "搜索工作流或文件夹");
    search.addEventListener("input", () => {
        lastSearch = search.value;
        const next = lastSearch.trim().toLocaleLowerCase();
        if (searchText === next) return;
        searchText = next;
        updateVisibility();
    });
    searchBox.append(nativeIcon("search"), search);

    const browseHeading = element("h3", "lx-wl-browse-heading", "浏览", "browse-heading");
    const files = element("div", "lx-wl-files scrollbar-custom", undefined, "files");
    files.tabIndex = 0;
    files.setAttribute("role", "region");
    files.setAttribute("aria-label", "工作流文件区");
    const tree = element("div", "lx-wl-tree", undefined, "tree");
    tree.setAttribute("role", "tree");
    tree.setAttribute("aria-label", "工作流文件");
    tree.setAttribute("aria-multiselectable", "true");
    const empty = element("p", "lx-wl-empty");
    files.append(tree, empty);

    const status = element("div", "lx-wl-status", undefined, "status");
    status.role = "status";
    const dialog = element("dialog", "lx-wl-dialog", undefined, "dialog");
    const contextMenu = element("div", "lx-wl-context-menu", undefined, "context-menu");
    contextMenu.role = "menu";
    contextMenu.setAttribute("aria-label", "工作流管理操作");
    if (typeof contextMenu.showPopover === "function") contextMenu.setAttribute("popover", "manual");
    contextMenu.hidden = true;
    root.append(header, searchBox, browseHeading, files, status, dialog, contextMenu);
    container.classList.add("lx-wl-host");
    container.append(root);
    const focusSearch = requestAnimationFrame(() => {
        if (search.isConnected && search.getClientRects().length && !root.contains(document.activeElement)) {
            search.focus({ preventScroll: true });
        }
    });
    header.addEventListener("contextmenu", handleContextMenu);
    browseHeading.addEventListener("contextmenu", handleContextMenu);
    files.addEventListener("contextmenu", handleContextMenu);
    files.addEventListener("dragover", handleDragOver);
    files.addEventListener("dragleave", (event) => {
        if (!files.contains(event.relatedTarget)) markDrop(null);
    });
    files.addEventListener("drop", handleDrop);
    files.addEventListener("click", (event) => {
        if (!event.target.closest?.(".lx-wl-row")) clearSelection();
    });
    files.addEventListener("keydown", (event) => {
        if (event.target === files && isContextKey(event)) openKeyboardContext(event, "", files);
    });
    document.addEventListener("pointerdown", closeContextOutside, true);

    function selectedPaths() {
        return [...selected].filter((path) => {
            const entry = entries.records.get(path);
            if (!entry) return false;
            for (let parent = entry.parent; parent; parent = entries.records.get(parent).parent) {
                if (selected.has(parent)) return false;
            }
            return true;
        });
    }

    function closeContextMenu(restoreFocus = false) {
        if (contextMenu.hidden) return;
        contextMenu.hidePopover?.();
        contextMenu.hidden = true;
        if (restoreFocus) contextOrigin?.focus({ preventScroll: true });
        contextOrigin = null;
    }

    function closeContextOutside(event) {
        if (!contextMenu.contains(event.target)) closeContextMenu();
    }

    function openContextMenu(path, x, y) {
        if (data.busy) return;
        const entry = entries.records.get(path);
        if (path && !entry) return;
        closeContextMenu();
        contextOrigin = path ? rows.get(path) : files;
        if (path && !selected.has(path)) selectPath(path);
        const paths = selectedPaths();
        function item(label, iconName, testId, action) {
            const control = button(label, () => {
                closeContextMenu(true);
                action();
            }, testId, "lx-wl-context-item");
            control.role = "menuitem";
            control.tabIndex = -1;
            control.prepend(nativeIcon(iconName));
            return control;
        }
        function separator() {
            const line = element("div", "lx-wl-context-separator");
            line.role = "separator";
            return line;
        }
        const items = [];
        if (!path || entry.type === "directory") {
            items.push(item(path ? "新建子文件夹" : "新建文件夹", "folder-plus", "context-new-folder",
                () => showCreate(path)));
        } else {
            items.push(item("打开", "folder-open", "context-open", () => actions.open(path)));
            const isPinned = pinned.has(path);
            items.push(item(isPinned ? "取消置顶" : "置顶", isPinned ? "pin-off" : "pin", "context-pin", () => {
                if (isPinned) pinned.delete(path);
                else pinned.add(path);
                savePaths(PIN_STORAGE_KEY, pinned);
                render({}, true);
            }));
        }
        const sortParent = entry.type === "directory" ? path : entry.parent;
        if (manualOrder.has(sortParent)) {
            items.push(item("恢复默认排序", "arrow-down-a-z", "context-reset-order", () => {
                manualOrder.delete(sortParent);
                saveManualOrder(manualOrder);
                render({}, true);
            }));
        }
        if (path) {
            const moveLabel = paths.length > 1 ? `移动 ${paths.length} 项到…` : "移动到…";
            items.push(
                separator(),
                item("重命名", "pencil", "context-rename", () => showRename(entry)),
                item(moveLabel, "folder-input", "context-move", () => showMovePicker(paths)),
                separator(),
                item("删除", "trash-2", "context-delete", () => showDelete(entry)),
            );
        }
        contextMenu.replaceChildren(...items);
        contextMenu.hidden = false;
        contextMenu.showPopover?.();
        const { width, height } = contextMenu.getBoundingClientRect();
        contextMenu.style.left = `${Math.max(4, Math.min(x, document.documentElement.clientWidth - width - 4))}px`;
        contextMenu.style.top = `${Math.max(4, Math.min(y, document.documentElement.clientHeight - height - 4))}px`;
        items[0]?.focus({ preventScroll: true });
    }

    function isContextKey(event) {
        return event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");
    }

    function openKeyboardContext(event, path, origin) {
        event.preventDefault();
        event.stopPropagation();
        const bounds = origin.getBoundingClientRect();
        openContextMenu(path, bounds.left + 8, Math.min(bounds.bottom, bounds.top + 34));
    }

    function handleContextMenu(event) {
        if (event.target.closest?.("input, textarea, select, [contenteditable=true], .lx-wl-more-content")) return;
        event.preventDefault();
        event.stopPropagation();
        const row = event.target.closest?.(".lx-wl-row");
        const path = row?.dataset.path || "";
        if (!event.clientX && !event.clientY) {
            openKeyboardContext(event, path, row || files);
        } else {
            openContextMenu(path, event.clientX, event.clientY);
        }
    }

    contextMenu.addEventListener("keydown", (event) => {
        if (event.key === "Tab") {
            closeContextMenu(true);
            event.stopPropagation();
            return;
        }
        const items = [...contextMenu.querySelectorAll('[role="menuitem"]')];
        const index = items.indexOf(document.activeElement);
        if (event.key === "Escape") {
            closeContextMenu(true);
        } else if (event.key === "ArrowDown") {
            items[(index + 1) % items.length]?.focus();
        } else if (event.key === "ArrowUp") {
            items[(index + items.length - 1) % items.length]?.focus();
        } else if (event.key === "Home") {
            items[0]?.focus();
        } else if (event.key === "End") {
            items.at(-1)?.focus();
        } else {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
    });

    function setExpanded(path, value) {
        if (!path || expanded.has(path) === value) return;
        if (value) expanded.add(path);
        else expanded.delete(path);
        savePaths(STORAGE_KEY, expanded);
        updateVisibility();
    }

    function setFocus(path, moveFocus = false, preventScroll = false) {
        focusedPath = path;
        const row = path ? rows.get(path) : null;
        if (tabStop !== row) {
            if (tabStop) tabStop.tabIndex = -1;
            if (row) row.tabIndex = 0;
            tabStop = row;
        }
        if (moveFocus && row && row !== document.activeElement) row.focus({ preventScroll });
    }

    function updateControls() {
        if (newFolder.disabled !== data.busy) newFolder.disabled = data.busy;
        if (refresh.disabled !== data.busy) refresh.disabled = data.busy;
        if (nativeCheckbox.checked !== data.showNative) nativeCheckbox.checked = data.showNative;
        const showingDrop = dropTarget !== null;
        const targetEntry = showingDrop && entries.records.get(dropTarget.highlight);
        const message = !showingDrop ? data.message || "" : dropTarget.position && targetEntry
            ? `放到「${displayEntryName(targetEntry)}」${dropTarget.position === "before" ? "前面" : "后面"}`
            : `移动到：${dropTarget.path || ROOT_LABEL}`;
        if (status.classList.contains("is-drag-status") !== showingDrop) {
            status.classList.toggle("is-drag-status", showingDrop);
        }
        if (status.textContent !== message) status.textContent = message;
        if (status.hidden !== !message) status.hidden = !message;
        const busy = String(data.busy);
        if (root.getAttribute("aria-busy") !== busy) root.setAttribute("aria-busy", busy);
        const rootDrop = rows.get("");
        const hideDrop = !legalDrop(dragPaths, "");
        if (rootDrop && rootDrop.hidden !== hideDrop) rootDrop.hidden = hideDrop;
    }

    function searchMatches() {
        if (!searchText) return null;
        const matches = new Set();
        for (const entry of entries.sorted) {
            const name = entry.searchName ??= entry.name.toLocaleLowerCase();
            const path = entry.searchPath ??= entry.path.toLocaleLowerCase();
            if (!name.includes(searchText) && !path.includes(searchText)) continue;
            for (let item = entry; item?.path && !matches.has(item.path); item = entries.records.get(item.parent)) {
                matches.add(item.path);
            }
        }
        return matches;
    }

    function updateVisibility() {
        const matches = searchMatches();
        visiblePaths = [];
        visibleIndex = new Map();
        for (const entry of entries.sorted) {
            const { path, parent } = entry;
            const row = rows.get(path);
            const visible = matches
                ? matches.has(path)
                : !parent || (visibleIndex.has(parent) && expanded.has(parent));
            if (visible) {
                visibleIndex.set(path, visiblePaths.length);
                visiblePaths.push(path);
            }
            if (row.hidden !== !visible) row.hidden = !visible;
            if (entry.type === "directory") {
                const open = String(expanded.has(path) || Boolean(matches));
                if (row.getAttribute("aria-expanded") !== open) row.setAttribute("aria-expanded", open);
            }
        }
        if (!visibleIndex.has(focusedPath)) focusedPath = visiblePaths[0] || "";
        setFocus(focusedPath);
        const emptyMessage = searchText ? "没有匹配的工作流" : "这里还没有工作流";
        if (empty.textContent !== emptyMessage) empty.textContent = emptyMessage;
        if (empty.hidden !== Boolean(visiblePaths.length)) empty.hidden = Boolean(visiblePaths.length);
    }

    function updateSelection(before) {
        for (const path of before) {
            if (!selected.has(path)) rows.get(path)?.setAttribute("aria-selected", "false");
        }
        for (const path of selected) {
            if (!before.has(path)) rows.get(path)?.setAttribute("aria-selected", "true");
        }
    }

    function clearSelection() {
        const before = selected;
        selected = new Set();
        selectionAnchor = null;
        updateSelection(before);
    }

    function selectPath(path, event = {}) {
        if (!path || !entries.records.has(path)) return;
        const before = selected;
        const additive = event.ctrlKey || event.metaKey;
        if (event.shiftKey && visibleIndex.has(selectionAnchor) && visibleIndex.has(path)) {
            const from = visibleIndex.get(selectionAnchor);
            const to = visibleIndex.get(path);
            const range = visiblePaths.slice(Math.min(from, to), Math.max(from, to) + 1);
            selected = additive ? new Set([...selected, ...range]) : new Set(range);
        } else {
            if (additive) {
                selected = new Set(before);
                if (selected.has(path)) selected.delete(path);
                else selected.add(path);
            } else {
                selected = new Set([path]);
            }
            selectionAnchor = path;
        }
        setFocus(path);
        updateSelection(before);
    }

    function activate(path) {
        if (data.busy) return;
        const entry = entries.records.get(path);
        if (entry.type === "directory") {
            setExpanded(path, !expanded.has(path));
        } else {
            actions.open(path);
        }
    }

    function legalDrop(paths, target) {
        return !data.busy && entries.records.get(target)?.type === "directory"
            && paths.length > 0
            && paths.every((path) => path && entries.records.has(path) && target !== path && !target.startsWith(`${path}/`))
            && paths.some((path) => parentPath(path) !== target);
    }

    function highlightClass(target) {
        return target.position ? `is-drop-${target.position}` : "is-drop-target";
    }

    function markDrop(target) {
        if (dropTarget?.path === target?.path && dropTarget?.highlight === target?.highlight
            && dropTarget?.position === target?.position) return;
        if (dropTarget) rows.get(dropTarget.highlight)?.classList.remove(highlightClass(dropTarget));
        if (hoverTimer !== null) clearTimeout(hoverTimer);
        hoverTimer = null;
        dropTarget = target;
        if (target) rows.get(target.highlight)?.classList.add(highlightClass(target));
        if (target && !target.position && target.path && !expanded.has(target.path)) {
            hoverTimer = setTimeout(() => {
                hoverTimer = null;
                if (dropTarget === target) setExpanded(target.path, true);
            }, HOVER_EXPAND_MS);
        }
        updateControls();
    }

    function dropRow(event) {
        const rowAt = (element) => {
            const row = element?.closest?.(".lx-wl-row");
            return row && !row.hidden && tree.contains(row) ? row : null;
        };
        const direct = rowAt(event.target);
        if (direct) return direct;
        // A hit in the tree's narrow gutter or next to the final row still uses
        // the adjoining visible row. Probe within the pane, not the whole tree.
        const { left, top, bottom, width } = files.getBoundingClientRect();
        const x = left + width / 2;
        for (const offset of [0, -3, 3, -7, 7, -12, 12]) {
            const y = event.clientY + offset;
            if (y < top || y >= bottom) continue;
            const row = rowAt(document.elementFromPoint(x, y));
            if (row) return row;
        }
        return null;
    }

    function dropDestination(row, paths, y) {
        if (!row || rows.get(row.dataset.path) !== row) return null;
        const entry = entries.records.get(row.dataset.path);
        if (!entry) return null;
        if (entry.path && !data.busy && paths.length && !paths.includes(entry.path)
            && paths.every((path) => entries.records.get(path)?.parent === entry.parent
                && pinned.has(path) === pinned.has(entry.path))) {
            const bounds = row.getBoundingClientRect();
            const fraction = (y - bounds.top) / (bounds.height || 1);
            // Folder edges reorder siblings. Its centre keeps the move-into-folder action.
            if (entry.type === "file" || fraction <= 0.25 || fraction >= 0.75) {
                return { path: entry.parent, highlight: entry.path, position: fraction < 0.5 ? "before" : "after" };
            }
        }
        const destination = entry.type === "directory" ? entry.path : entry.parent;
        return legalDrop(paths, destination) ? { path: destination, highlight: entry.path } : null;
    }

    function handleDragOver(event) {
        if (!event.dataTransfer?.types.includes(DRAG_TYPE)) return;
        const target = dropDestination(dropRow(event), dragPaths, event.clientY);
        markDrop(target);
        if (!target) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
    }

    function handleDrop(event) {
        if (!event.dataTransfer?.types.includes(DRAG_TYPE)) return;
        event.preventDefault();
        let paths;
        try {
            paths = JSON.parse(event.dataTransfer.getData(DRAG_TYPE));
        } catch {
            paths = [];
        }
        const target = Array.isArray(paths) && paths.every((item) => typeof item === "string")
            ? dropDestination(dropRow(event), paths, event.clientY) : null;
        endDrag();
        if (!target) return;
        if (target.position) reorderSiblings(paths, target);
        else void movePaths(paths, target.path);
    }

    function reorderSiblings(paths, { path, highlight, position }) {
        const children = entries.records.get(path).children;
        const siblings = sortChildren([...children], manualOrder.get(path)).map((entry) => entry.path);
        const candidates = new Set(paths);
        const sorted = siblings.filter((sibling) => !candidates.has(sibling));
        const insertion = sorted.indexOf(highlight) + Number(position === "after");
        sorted.splice(insertion, 0, ...siblings.filter((sibling) => candidates.has(sibling)));
        if (sorted.every((sibling, index) => sibling === siblings[index])) return;
        manualOrder.set(path, sorted);
        saveManualOrder(manualOrder);
        render({}, true);
    }

    function showDragPreview(event) {
        if (dragPaths.length < 2) return;
        const preview = element("div", "lx-wl-drag-preview", `拖动 ${dragPaths.length} 项`);
        preview.setAttribute("aria-hidden", "true");
        preview.style.left = `${event.clientX}px`;
        preview.style.top = `${event.clientY}px`;
        root.append(preview);
        event.dataTransfer.setDragImage(preview, -8, -10);
        requestAnimationFrame(() => preview.remove());
    }

    async function movePaths(paths, target) {
        if (!legalDrop(paths, target)) return false;
        pendingMove = new Map(paths
            .filter((path) => parentPath(path) !== target)
            .map((path) => [path, joinPath(target, pathName(path))]));
        try {
            const result = await actions.move(paths, target);
            if (result === false) pendingMove = null;
            return result;
        } catch {
            pendingMove = null;
            return false;
        }
    }

    function updatePin(row, entry) {
        if (entry.type !== "file") return;
        const marker = row.querySelector(".lx-wl-pin");
        if (pinned.has(entry.path)) {
            if (!marker) {
                const icon = nativeIcon("pin", "lx-wl-pin");
                icon.title = "已置顶";
                row.querySelector(".lx-wl-entry-label").append(icon);
            }
            row.setAttribute("aria-label", `${displayEntryName(entry)}，已置顶`);
        } else if (marker) {
            marker.remove();
            row.removeAttribute("aria-label");
        }
    }

    function remapPresentation(remap) {
        const nextPins = new Set([...pinned].map(remap).filter((path) => path !== null));
        const pinsChanged = nextPins.size !== pinned.size || [...nextPins].some((path) => !pinned.has(path));
        if (pinsChanged) {
            pinned = nextPins;
            savePaths(PIN_STORAGE_KEY, pinned);
        }

        let orderChanged = false;
        const nextOrder = new Map();
        for (const [folder, order] of manualOrder) {
            const nextFolder = remap(folder);
            if (nextFolder === null) {
                orderChanged = true;
                continue;
            }
            const nextPaths = order.map(remap).filter((path) => path !== null && parentPath(path) === nextFolder);
            if (nextPaths.length) nextOrder.set(nextFolder, nextPaths);
            if (nextFolder !== folder || nextPaths.length !== order.length || nextPaths.some((path, index) => path !== order[index])) {
                orderChanged = true;
            }
        }
        if (orderChanged) {
            manualOrder = nextOrder;
            saveManualOrder(manualOrder);
        }
        return pinsChanged || orderChanged;
    }

    function createRow(entry) {
        const { path, type, depth = 0 } = entry;
        const row = element("div", `lx-wl-row lx-wl-${type}${path ? "" : " lx-wl-root-row"}`, undefined, path ? "entry" : "root");
        row.dataset.path = path;
        row.dataset.type = type;
        row.style.setProperty("--lx-depth", Math.max(0, depth - 1));
        row.title = path || `${ROOT_LABEL}（可拖入）`;
        if (path) {
            row.tabIndex = -1;
            row.role = "treeitem";
            row.setAttribute("aria-level", String(depth));
            row.setAttribute("aria-keyshortcuts", "Shift+F10");
            row.setAttribute("aria-selected", String(selected.has(path)));
            if (path === data.activePath) row.classList.add("is-active");
        } else {
            row.hidden = true;
            row.setAttribute("aria-hidden", "true");
        }
        if (path === dropTarget?.highlight) row.classList.add(highlightClass(dropTarget));
        if (path && type === "directory") {
            const chevron = element("button", "lx-wl-tree-slot lx-wl-twisty");
            chevron.type = "button";
            chevron.tabIndex = -1;
            chevron.setAttribute("aria-hidden", "true");
            chevron.append(nativeIcon("chevron-right"));
            chevron.addEventListener("click", (event) => {
                event.stopPropagation();
                setFocus(path, true);
                setExpanded(path, !expanded.has(path));
            });
            row.append(chevron);
        } else {
            const spacer = element("span", "lx-wl-tree-slot");
            spacer.setAttribute("aria-hidden", "true");
            row.append(spacer);
        }
        if (type === "directory") {
            row.append(fileIcon("folder", "lx-wl-folder-closed"), fileIcon("folder-open", "lx-wl-folder-open"));
        } else {
            row.append(fileIcon("file"));
        }
        const displayName = path ? displayEntryName(entry) : "移到根目录";
        const label = element("span", "lx-wl-entry-label");
        label.append(element("span", "lx-wl-name", displayName));
        if (path && type === "directory") {
            const count = element("span", "lx-wl-folder-count", String(entry.workflowCount), "folder-count");
            count.setAttribute("aria-hidden", "true");
            row.setAttribute("aria-label", `${displayName}，${entry.workflowCount} 个工作流`);
            label.append(count);
        }
        row.append(label);
        updatePin(row, entry);
        if (path) {
            row.addEventListener("focus", () => setFocus(path));
            row.addEventListener("click", (event) => {
                if (event.detail > 1) return;
                selectPath(path, event);
                if (!event.ctrlKey && !event.metaKey && !event.shiftKey) activate(path);
            });
            row.draggable = true;
            row.addEventListener("dragstart", (event) => {
                if (data.busy || !event.dataTransfer) {
                    event.preventDefault();
                    return;
                }
                if (!selected.has(path)) selectPath(path);
                dragPaths = selectedPaths();
                rows.get("").hidden = !legalDrop(dragPaths, "");
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(dragPaths));
                showDragPreview(event);
                for (const source of dragPaths) rows.get(source)?.classList.add("is-dragging");
            });
            row.addEventListener("dragend", endDrag);
        }
        return row;
    }

    function endDrag() {
        for (const source of dragPaths) rows.get(source)?.classList.remove("is-dragging");
        dragPaths = [];
        markDrop(null);
        if (rows.has("")) rows.get("").hidden = true;
    }

    tree.addEventListener("keydown", (event) => {
        const path = focusedPath;
        if (!path) return;
        if (isContextKey(event)) {
            openKeyboardContext(event, path, rows.get(path));
            return;
        }
        const entry = entries.records.get(path);
        const index = visibleIndex.get(path);
        switch (event.key) {
            case "ArrowDown":
            case "ArrowUp": {
                const step = event.key === "ArrowDown" ? 1 : -1;
                const next = visiblePaths[Math.max(0, Math.min(visiblePaths.length - 1, index + step))];
                if (event.shiftKey) selectPath(next, { shiftKey: true });
                setFocus(next, true);
                break;
            }
            case "Home":
                setFocus(visiblePaths[0], true);
                break;
            case "End":
                setFocus(visiblePaths.at(-1), true);
                break;
            case "ArrowRight":
                if (entry?.type === "directory" && path && !expanded.has(path)) setExpanded(path, true);
                else if (entry?.type === "directory") {
                    const child = visiblePaths[index + 1];
                    if (child && parentPath(child) === path) setFocus(child, true);
                }
                break;
            case "ArrowLeft":
                if (path && entry?.type === "directory" && expanded.has(path)) setExpanded(path, false);
                else if (parentPath(path)) setFocus(parentPath(path), true);
                break;
            case " ":
                selectPath(path, { ctrlKey: true });
                break;
            case "Enter":
                if (path) activate(path);
                break;
            case "Escape":
                if (!selected.size) return;
                clearSelection();
                event.stopPropagation();
                break;
            default:
                return;
        }
        event.preventDefault();
    });

    function showDialog(title, submitText, contents, submit, focus, { destructive = false, onSuccess } = {}) {
        if (dialog.open) return;
        dialog.setAttribute("aria-label", title);
        const form = element("form", "lx-wl-dialog-form");
        const alert = element("p", "lx-wl-dialog-error");
        alert.role = "alert";
        alert.hidden = true;
        const actionsRow = element("div", "lx-wl-dialog-actions");
        const cancel = button("取消", () => dialog.close(), "dialog-cancel");
        const confirmClass = destructive ? "lx-wl-danger-button" : "lx-wl-primary";
        const confirm = element("button", `lx-wl-button ${confirmClass}`, submitText, "dialog-submit");
        confirm.type = "submit";
        actionsRow.append(cancel, confirm);
        form.append(element("h3", "lx-wl-dialog-title", title), contents, alert, actionsRow);
        dialog.oncancel = (event) => {
            if (destructive && confirm.disabled) event.preventDefault();
        };
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (confirm.disabled) return;
            alert.hidden = true;
            confirm.disabled = true;
            if (destructive) cancel.disabled = true;
            let result;
            try {
                result = await submit();
                if (result === false) throw new Error(data.message || "操作未完成，请检查名称或目标。");
            } catch (error) {
                alert.textContent = error instanceof Error ? error.message : "操作失败";
                alert.hidden = false;
                confirm.disabled = false;
                cancel.disabled = false;
                return;
            }
            dialog.close();
            onSuccess?.(result);
        });
        dialog.replaceChildren(form);
        dialog.showModal();
        (focus ?? (destructive ? cancel : null))?.focus();
    }

    function showCreate(parent) {
        const contents = element("div", "lx-wl-dialog-fields");
        contents.append(element("p", "lx-wl-dialog-path", `位置：${parent || ROOT_LABEL}`));
        const label = element("label", "lx-wl-field", "文件夹名称");
        const input = element("input", "lx-wl-name-input", undefined, "folder-name");
        input.type = "text";
        input.required = true;
        label.append(input);
        contents.append(label);
        showDialog("新建文件夹", "创建", contents, async () => {
            const name = input.value.trim();
            if (!name || /[\\/]/.test(name)) throw new Error("请输入一个文件夹名称，不能包含路径分隔符。");
            const result = await actions.create(parent, name);
            if (result === false) return false;
            if (parent) setExpanded(parent, true);
            return true;
        }, input);
    }

    function showRename(entry) {
        const contents = element("div", "lx-wl-dialog-fields");
        contents.append(element("p", "lx-wl-dialog-path", `当前位置：${entry.path}`));
        const isFolder = entry.type === "directory";
        const label = element("label", "lx-wl-field", isFolder ? "文件夹名称" : "工作流名称");
        const input = element("input", "lx-wl-name-input", undefined, "rename-name");
        const original = displayEntryName(entry);
        const belongsToEntry = (path) => path === entry.path || path.startsWith(`${entry.path}/`);
        const renamedSelection = [...selected].filter(belongsToEntry);
        input.type = "text";
        input.required = true;
        input.value = original;
        label.append(input);
        contents.append(label);
        showDialog(isFolder ? "重命名文件夹" : "重命名工作流", "保存", contents, () => {
            const name = input.value.trim();
            if (!name || /[\\/]/.test(name)) throw new Error("请输入一个名称，不能包含路径分隔符。");
            return name === original || actions.rename(entry.path, name, entry.stamp);
        }, input, { onSuccess: (nextPath) => {
            if (typeof nextPath !== "string" || nextPath === entry.path || !entries.records.has(nextPath)) return;
            const remap = (path) => belongsToEntry(path) ? nextPath + path.slice(entry.path.length) : path;
            const before = selected;
            selected = new Set([...selected, ...renamedSelection.map(remap)].filter((path) => entries.records.has(path)));
            expanded = new Set([...expanded].map(remap));
            if (selectionAnchor) selectionAnchor = remap(selectionAnchor);
            focusedPath = nextPath;
            savePaths(STORAGE_KEY, expanded);
            if (remapPresentation(remap)) render({}, true);
            updateSelection(before);
            updateVisibility();
            setFocus(focusedPath, true);
        } });
        input.select();
    }

    function showDelete(entry) {
        const isFolder = entry.type === "directory";
        const contents = element("div", "lx-wl-dialog-fields");
        contents.append(
            element("p", "lx-wl-delete-target", entry.path, "delete-target"),
            element("p", "lx-wl-dialog-path", isFolder
                ? "此文件夹和其中的所有文件及子文件夹将移到灵犀的本地回收目录。"
                : "此工作流将从磁盘永久删除。打开的标签会关闭，未保存的修改会丢失。"),
        );
        showDialog(isFolder ? "删除文件夹" : "删除工作流", "删除", contents,
            () => actions.remove(entry.path, entry.stamp), null, { destructive: true, onSuccess: () => {
                const remove = (path) => path === entry.path || path.startsWith(`${entry.path}/`) ? null : path;
                if (remapPresentation(remove)) render({}, true);
            } });
    }

    function showMovePicker(paths) {
        if (!paths.length) return;
        const contents = element("div", "lx-wl-dialog-fields");
        contents.append(element("p", "lx-wl-dialog-path", `选择 ${paths.length} 项的目标文件夹`));
        const choices = element("div", "lx-wl-move-choices");
        let target = null;
        const options = [];
        for (const entry of [entries.records.get(""), ...entries.sorted]) {
            const path = entry.path;
            if (!legalDrop(paths, path)) continue;
            const option = button(path || ROOT_LABEL, () => {
                target = path;
                for (const item of options) item.setAttribute("aria-pressed", String(item === option));
            }, "move-target", "lx-wl-move-option");
            option.dataset.path = path;
            option.title = path || ROOT_LABEL;
            option.setAttribute("aria-pressed", "false");
            choices.append(option);
            options.push(option);
        }
        if (!options.length) choices.append(element("p", "lx-wl-empty", "没有可移动到的文件夹。"));
        contents.append(choices);
        showDialog("移动到文件夹", "移动", contents, () => {
            if (target === null) throw new Error("请选择目标文件夹。");
            return movePaths(paths, target);
        }, options[0]);
    }

    function reconcileRows(previousEntries) {
        const nextRows = new Map();
        for (const entry of [entries.records.get(""), ...entries.sorted]) {
            const previous = previousEntries.records.get(entry.path);
            const row = rows.get(entry.path);
            if (!row || previous?.type !== entry.type) {
                nextRows.set(entry.path, createRow(entry));
                continue;
            }
            nextRows.set(entry.path, row);
            if (previous.depth !== entry.depth) {
                row.style.setProperty("--lx-depth", Math.max(0, entry.depth - 1));
                if (entry.path) row.setAttribute("aria-level", String(entry.depth));
            }
            if (previous.name !== entry.name) row.querySelector(".lx-wl-name").textContent = displayEntryName(entry);
            if (entry.path && entry.type === "directory"
                && (previous.name !== entry.name || previous.workflowCount !== entry.workflowCount)) {
                row.querySelector(".lx-wl-folder-count").textContent = String(entry.workflowCount);
                row.setAttribute("aria-label", `${displayEntryName(entry)}，${entry.workflowCount} 个工作流`);
            }
            updatePin(row, entry);
        }
        for (const [path, row] of rows) {
            if (nextRows.get(path) !== row) row.remove();
        }
        let cursor = tree.firstElementChild;
        const tail = document.createDocumentFragment();
        for (const row of nextRows.values()) {
            if (!cursor) tail.append(row);
            else if (row === cursor) cursor = cursor.nextElementSibling;
            else tree.insertBefore(row, cursor);
        }
        if (tail.hasChildNodes()) tree.append(tail);
        rows = nextRows;
    }

    function render(nextData, orderChanged = false) {
        const before = data;
        data = { ...data, ...nextData };
        const entriesChanged = orderChanged || before.entries !== data.entries || !rows.size;
        if (data.busy || entriesChanged) closeContextMenu();
        if (entriesChanged) {
            const treeHadFocus = tree.contains(document.activeElement);
            const scroll = files.scrollTop;
            const previousEntries = entries;
            const previousSelection = selected;
            entries = makeTree(data.entries, manualOrder, pinned);
            if (pendingMove) {
                const completed = [...pendingMove]
                    .filter(([source, dest]) => !entries.records.has(source) && entries.records.has(dest));
                const remap = (path) => {
                    const match = completed.find(([source]) => path === source || path.startsWith(`${source}/`));
                    return match ? match[1] + path.slice(match[0].length) : path;
                };
                selected = new Set([...selected].map(remap));
                expanded = new Set([...expanded].map(remap));
                focusedPath = remap(focusedPath);
                selectionAnchor = typeof selectionAnchor === "string" ? remap(selectionAnchor) : null;
                if (completed.length) {
                    for (const [, dest] of completed) {
                        for (let parent = parentPath(dest); parent; parent = parentPath(parent)) expanded.add(parent);
                    }
                    savePaths(STORAGE_KEY, expanded);
                    if (remapPresentation(remap)) entries = makeTree(data.entries, manualOrder, pinned);
                }
                if (!data.busy) pendingMove = null;
            }
            selected = new Set([...selected].filter((path) => entries.records.has(path)));
            reconcileRows(previousEntries);
            updateSelection(previousSelection);
            updateVisibility();
            if (files.scrollTop !== scroll) files.scrollTop = scroll;
            if (treeHadFocus) setFocus(focusedPath, true, true);
        }
        if (before.activePath !== data.activePath) {
            rows.get(before.activePath)?.classList.remove("is-active");
            rows.get(data.activePath)?.classList.add("is-active");
        }
        updateControls();
    }

    render(data);
    return {
        render,
        destroy() {
            cancelAnimationFrame(focusSearch);
            endDrag();
            closeContextMenu();
            document.removeEventListener("pointerdown", closeContextOutside, true);
            if (dialog.open) dialog.close();
            root.remove();
            container.classList.remove("lx-wl-host");
        },
    };
}
