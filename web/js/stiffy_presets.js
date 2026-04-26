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
 *
 * Must be called deferred (setTimeout) so that graph.links is fully updated first.
 */
function refreshComboNode(node) {
    if (!node.graph || !node.inputs) return;

    const encSlots = node.inputs.filter((inp) => inp.name?.startsWith("encoded_"));

    // Build source_map from connected slots
    const sourceMap = {};
    const connectedSlots = [];
    for (const inp of encSlots) {
        if (inp.link == null) continue;
        const link = node.graph.links[inp.link];
        if (!link) continue;
        const srcNode = node.graph.getNodeById(link.origin_id);
        const info = getSourceInfo(srcNode);
        if (info) {
            sourceMap[info.title] = inp.name;
            connectedSlots.push({ slotName: inp.name, info });
        }
    }

    // Store source_map on node properties for Python to read via extra_pnginfo
    if (!node.properties) node.properties = {};
    node.properties._source_map = sourceMap;

    // Ensure exactly one trailing unconnected slot
    // Re-read after potential modifications
    const slots = node.inputs.filter((inp) => inp.name?.startsWith("encoded_"));
    const last = slots[slots.length - 1];

    if (!last || last.link != null) {
        node.addInput(`encoded_${slots.length + 1}`, "ENCODED_PROMPT");
    } else {
        // Walk backwards and remove extra trailing empties beyond the first
        for (let i = slots.length - 2; i >= 0; i--) {
            if (slots[i].link != null) break; // stop at first connected slot
            const idx = node.inputs.indexOf(slots[i]);
            if (idx !== -1) node.removeInput(idx);
        }
    }

    // Update sel_{cat} COMBO options: [MERGE_ALL, ...titles of connected nodes]
    for (const w of node.widgets ?? []) {
        if (!w.name.startsWith("sel_")) continue;
        const cat = w.name.replace(/^sel_/, "");

        const opts = [MERGE_ALL_SENTINEL];
        for (const { info } of connectedSlots) {
            // Include title if this source contributes the category (or if categories unknown)
            if (info.categories.length === 0 || info.categories.includes(cat)) {
                opts.push(info.title);
            }
        }

        w.options = w.options ?? {};
        w.options.values = opts;
        if (!opts.includes(w.value)) w.value = MERGE_ALL_SENTINEL;
    }

    node.graph.setDirtyCanvas(true, true);
}

function setupComboNode(node) {
    const origOnConnectionsChange = node.onConnectionsChange?.bind(node);
    node.onConnectionsChange = function (type, index, connected, link_info) {
        if (origOnConnectionsChange) origOnConnectionsChange(type, index, connected, link_info);
        // Defer: graph.links is not yet updated when this callback fires
        setTimeout(() => refreshComboNode(node), 0);
    };

    // Restore state when loading a saved workflow
    const origOnConfigure = node.onConfigure?.bind(node);
    node.onConfigure = function (info) {
        if (origOnConfigure) origOnConfigure.call(this, info);
        setTimeout(() => refreshComboNode(node), 0);
    };

    // Initial pass (deferred until node is in the graph)
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
