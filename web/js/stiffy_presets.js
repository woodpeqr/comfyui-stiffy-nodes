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
 * Return {title, categories[]} for a source node, where categories is the list of
 * prompt categories this node contributes (used to filter sel_* dropdown options).
 */
function getSourceInfo(srcNode) {
    if (!srcNode) return null;
    const title = srcNode.title || srcNode.type;
    let categories = [];

    if (srcNode.type === SIMPLE_NODE_TYPE) {
        const catWidget = srcNode.widgets?.find((w) => w.name === "category");
        if (catWidget?.value) categories = [catWidget.value];
    } else if (srcNode.type === COMPLEX_NODE_TYPE) {
        for (const w of srcNode.widgets ?? []) {
            if (w.name.endsWith("_prompt") && w.name !== "negative_prompt" && w.value?.trim()) {
                categories.push(w.name.replace(/_prompt$/, ""));
            }
        }
        const neg = srcNode.widgets?.find((w) => w.name === "negative_prompt");
        if (neg?.value?.trim()) categories.push("negative");
    }
    // Unknown node type → categories stays [], meaning "contributes everything"

    return { title, categories };
}

/**
 * Read all source nodes connected to the `encoded` INPUT_IS_LIST slot.
 * ComfyUI uses slot.links (array) for multi-connection slots; fall back to slot.link.
 * Returns [{title, categories}] in connection order.
 */
function getEncodedConnections(node) {
    if (!node.graph) return [];
    const slot = node.inputs?.find((inp) => inp.name === "encoded");
    if (!slot) return [];

    const linkIds = Array.isArray(slot.links)
        ? slot.links
        : slot.link != null ? [slot.link] : [];

    const result = [];
    for (const id of linkIds) {
        const link = node.graph.links[id];
        if (!link) continue;
        const src = node.graph.getNodeById(link.origin_id);
        const info = getSourceInfo(src);
        if (info) result.push(info);
    }
    return result;
}

/**
 * Rebuild source_map and sel_* COMBO options from currently connected sources.
 * Deferred via setTimeout so graph.links is fully updated before we read it.
 */
function refreshComboNode(node) {
    if (!node.graph) return;

    const connections = getEncodedConnections(node);

    // source_map: {title: 0-based index} — matches Python's encoded list order
    const sourceMap = {};
    connections.forEach((info, i) => { sourceMap[info.title] = i; });

    if (!node.properties) node.properties = {};
    node.properties._source_map = sourceMap;

    // Update each sel_* COMBO: [MERGE_ALL, ...titles that contribute this category]
    for (const w of node.widgets ?? []) {
        if (!w.name.startsWith("sel_")) continue;
        const cat = w.name.replace(/^sel_/, "");

        const opts = [MERGE_ALL_SENTINEL];
        for (const info of connections) {
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
        setTimeout(() => refreshComboNode(node), 0);
    };

    const origOnConfigure = node.onConfigure?.bind(node);
    node.onConfigure = function (info) {
        if (origOnConfigure) origOnConfigure.call(this, info);
        setTimeout(() => refreshComboNode(node), 0);
    };

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
