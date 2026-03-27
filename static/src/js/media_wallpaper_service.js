import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * APEX Media Wallpaper Service
 *
 * When the user has enabled custom wallpapers in their Media Settings,
 * this service picks a random owned media item and applies its image as
 * the background of every `.o_content` container (list / form views).
 *
 * A MutationObserver keeps newly-mounted views in sync.
 */

const WALLPAPER_CLASS = "aps-media-wallpaper";
const WALLPAPER_QUAD_CLASS = "aps-media-wallpaper--quad";

let _wallpaperUrl = null;
let _quadUrls = null;   // array of 4 URLs when in quad mode
let _mode = "single";
let _mediaIds = [];     // full pool for refresh picks
let _observer = null;
let _refreshTimer = null;

function _setWpVar(el) {
    if (_mode === "quad" && _quadUrls) {
        el.classList.add(WALLPAPER_QUAD_CLASS);
        const imgs = _quadUrls.map((u) => `url(${u})`).join(", ");
        el.style.setProperty("--aps-wp-url", imgs);
    } else {
        el.classList.remove(WALLPAPER_QUAD_CLASS);
        el.style.setProperty("--aps-wp-url", `url(${_wallpaperUrl})`);
    }
}

function _applyTo(el) {
    if (el.classList.contains(WALLPAPER_CLASS)) return;
    el.classList.add(WALLPAPER_CLASS);
    _setWpVar(el);
}

function _applyAll() {
    document.querySelectorAll(".o_content").forEach(_applyTo);
}

/** Re-pick random images from the pool and update existing elements. */
function _pickNewWallpaper() {
    const pick = () => _mediaIds[Math.floor(Math.random() * _mediaIds.length)];
    if (_mode === "quad") {
        _quadUrls = Array.from({ length: 4 }, () =>
            `/web/image/aps.media/${encodeURIComponent(pick())}/image`
        );
    } else {
        _wallpaperUrl = `/web/image/aps.media/${encodeURIComponent(pick())}/image`;
    }
}

/** Update the CSS variable on all already-tagged .o_content elements. */
function _refreshAll() {
    document.querySelectorAll(`.o_content.${WALLPAPER_CLASS}`).forEach(_setWpVar);
}

function _onMutation(mutations) {
    for (const m of mutations) {
        for (const node of m.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            if (node.matches?.(".o_content")) _applyTo(node);
            node.querySelectorAll?.(".o_content").forEach(_applyTo);
        }
    }
}

registry.category("services").add("aps_media_wallpaper", {
    async start() {
        let data;
        try {
            data = await rpc(
                "/web/dataset/call_kw/aps.user.media.settings/get_wallpaper_data",
                {
                    model: "aps.user.media.settings",
                    method: "get_wallpaper_data",
                    args: [],
                    kwargs: {},
                },
            );
        } catch {
            // Silently ignore — module may not be fully installed yet or
            // user has no media settings record.
            return;
        }

        if (!data?.enabled || !data.media_ids?.length) return;

        _mode = data.mode || "single";
        _mediaIds = data.media_ids;

        _pickNewWallpaper();

        // Apply to any existing .o_content elements
        _applyAll();

        // Auto-refresh timer
        const mins = data.refresh_minutes || 0;
        if (mins > 0) {
            _refreshTimer = setInterval(() => {
                _pickNewWallpaper();
                _refreshAll();
            }, mins * 60 * 1000);
        }

        // Watch for future views being mounted
        _observer = new MutationObserver(_onMutation);
        _observer.observe(document.body, { childList: true, subtree: true });
    },
});
