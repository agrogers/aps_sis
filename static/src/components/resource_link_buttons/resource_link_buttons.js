import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Open a resource link: external URL, Odoo internal path, client action,
 * or notes-popup.  Shared by ResourceLinkButtons and ResourceLinksField.
 *
 * @param {Object}  linkData    Link object from supporting_resources_buttons JSON
 * @param {Object}  services    { action, orm }
 * @param {Object}  [context]   Extra context dict for `action:` URLs
 */
export async function openResourceLink(linkData, services, context) {
    if (linkData && linkData.link_type === "notes") {
        const [, viewId] = await services.orm.call(
            "ir.model.data",
            "check_object_reference",
            ["aps_sis", "view_aps_resource_notes_popup"]
        );
        services.action.doAction({
            type: "ir.actions.act_window",
            name: linkData.name || "Resource Notes",
            res_model: "aps.resources",
            res_id: linkData.id,
            view_mode: "form",
            views: [[viewId, "form"]],
            target: "new",
        });
        return;
    }

    const url = typeof linkData === "string" ? linkData : linkData.url;
    if (!url) return;

    if (url.startsWith("action:")) {
        const rawAction = url.replace("action:", "");
        const paramIndex = rawAction.search(/[?&]/);
        const actionTag = paramIndex === -1 ? rawAction : rawAction.slice(0, paramIndex);
        const rawParams = paramIndex === -1 ? "" : rawAction.slice(paramIndex);
        const params = rawParams ? rawParams.replace(/^[?&]/, "") : "";
        const urlParams = new URLSearchParams(params);
        const contextParams = Object.fromEntries(urlParams.entries());

        services.action.doAction(actionTag, {
            additionalContext: {
                ...(context || {}),
                ...contextParams,
            },
            target: "new",
        });
    } else if (url.startsWith("/") || url.includes(window.location.origin)) {
        window.location.href = url;
    } else {
        window.open(url, "_blank");
    }
}

/**
 * Reusable OWL component that renders a list of resource-link buttons.
 *
 * Props:
 *  - links:       Array of link objects ({id, name, url, icon_url, link_type, …})
 *  - size:        CSS size string for icon (default "24px")
 *  - showName:    Show the link name text (default false)
 *  - compact:     Use compact pill-style layout for embedding in tight cells (default false)
 *  - context:     Optional dict passed as additional context for `action:` URLs
 *  - notesHandler: Optional callback(linkData) invoked for notes-type links instead of the default popup
 */
export class ResourceLinkButtons extends Component {
    static template = "aps_sis.ResourceLinkButtons";
    static props = {
        links: { type: Array },
        size: { type: String, optional: true },
        showName: { type: Boolean, optional: true },
        compact: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
        notesHandler: { type: Function, optional: true },
        linkInterceptor: { type: Function, optional: true },
    };
    static defaultProps = {
        size: "24px",
        showName: false,
        compact: false,
        context: {},
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
    }

    openUrl(linkData) {
        // Let parent intercept the click (e.g. quiz links in student mode)
        if (this.props.linkInterceptor && this.props.linkInterceptor(linkData)) {
            return;
        }
        if (linkData?.link_type === "notes" && this.props.notesHandler) {
            this.props.notesHandler(linkData);
            return;
        }
        openResourceLink(linkData, { action: this.action, orm: this.orm }, this.props.context);
    }
}
