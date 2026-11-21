import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

const PATCH_FLAG = "__lxMemoryCleanupCanvasMenuPatch";
const MENU_MARKER = "__lxMemoryCleanupMenuItem";
const FORCE_STOP_MARKER = "__lxForceStopMenuItem";
const MENU_LABEL = "♻ 彻底清理内存/显存";
const FORCE_STOP_LABEL = "🛑 强制停止当前任务";
let cleanupRunning = false;
let forceStopRunning = false;

function formatGb(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "未知";
    return `${Number(value).toFixed(2)} GB`;
}

function formatDelta(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "未知";
    const number = Number(value);
    return `${number >= 0 ? "+" : ""}${number.toFixed(2)} GB`;
}

function stripHtml(value) {
    const container = document.createElement("div");
    container.innerHTML = String(value || "");
    return container.textContent || container.innerText || "";
}

function menuText(item) {
    if (typeof item === "string") return item;
    return stripHtml(item?.content ?? item?.title ?? "");
}

function isCleanupItem(item) {
    return item?.[MENU_MARKER] || menuText(item).includes("彻底清理内存/显存");
}

function isForceStopItem(item) {
    return item?.[FORCE_STOP_MARKER] || menuText(item).includes("强制停止当前任务");
}

function isMemoryCleanupText(text) {
    const normalized = String(text || "").replace(/\s+/g, " ");
    return (
        /(清理|释放).*(显存|内存|模型|缓存)/.test(normalized)
        || /(Free|Clear|Purge|Unload).*(VRAM|Memory|Models?|Cache)/i.test(normalized)
        || /(VRAM|Memory|Models?|Cache).*(Free|Clear|Purge|Unload)/i.test(normalized)
    );
}

function findInsertIndex(options) {
    const texts = options.map(menuText);
    const cleanupIndex = texts.findIndex(isMemoryCleanupText);
    if (cleanupIndex >= 0) return cleanupIndex + 1;

    const restartIndex = texts.findIndex((text) => /重启\s*ComfyUI|Restart\s*ComfyUI/i.test(text));
    if (restartIndex >= 0) return restartIndex;

    const addNodeIndex = texts.findIndex((text) => /添加节点|Add Node/i.test(text));
    if (addNodeIndex >= 0) return addNodeIndex;

    const firstSeparator = options.findIndex((item) => item == null);
    return firstSeparator >= 0 ? firstSeparator + 1 : 0;
}

function toastStyle(type) {
    const palette = {
        success: ["#123524", "#64d487"],
        error: ["#3b1515", "#ff7b72"],
        info: ["#162235", "#86b7ff"],
    }[type] || ["#1d1d1f", "#d9d9df"];
    return {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "100000",
        maxWidth: "360px",
        padding: "12px 14px",
        borderRadius: "8px",
        border: `1px solid ${palette[1]}`,
        background: palette[0],
        color: "#f6f6f8",
        boxShadow: "0 10px 30px rgba(0, 0, 0, 0.35)",
        fontSize: "13px",
        lineHeight: "1.45",
        whiteSpace: "pre-line",
        pointerEvents: "none",
    };
}

function showToast(title, detail = "", type = "success") {
    const toast = app.extensionManager?.toast;
    if (toast?.add) {
        toast.add({
            severity: type === "error" ? "error" : type === "info" ? "info" : "success",
            summary: title,
            detail,
            life: type === "error" ? 7000 : 5000,
        });
        return;
    }

    const existing = document.querySelector(".lx-memory-cleanup-toast");
    existing?.remove();

    const element = document.createElement("div");
    element.className = "lx-memory-cleanup-toast";
    Object.assign(element.style, toastStyle(type));
    element.textContent = detail ? `${title}\n${detail}` : title;
    document.body.appendChild(element);

    window.setTimeout(() => {
        element.style.transition = "opacity 180ms ease";
        element.style.opacity = "0";
        window.setTimeout(() => element.remove(), 220);
    }, type === "error" ? 7000 : 5000);
}

function buildResultText(data) {
    if (data.status || data.message) return data.status || data.message;
    return [
        `显存可用：${formatGb(data.vram_before)} -> ${formatGb(data.vram_after)}（${formatDelta(data.vram_delta)}）`,
        `内存可用：${formatGb(data.ram_before)} -> ${formatGb(data.ram_after)}（${formatDelta(data.ram_delta)}）`,
    ].join("\n");
}

async function runCleanup() {
    if (cleanupRunning) {
        showToast("灵犀清理", "上一次清理还没有结束。", "info");
        return;
    }

    cleanupRunning = true;
    showToast("灵犀清理", "正在卸载模型并清理内存/显存...", "info");

    try {
        const response = await api.fetchApi("/lx/memory/cleanup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                clean_cache: true,
                unload_models: true,
            }),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok || data.success === false) {
            throw new Error(data.message || `HTTP ${response.status}`);
        }

        showToast(data.queued ? "清理已排队" : "清理完成", buildResultText(data), "success");
    } catch (error) {
        console.warn("[LX Memory Cleanup] cleanup failed", error);
        showToast("清理失败", error?.message || String(error), "error");
    } finally {
        cleanupRunning = false;
    }
}

async function runForceStop() {
    if (forceStopRunning) {
        showToast("强制停止", "上一次强制停止还没有结束。", "info");
        return;
    }

    forceStopRunning = true;
    showToast("强制停止", "正在中断当前节点并清空等待队列...", "info");

    try {
        const response = await api.fetchApi("/lx/execution/force-stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                clear_pending: true,
                cooperative_wait_ms: 700,
                forced_wait_ms: 1800,
                allow_thread_interrupt: true,
            }),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok || data.success === false) {
            throw new Error(data.message || `HTTP ${response.status}`);
        }

        if (!data.had_running) {
            showToast("强制停止", data.message || "当前没有正在运行的任务。", "info");
        } else if (data.stopped) {
            const title = data.mode === "forced" ? "已强制停止" : "任务已停止";
            showToast(title, data.message || "当前任务已停止。", "success");
        } else {
            showToast(
                "强制停止未完成",
                data.message || "当前节点处于不可安全中断的原生调用中，任务仍在运行。",
                "error"
            );
        }
    } catch (error) {
        console.warn("[LX Force Stop] force stop failed", error);
        showToast("强制停止失败", error?.message || String(error), "error");
    } finally {
        forceStopRunning = false;
    }
}

function createCleanupItem() {
    return {
        [MENU_MARKER]: true,
        content: cleanupRunning ? "♻ 正在彻底清理内存/显存..." : MENU_LABEL,
        disabled: cleanupRunning,
        callback: () => runCleanup(),
    };
}

function createForceStopItem() {
    return {
        [FORCE_STOP_MARKER]: true,
        content: forceStopRunning ? "🛑 正在强制停止当前任务..." : FORCE_STOP_LABEL,
        disabled: forceStopRunning,
        callback: () => runForceStop(),
    };
}

function insertUtilityItems(options) {
    if (!Array.isArray(options)) return options;

    if (!options.some(isCleanupItem)) {
        options.splice(findInsertIndex(options), 0, createCleanupItem());
    }

    if (!options.some(isForceStopItem)) {
        const cleanupIndex = options.findIndex(isCleanupItem);
        const insertIndex = cleanupIndex >= 0 ? cleanupIndex + 1 : findInsertIndex(options);
        options.splice(insertIndex, 0, createForceStopItem());
    }
    return options;
}

function installCanvasMenuPatch() {
    const prototype = globalThis.LGraphCanvas?.prototype;
    if (!prototype?.getCanvasMenuOptions || prototype[PATCH_FLAG]) return Boolean(prototype?.[PATCH_FLAG]);

    const originalGetCanvasMenuOptions = prototype.getCanvasMenuOptions;
    prototype[PATCH_FLAG] = true;
    prototype.getCanvasMenuOptions = function (...args) {
        const options = originalGetCanvasMenuOptions.apply(this, args);
        try {
            insertUtilityItems(options);
        } catch (error) {
            console.warn("[LX Utility Menu] failed to insert menu items", error);
        }
        return options;
    };
    return true;
}

app.registerExtension({
    name: "LX.Utility.MemoryCleanupMenu",

    setup() {
        if (installCanvasMenuPatch()) return;
        for (const delay of [250, 500, 1000, 2000]) {
            window.setTimeout(installCanvasMenuPatch, delay);
        }
    },
});
