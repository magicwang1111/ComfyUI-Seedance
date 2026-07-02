import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_NAME = "ComfyUI-Seedance Trusted Person Asset";
const CREATE_SESSION_ROUTE = "/seedance/assets/validation/session";
const CALLBACK_ROUTE = "/seedance/assets/validation/callback";
const POLL_INTERVAL_MS = 3000;

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function getWidgetValue(node, name) {
    return String(getWidget(node, name)?.value ?? "").trim();
}

function setWidgetValue(node, name, value) {
    const widget = getWidget(node, name);
    if (!widget) {
        throw new Error(`${name} must remain a node widget while creating real-person validation.`);
    }
    widget.value = value;
    widget.callback?.(value);
    node.setDirtyCanvas(true, true);
}

function setStatus(node, text) {
    if (node._seedanceStatusWidget) {
        node._seedanceStatusWidget.name = `认证状态：${text}`;
    }
    node.setDirtyCanvas(true, true);
}

function stopPolling(node) {
    if (node._seedancePollTimer) {
        window.clearInterval(node._seedancePollTimer);
        node._seedancePollTimer = null;
    }
}

async function fetchJson(path, options = {}) {
    const response = await api.fetchApi(path, options);
    let payload = {};
    try {
        payload = await response.json();
    } catch {
        payload = {};
    }
    if (!response.ok) {
        throw new Error(payload.error || `Request failed with HTTP ${response.status}.`);
    }
    return payload;
}

function defaultCallbackUrl() {
    return new URL(CALLBACK_ROUTE, window.location.origin).toString();
}

async function refreshValidation(node, force = false) {
    const sessionId = node._seedanceValidationSessionId;
    if (!sessionId) {
        throw new Error("请先创建真人认证。");
    }

    const suffix = force ? "?refresh=1" : "";
    const state = await fetchJson(
        `/seedance/assets/validation/session/${encodeURIComponent(sessionId)}${suffix}`,
        { cache: "no-store" },
    );

    if (state.group_id) {
        setWidgetValue(node, "group_id", state.group_id);
        setStatus(node, "认证完成，Group ID 已写入");
        stopPolling(node);
        return;
    }

    if (state.status === "failed") {
        setStatus(node, state.error || "认证未通过");
        stopPolling(node);
        return;
    }

    if (state.query_error) {
        setStatus(node, `等待 Group ID：${state.query_error}`);
        return;
    }

    const labels = {
        awaiting_user: "等待用户完成人脸认证",
        verified: "认证通过，正在获取 Group ID",
    };
    setStatus(node, labels[state.status] || state.status || "等待认证");
}

function startPolling(node) {
    stopPolling(node);
    node._seedancePollTimer = window.setInterval(() => {
        refreshValidation(node).catch((error) => {
            setStatus(node, error.message);
            if (error.message.includes("expired") || error.message.includes("not found")) {
                stopPolling(node);
            }
        });
    }, POLL_INTERVAL_MS);
}

async function createValidation(node) {
    stopPolling(node);
    setStatus(node, "正在创建认证链接");

    const popup = window.open("about:blank", "_blank");
    const projectName = getWidgetValue(node, "project_name") || "default";
    const callbackUrl = getWidgetValue(node, "callback_url") || defaultCallbackUrl();

    try {
        const result = await fetchJson(CREATE_SESSION_ROUTE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_name: projectName,
                callback_url: callbackUrl,
            }),
        });

        node._seedanceValidationSessionId = result.session_id;
        node._seedanceValidationH5Link = result.h5_link;
        setStatus(node, "等待用户完成人脸认证");
        startPolling(node);

        if (popup) {
            popup.opener = null;
            popup.location.replace(result.h5_link);
        } else {
            window.open(result.h5_link, "_blank", "noopener,noreferrer");
        }
    } catch (error) {
        popup?.close();
        setStatus(node, error.message);
    }
}

function openValidation(node) {
    if (!node._seedanceValidationH5Link) {
        setStatus(node, "请先创建真人认证");
        return;
    }
    window.open(node._seedanceValidationH5Link, "_blank", "noopener,noreferrer");
}

function installValidationControls(node) {
    node._seedanceStatusWidget = node.addWidget("button", "认证状态：未开始", null, () => {});
    node._seedanceStatusWidget.serialize = false;

    const createWidget = node.addWidget("button", "创建真人认证", null, () => createValidation(node));
    createWidget.serialize = false;

    const openWidget = node.addWidget("button", "重新打开认证页面", null, () => openValidation(node));
    openWidget.serialize = false;

    const refreshWidget = node.addWidget("button", "查询认证结果", null, () => {
        refreshValidation(node, true).catch((error) => setStatus(node, error.message));
    });
    refreshWidget.serialize = false;

    const computedSize = node.computeSize();
    node.setSize([Math.max(node.size[0], 360), Math.max(node.size[1], computedSize[1])]);
}

app.registerExtension({
    name: "ComfyUISeedanceTrustedPersonAsset",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            installValidationControls(this);
            return result;
        };

        const originalOnRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            stopPolling(this);
            return originalOnRemoved?.apply(this, arguments);
        };
    },
});
