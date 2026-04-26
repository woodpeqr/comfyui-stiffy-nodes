import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const SIMPLE_NODE_TYPE = "StiffySimplePresetNode";
const COMPLEX_NODE_TYPE = "StiffyComplexPresetNode";
const COMBO_NODE_TYPE = "StiffyComboNode";
const NEW_PRESET_SENTINEL = "-- new --";
const MERGE_ALL_SENTINEL = "(merge all)";

// ─── API helpers ─────────────────────────────────────────────────────────────

async function fetchPreset(name) {
    const resp = await api.fetchApi(`/api/stiffy/presets/${encodeURIComponent(name)}`);
    if (!resp.ok) return null;
    return await resp.json();
}

async function fetchPresetNames(category) {
    const url = category
        ? `/api/stiffy/presets?category=${encodeURIComponent(category)}`
        : "/api/stiffy/presets";
    const resp = await api.fetchApi(url);
    if (!resp.ok) return [];
    return await resp.json();
}

// ─── Widget helpers ──────────────────────────────────────────────────────────

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
    const w = getWidget(node, name);
    if (w) w.value = value;
}

// ─── Simple preset node ──────────────────────────────────────────────────────

function setupSimplePresetNode(node) {
    const loadPresetWidget = getWidget(node, "load_preset");
    if (!loadPresetWidget) return;

    const orig = loadPresetWidget.callback;
    loadPresetWidget.callback = async function (value) {
        if (orig) orig.call(this, value);
        if (!value || value === NEW_PRESET_SENTINEL) return;

        const entries = await fetchPreset(value);
        if (!entries) return;

        const catEntry = entries.find((e) => e.category !== "negative");
        const negEntry = entries.find((e) => e.category === "negative");

        setWidgetValue(node, "preset_name", value);
        setWidgetValue(node, "prompt", catEntry ? catEntry.prompt : "");
        setWidgetValue(node, "negative_prompt", negEntry ? negEntry.prompt : "");

        node.graph?.setDirtyCanvas(true);
    };
}

// ─── Complex preset node ─────────────────────────────────────────────────────

function setupComplexPresetNode(node) {
    const loadPresetWidget = getWidget(node, "load_preset");
    if (!loadPresetWidget) return;

    const orig = loadPresetWidget.callback;
    loadPresetWidget.callback = async function (value) {
        if (orig) orig.call(this, value);
        if (!value || value === NEW_PRESET_SENTINEL) return;

        const entries = await fetchPreset(value);
        if (!entries) return;

        setWidgetValue(node, "preset_name", value);

        // Clear all category fields first, then populate from preset
        for (const w of node.widgets ?? []) {
            if (w.name.endsWith("_prompt") && w.name !== "negative_prompt") {
                w.value = "";
            }
        }
        setWidgetValue(node, "negative_prompt", "");

        for (const entry of entries) {
            if (entry.category === "negative") {
                setWidgetValue(node, "negative_prompt", entry.prompt);
            } else {
                setWidgetValue(node, `${entry.category}_prompt`, entry.prompt);
            }
        }

        node.graph?.setDirtyCanvas(true);
    };
}

// ─── Combo node ──────────────────────────────────────────────────────────────

/**
 * Return {title, categories[]} for a connected source node, where categories is the
 * list of prompt categories this node contributes.
 */
function getSourceInfo(srcNode) {
    if (!srcNode) return null;
    const title = srcNode.title || srcNode.type;
    let categories = [];

    if (srcNode.type === SIMPLE_NODE_TYPE) {
        // Simple node contributes the value of its "category" widget
        const catWidget = srcNode.widgets?.find((w) => w.name === "category");
        if (catWidget?.value) categories = [catWidget.value];
    } else if (srcNode.type === COMPLEX_NODE_TYPE) {
        // Complex node contributes every {cat}_prompt widget that is non-empty
        for (const w of srcNode.widgets ?? []) {
            if (w.name.endsWith("_prompt") && w.name !== "negative_prompt" && w.value?.trim()) {
                categories.push(w.name.replace(/_prompt$/, ""));
            }
        }
        const neg = srcNode.widgets?.find((w) => w.name === "negative_prompt");
        if (neg?.value?.trim()) categories.push("negative");
    } else {
        // Any other node type: treat its output as contributing all categories (unknown)
        categories = [];
    }

    return { title, categories };
}

/**
 * Find the slot index (0-based) of an input slot by name.
 */
function findInputSlot(node, name) {
    return node.inputs?.findIndex((inp) => inp.name === name) ?? -1;
}

/**
 * Rebuild the source_map and refresh sel_{cat} COMBO options based on current connections.
 * Always keeps exactly one trailing empty encoded_N slot.
 */
function refreshComboNode(node) {
    if (!node.inputs) node.inputs = [];

    // Collect all encoded_* input slots in order
    const encSlots = node.inputs.filter((inp) => inp.name?.startsWith("encoded_"));

    // Determine which slots are connected and build source_map
    const sourceMap = {};
    const connectedSlots = [];
    for (const inp of encSlots) {
        const link = inp.link != null ? node.graph?.links?.[inp.link] : null;
        if (link) {
            const srcNode = node.graph?.getNodeById(link.origin_id);
            const info = getSourceInfo(srcNode);
            if (info) {
                sourceMap[info.title] = inp.name;
                connectedSlots.push({ slotName: inp.name, info });
            }
        }
    }

    // Store source_map on node properties for Python to read via extra_pnginfo
    if (!node.properties) node.properties = {};
    node.properties._source_map = sourceMap;

    // Ensure there is exactly one trailing unconnected encoded_N slot
    const lastSlot = encSlots[encSlots.length - 1];
    const lastConnected = lastSlot?.link != null;

    if (!lastSlot || lastConnected) {
        // Add a new empty slot
        const nextN = encSlots.length + 1;
        node.addInput(`encoded_${nextN}`, "ENCODED_PROMPT");
    } else {
        // Remove any extra trailing empty slots (keep exactly one)
        let trailingEmpty = 0;
        for (let i = encSlots.length - 1; i >= 0; i--) {
            if (encSlots[i].link == null) trailingEmpty++;
            else break;
        }
        for (let i = 0; i < trailingEmpty - 1; i++) {
            const toRemove = encSlots[encSlots.length - 1 - i];
            const slotIdx = findInputSlot(node, toRemove.name);
            if (slotIdx !== -1) node.removeInput(slotIdx);
        }
    }

    // Update sel_{cat} COMBO options: [MERGE_ALL, ...connected node titles]
    const titles = connectedSlots.map((s) => s.info.title);
    for (const w of node.widgets ?? []) {
        if (!w.name.startsWith("sel_")) continue;
        const cat = w.name.replace(/^sel_/, "");

        // Build options: always include MERGE_ALL; add titles that contribute this category
        const opts = [MERGE_ALL_SENTINEL];
        for (const { info } of connectedSlots) {
            if (info.categories.length === 0 || info.categories.includes(cat)) {
                opts.push(info.title);
            }
        }

        w.options = w.options ?? {};
        w.options.values = opts;

        // Reset to MERGE_ALL if current value is no longer available
        if (!opts.includes(w.value)) w.value = MERGE_ALL_SENTINEL;
    }

    node.graph?.setDirtyCanvas(true);
}

function setupComboNode(node) {
    const origOnConnectionsChange = node.onConnectionsChange?.bind(node);
    node.onConnectionsChange = function (type, index, connected, link_info) {
        if (origOnConnectionsChange) origOnConnectionsChange(type, index, connected, link_info);
        refreshComboNode(node);
    };

    // Initial refresh in case node is restored with existing connections
    setTimeout(() => refreshComboNode(node), 0);
}

// ─── Extension ───────────────────────────────────────────────────────────────

app.registerExtension({
    name: "stiffy.presets",

    async nodeCreated(node) {
        if (node.type === SIMPLE_NODE_TYPE) {
            setupSimplePresetNode(node);
        } else if (node.type === COMPLEX_NODE_TYPE) {
            setupComplexPresetNode(node);
        } else if (node.type === COMBO_NODE_TYPE) {
            setupComboNode(node);
        }
    },
});
