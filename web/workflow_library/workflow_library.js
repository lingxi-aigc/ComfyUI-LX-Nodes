import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import { mountWorkflowPanel } from "./panel.js";

const TAB = "lx-workflow-library";
const SHOW_NATIVE = "LX.WorkflowLibrary.ShowNativeSidebar";
const PREFIX = "workflows/";
const ROUTE = "/lx/workflow-library/";
const HIDE_CLASS = "lx-hide-native-workflows";
const NATIVE_TAB = "workflows";
const NATIVE_BUTTON = '[data-testid="side-toolbar"] [data-testid="workflows-tab-button"]';
const TAB_BUTTON = '[data-testid="lx-workflow-library-tab-button"]';
const FOCUS_COMMAND = "LX.WorkflowLibrary.Focus";

let entries = [];
let mounted;
let busy = false;
let moveNotice;
let message = "";
let sidebarReady = false;
let treeRequest = 0;

const manager = () => app.extensionManager;
const store = () => manager()?.workflow;
const parentOf = (path) => path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
const filename = (path) => path.split("/").at(-1);
const nativePath = (path) => PREFIX + path;
const showNative = () => manager()?.setting?.get(SHOW_NATIVE) !== false;
const isUnder = (path, directory) => path === directory || path?.startsWith(directory + "/");

function notify(detail, severity = "info") {
    const toast = manager()?.toast;
    const kind = severity === "warn" ? "warning" : severity;
    if (typeof toast?.[kind] === "function") toast[kind]("工作流管理", { description: detail, duration: 5200 });
    else toast?.add?.({ summary: "工作流管理", detail, severity: kind === "warning" ? "warn" : kind, life: 5200 });
}

async function callRoute(action, body) {
    const response = await api.fetchApi(ROUTE + action, body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    let result;
    try {
        result = await response.json();
    } catch {
        throw new Error(response.status === 404 ? "工作流管理接口还未注册，请重启 ComfyUI。" : "工作流管理接口返回异常。");
    }
    if (!response.ok || result.error) throw new Error(result.error || `请求失败（${response.status}）。`);
    return result;
}

function activeFile() {
    const path = store()?.activeWorkflow?.path;
    return path?.startsWith(PREFIX) ? path.slice(PREFIX.length) : undefined;
}

function render() {
    if (!mounted) return;
    mounted.activePath = activeFile();
    mounted.panel.render({
        entries,
        showNative: showNative(),
        busy,
        activePath: mounted.activePath,
        message,
    });
}

async function refresh({ quiet = false } = {}) {
    const request = ++treeRequest;
    try {
        const { entries: tree } = await callRoute("tree");
        if (request !== treeRequest) return;
        if (!Array.isArray(tree)) throw new Error("目录列表格式异常。");
        entries = tree;
        message = "";
    } catch (error) {
        if (request !== treeRequest) return;
        message = error.message || "无法读取工作流目录。";
        if (!quiet) notify(message, "error");
    }
    render();
}

function positionWorkflowTab() {
    const sidebar = manager()?.sidebarTab;
    const tabs = sidebar?.sidebarTabs;
    if (!Array.isArray(tabs)) return;
    const nativeIndex = tabs.findIndex(({ id }) => id === NATIVE_TAB);
    const library = tabs.find(({ id }) => id === TAB);
    if (nativeIndex < 0 || !library || tabs[nativeIndex + 1] === library) return;
    const ordered = tabs.filter(({ id }) => id !== TAB);
    ordered.splice(ordered.findIndex(({ id }) => id === NATIVE_TAB) + 1, 0, library);
    sidebar.sidebarTabs = ordered;
}

function applyNativeVisibility() {
    if (sidebarReady) positionWorkflowTab();
    document.documentElement.classList.toggle(HIDE_CLASS, sidebarReady && !showNative());
    render();
}

function openSidebar() {
    const sidebar = manager()?.sidebarTab;
    if (sidebar?.activeSidebarTabId === TAB) return;
    if (typeof sidebar?.toggleSidebarTab === "function") sidebar.toggleSidebarTab(TAB);
    else document.querySelector(TAB_BUTTON)?.click();
}

async function setShowNative(show) {
    try {
        if (!show && manager()?.sidebarTab?.activeSidebarTabId === NATIVE_TAB) openSidebar();
        await manager().setting.set(SHOW_NATIVE, Boolean(show));
        applyNativeVisibility();
    } catch (error) {
        notify(error.message || "无法保存入口设置。", "error");
        render();
    }
}

async function run(action, { inlineError = false } = {}) {
    if (busy || store()?.isBusy) {
        if (inlineError) throw new Error("请等当前工作流操作完成。");
        if (busy) return false;
        notify("请等当前工作流操作完成。");
        return false;
    }
    busy = true;
    render();
    try {
        return await action();
    } catch (error) {
        if (inlineError) throw error;
        notify(error.message || "操作失败。", "error");
        return false;
    } finally {
        busy = false;
        render();
    }
}

async function resolveWorkflow(path) {
    const workflows = store();
    if (!workflows?.getWorkflowByPath) throw new Error("当前 ComfyUI 版本无法打开此工作流。");
    let workflow = workflows.getWorkflowByPath(path);
    if (!workflow && path.startsWith(PREFIX)) {
        await workflows.syncWorkflows();
        workflow = workflows.getWorkflowByPath(path);
    }
    if (!workflow) throw new Error("工作流不存在或已移走，请刷新目录。");
    return workflow;
}

async function activateWorkflow(workflow, { deferWarnings = false } = {}) {
    const fromDisk = !workflow.isLoaded;
    if (fromDisk) await workflow.load();
    if (!workflow.activeState) throw new Error("无法读取工作流内容。");
    workflow.changeTracker?.prepareForSave?.();
    // Keep the original workflow object so its draft and view state stay with its tab.
    const loaded = await app.loadGraphData(workflow.activeState, true, true, workflow, {
        skipAssetScans: !fromDisk,
        silentAssetErrors: !fromDisk,
        deferWarnings,
    });
    if (loaded === false) throw new Error("工作流打开失败。");
    store()?.reportUserActivation?.(workflow);
    return true;
}

function openWorkflow(path) {
    if (path === activeFile()) return true;
    return run(async () => activateWorkflow(await resolveWorkflow(nativePath(path))));
}

function createFolder(parent, name) {
    return run(async () => {
        const { path } = await callRoute("folder", { parent, name });
        await refresh();
        notify(`已新建 ${filename(path)}。`, "success");
        return path;
    });
}

function protectOpenDescendants(source, verb = "移动") {
    const workflows = store();
    if (!workflows || workflows.tabsRestored === false) throw new Error(`正在恢复工作流标签，请稍后再${verb}。`);
    const folder = nativePath(source);
    const open = [...(workflows.openWorkflows ?? []), ...(workflows.modifiedWorkflows ?? [])];
    const openPaths = [...new Set(open.map(({ path }) => path).filter((path) => isUnder(path, folder)))];
    if (openPaths.length) {
        const names = openPaths.slice(0, 2).map((path) => `「${filename(path).replace(/\.json$/i, "")}」`).join("、");
        const remaining = openPaths.length > 2 ? `等 ${openPaths.length} 个工作流` : "";
        throw new Error(`请先保存并关闭${names}${remaining}，再${verb}文件夹。`);
    }
    if (workflows.bookmarkedWorkflows?.some((workflow) => isUnder(workflow.path, folder))) {
        throw new Error(`文件夹内有收藏的工作流，请先取消这些收藏再${verb}。`);
    }
}

function entryForEdit(path, stamp) {
    const entry = entries.find((item) => item.path === path);
    if (!entry || (stamp && entry.stamp !== stamp)) throw new Error("所选项目已变化，请刷新列表后重试。");
    return entry;
}

async function refreshAfterEdit(entry) {
    if (moveNotice) {
        moveNotice.items = moveNotice.items.filter((item) => !isUnder(item.from, entry.path) && !isUnder(item.to, entry.path));
        if (!moveNotice.items.length) dismissMoveNotice();
    }
    await refresh();
    if (entry.type !== "directory") return;
    try {
        await store()?.syncWorkflows?.();
    } catch {
        notify("灵犀列表已更新。原生列表同步失败，请刷新原生面板。", "warn");
    }
}

function renameEntry(source, name, stamp) {
    return run(async () => {
        const entry = entryForEdit(source, stamp);
        const folder = entry.type === "directory";
        const suffix = folder ? "" : entry.name.match(/\.json$/i)[0];
        const fullName = suffix && !/\.json$/i.test(name) ? name + suffix : name;
        if (entry.name === fullName) return source;
        if (folder) protectOpenDescendants(source, "重命名");
        const workflow = folder ? null : await resolveWorkflow(nativePath(source));
        const { path } = await callRoute(folder ? "rename-folder" : "check-rename", {
            source, name: fullName, stamp: entry.stamp,
        });
        if (workflow) await store().renameWorkflow(workflow, nativePath(path));
        await refreshAfterEdit(entry);
        notify(`已重命名为 ${filename(path)}。`, "success");
        return path;
    }, { inlineError: true });
}

async function removeWorkflowFile(workflow, request, workflows) {
    await callRoute("check-delete", request);
    const wasActive = workflows.activeWorkflow?.path === workflow.path;
    if (wasActive) {
        const replacement = workflows.getMostRecentWorkflow?.()
            ?? workflows.openWorkflows?.find((item) => item.path !== workflow.path);
        if (replacement) {
            await activateWorkflow(replacement, { deferWarnings: true });
        } else {
            const blank = { last_node_id: 0, last_link_id: 0, nodes: [], links: [], groups: [], config: {}, extra: {}, version: 0.4 };
            const loaded = await app.loadGraphData(blank);
            if (loaded === false) throw new Error("无法打开空白工作流。");
        }
        if (workflows.activeWorkflow?.path === workflow.path) throw new Error("工作流切换失败，请重试。");
    }
    try {
        // Native deletion detaches the tab and clears its draft after the disk operation succeeds.
        await workflows.deleteWorkflow(workflow);
    } catch (error) {
        if (wasActive && workflows.getWorkflowByPath(workflow.path) === workflow) {
            try {
                await activateWorkflow(workflow, { deferWarnings: true });
            } catch {
                // Leave the original tab available when it cannot be reactivated.
            }
        }
        throw error;
    }
}

function removeEntry(source, stamp) {
    return run(async () => {
        const entry = entryForEdit(source, stamp);
        const folder = entry.type === "directory";
        const request = { source, stamp: entry.stamp };
        if (folder) {
            protectOpenDescendants(source, "删除");
            await callRoute("delete-folder", request);
        } else {
            const workflows = store();
            if (workflows?.tabsRestored === false) throw new Error("正在恢复工作流标签，请稍后再删除。");
            const workflow = await resolveWorkflow(nativePath(source));
            await removeWorkflowFile(workflow, request, workflows);
        }
        await refreshAfterEdit(entry);
        notify(folder ? `已将 ${entry.name} 移到灵犀本地回收目录。` : `已删除 ${entry.name}。`, "success");
        return true;
    }, { inlineError: true });
}

async function moveEntry(entry, target) {
    if (parentOf(entry.path) === target) return null;
    let path;
    if (entry.type === "directory") {
        protectOpenDescendants(entry.path);
        ({ path } = await callRoute("move-folder", { source: entry.path, target, stamp: entry.stamp }));
    } else {
        const workflows = store();
        const workflow = await resolveWorkflow(nativePath(entry.path));
        if (workflow.isTemporary) throw new Error("请先保存成工作流文件，再移动。");
        ({ path } = await callRoute("check-move", { source: entry.path, target, stamp: entry.stamp }));
        if (workflows.activeWorkflow?.path === workflow.path) {
            // Capture canvas edits in the tracker before native rename rekeys the draft.
            const tracker = workflow.changeTracker;
            if (typeof tracker?.captureCanvasState === "function") tracker.captureCanvasState();
            else tracker?.checkState?.();
        }
        await workflows.renameWorkflow(workflow, nativePath(path));
    }
    return path ? { from: entry.path, to: path, type: entry.type } : null;
}

function dismissMoveNotice() {
    if (moveNotice?.id != null) manager()?.toast?.dismiss?.(moveNotice.id);
    moveNotice = undefined;
}

function reportMoves(moved, failed, { undo = false, undoItems = [] } = {}) {
    const verb = undo ? "撤销" : "移动";
    if (!moved.length && !failed.length) return notify("已在目标文件夹中。");
    const title = moved.length ? `已${verb} ${moved.length} 项` : `未${verb}任何项目`;
    const summary = moved.length && failed.length ? `${title}，跳过 ${failed.length} 项` : title;
    const detail = failed.slice(0, 3).map(({ path, error }) => `${filename(path)}：${error}`);
    if (failed.length > detail.length) detail.push(`另有 ${failed.length - detail.length} 项未处理。`);
    const description = detail.join(" ") || undefined;
    const kind = failed.length ? "warning" : "success";
    const toast = manager()?.toast;
    if (typeof toast?.[kind] !== "function") {
        return notify(description ? `${summary}。${description}` : summary, kind);
    }
    if (!undoItems.length) {
        toast[kind](summary, { description, duration: 5200 });
        return;
    }
    const notice = { items: undoItems };
    notice.id = toast[kind](summary, {
        description,
        duration: 6500,
        action: { label: "撤销", onClick: () => void undoMove(notice) },
    });
    moveNotice = notice;
}

function movePaths(paths, target) {
    return run(async () => {
        const selected = new Set(paths);
        const directoryPaths = entries.filter((entry) => entry.type === "directory" && selected.has(entry.path)).map(({ path }) => path);
        const sources = entries.filter((entry) => selected.has(entry.path) &&
            !directoryPaths.some((directory) => entry.path !== directory && isUnder(entry.path, directory)));
        if (!sources.length) return false;
        const moved = [];
        const failed = [];
        for (const entry of sources) {
            try {
                const result = await moveEntry(entry, target);
                if (!result) continue;
                moved.push(result);
            } catch (error) {
                failed.push({ path: entry.path, error: error.message || "无法移动" });
            }
        }
        if (!moved.length) {
            reportMoves(moved, failed);
            return false;
        }
        dismissMoveNotice();
        await refresh({ quiet: true });
        const undoItems = message ? [] : moved.map((item) => ({
            ...item, stamp: entries.find(({ path }) => path === item.to)?.stamp,
        })).filter(({ stamp }) => stamp);
        reportMoves(moved, failed, { undoItems });
        if (moved.some(({ type }) => type === "directory")) await store()?.syncWorkflows?.();
        return true;
    });
}

function undoMove(notice) {
    return run(async () => {
        if (moveNotice !== notice) return false;
        await refresh({ quiet: true });
        if (message) throw new Error(message);
        dismissMoveNotice();
        const restored = [];
        const failed = [];
        for (const item of [...notice.items].reverse()) {
            try {
                const entry = entries.find(({ path }) => path === item.to);
                if (!entry || entry.stamp !== item.stamp) {
                    throw new Error("文件已变化，保留当前位置。");
                }
                const result = await moveEntry(entry, parentOf(item.from));
                if (!result) continue;
                restored.push(result);
            } catch (error) {
                failed.push({ path: item.to, error: error.message || "无法撤销" });
            }
        }
        if (restored.length) {
            await refresh({ quiet: true });
        }
        reportMoves(restored, failed, { undo: true });
        if (restored.some(({ type }) => type === "directory")) await store()?.syncWorkflows?.();
        return restored.length > 0;
    });
}

function destroy() {
    if (!mounted) return;
    clearInterval(mounted.timer);
    mounted.panel.destroy();
    mounted = undefined;
}

function mount(container) {
    // ComfyUI can call the render ref again when repatching the same sidebar host.
    if (mounted?.container === container) return;
    destroy();
    const panel = mountWorkflowPanel(container, {
        open: openWorkflow,
        create: createFolder,
        rename: renameEntry,
        remove: removeEntry,
        move: movePaths,
        refresh,
        setShowNative,
    });
    mounted = {
        container,
        panel,
        timer: setInterval(() => {
            if (activeFile() !== mounted?.activePath) render();
        }, 350),
    };
    render();
    void refresh({ quiet: true });
}

app.registerExtension({
    name: "LX.WorkflowLibrary",
    settings: [{
        id: SHOW_NATIVE,
        name: "显示原生工作流入口",
        category: ["灵犀", "工作流管理"],
        type: "boolean",
        defaultValue: true,
        onChange(value) {
            if (value === false && sidebarReady && manager()?.sidebarTab?.activeSidebarTabId === NATIVE_TAB) openSidebar();
            applyNativeVisibility();
        },
    }],
    commands: [{ id: FOCUS_COMMAND, label: "打开工作流管理", function: openSidebar }],
    menuCommands: [{ path: ["Extensions", "灵犀工具"], commands: [FOCUS_COMMAND] }],
    setup() {
        const extensionManager = manager();
        if (sidebarReady || typeof extensionManager?.registerSidebarTab !== "function") return;
        extensionManager.registerSidebarTab({
            id: TAB,
            label: "工作流",
            title: "工作流管理",
            tooltip: "灵犀工作流管理",
            icon: "icon-[lucide--workflow]",
            type: "custom",
            render: mount,
            destroy,
        });
        const style = document.createElement("style");
        style.textContent = `html.${HIDE_CLASS} ${NATIVE_BUTTON} { display: none !important; }`;
        document.head.append(style);
        sidebarReady = true;
        store()?.onUserActivation?.(render);
        applyNativeVisibility();
    },
});
