import { app } from "../../../scripts/app.js";

const TRAIN_NODE_NAME = "ComfyUI-Seedance Voice Clone V3 Train";

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function timestamp() {
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    return [
        now.getFullYear(),
        pad(now.getMonth() + 1),
        pad(now.getDate()),
        pad(now.getHours()),
        pad(now.getMinutes()),
        pad(now.getSeconds()),
    ].join("");
}

function randomSuffix() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 8);
    }
    return Math.random().toString(16).slice(2, 10).padEnd(8, "0");
}

function generateVoiceId(node) {
    const language = String(getWidget(node, "language")?.value || "cn")
        .toLowerCase()
        .replace(/[^a-z0-9]/g, "_");
    return `custom_${language}_${timestamp()}_${randomSuffix()}`;
}

function setVoiceId(node, force = false) {
    const widget = getWidget(node, "custom_speaker_id");
    if (!widget || (!force && String(widget.value || "").trim())) {
        return;
    }
    const value = generateVoiceId(node);
    widget.value = value;
    widget.callback?.(value);
    node.setDirtyCanvas(true, true);
}

function installVoiceIdControls(node) {
    setVoiceId(node);
    const regenerate = node.addWidget("button", "生成新的 custom_speaker_id", null, () => setVoiceId(node, true));
    regenerate.serialize = false;
    const computedSize = node.computeSize();
    node.setSize([Math.max(node.size[0], 360), Math.max(node.size[1], computedSize[1])]);
}

app.registerExtension({
    name: "ComfyUISeedanceVoiceClone",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== TRAIN_NODE_NAME) {
            return;
        }
        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            installVoiceIdControls(this);
            return result;
        };
    },
});
