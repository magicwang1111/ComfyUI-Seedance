import { app } from "../../../scripts/app.js";

const NODE_NAME = "ComfyUI-Seedance 2.5 Omni-to-Video";
const MEDIA_INPUTS = {
    image: { type: "IMAGE", limit: 30 },
    video: { type: "VIDEO", limit: 10 },
    audio: { type: "AUDIO", limit: 10 },
    asset: { type: "STRING", limit: 50 },
};

function dynamicInputName(mediaType, index) {
    return `${mediaType}_${String(index).padStart(2, "0")}`;
}

function stabilizeMediaInputs(node) {
    if (node._seedance25Stabilizing) {
        return;
    }

    node._seedance25Stabilizing = true;
    try {
        for (const [mediaType, config] of Object.entries(MEDIA_INPUTS)) {
            const pattern = new RegExp(`^${mediaType}_(\\d{2})$`);
            const matchingInputs = (node.inputs ?? [])
                .map((input, slot) => ({ input, slot }))
                .filter(({ input }) => pattern.test(input.name));

            const hasConnectedInput = matchingInputs.some(({ input }) => input.link != null);
            const emptyInputs = matchingInputs.filter(({ input }) => input.link == null);
            const emptyInputToKeep = hasConnectedInput ? emptyInputs[emptyInputs.length - 1] : emptyInputs[0];
            const emptyInputsToRemove = emptyInputs.filter((entry) => entry !== emptyInputToKeep);
            for (const { slot } of emptyInputsToRemove.reverse()) {
                node.removeInput(slot);
            }

            const connectedInputs = (node.inputs ?? [])
                .filter((input) => pattern.test(input.name) && input.link != null);
            connectedInputs.forEach((input, index) => {
                input.name = dynamicInputName(mediaType, index + 1);
                input.label = input.name;
                input.type = config.type;
            });

            const emptyInput = (node.inputs ?? [])
                .find((input) => pattern.test(input.name) && input.link == null);
            if (connectedInputs.length < config.limit) {
                if (emptyInput) {
                    emptyInput.name = dynamicInputName(mediaType, connectedInputs.length + 1);
                    emptyInput.label = emptyInput.name;
                    emptyInput.type = config.type;
                } else {
                    node.addInput(dynamicInputName(mediaType, connectedInputs.length + 1), config.type);
                }
            } else if (emptyInput) {
                node.removeInput(node.inputs.indexOf(emptyInput));
            }
        }
    } finally {
        node._seedance25Stabilizing = false;
    }

    node.graph?.setDirtyCanvas(true, true);
}

function scheduleStabilize(node) {
    if (node._seedance25StabilizeTimer != null) {
        window.clearTimeout(node._seedance25StabilizeTimer);
    }
    node._seedance25StabilizeTimer = window.setTimeout(() => {
        node._seedance25StabilizeTimer = null;
        stabilizeMediaInputs(node);
    }, 32);
}

app.registerExtension({
    name: "ComfyUISeedance.Seedance25OmniDynamicInputs",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            stabilizeMediaInputs(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            scheduleStabilize(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            scheduleStabilize(this);
            return result;
        };
    },
});
