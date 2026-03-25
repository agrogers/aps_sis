import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * ResourceTreeNode — renders a single node in the resource hierarchy tree
 * together with its children (recursively).
 *
 * Props:
 *   node        — tree node object: { id, name, type_id, type_name,
 *                   connection_type, children }
 *   currentId   — id of the resource being viewed (highlighted)
 *   depth       — nesting depth (0 = root ancestor)
 *   onOpen      — callback(id) to navigate to a resource
 */
class ResourceTreeNode extends Component {
    static template = "aps_sis.ResourceTreeNode";
    // components set below (self-referential recursive component)
    static props = {
        node: { type: Object },
        currentId: { type: Number, optional: true },
        depth: { type: Number },
        onOpen: { type: Function },
    };

    get isCurrent() {
        return this.props.node.id === this.props.currentId;
    }

    get isSupporting() {
        return this.props.node.connection_type === "supporting";
    }

    get typeIconUrl() {
        if (!this.props.node.type_id) return false;
        return `/web/image/aps.resource.types/${this.props.node.type_id}/icon`;
    }

    get rowStyle() {
        const fontSize = Math.max(0.75, 1 - this.props.depth * 0.07).toFixed(2);
        return `padding-left: ${this.props.depth * 20}px; font-size: ${fontSize}em`;
    }

    onClick(ev) {
        ev.preventDefault();
        if (!this.isCurrent) {
            this.props.onOpen(this.props.node.id);
        }
    }
}
// OWL recursive component: register itself in its own components map after definition.
ResourceTreeNode.components = { ResourceTreeNode };

/**
 * ResourceTreeWidget — view widget for the "Tree View" notebook page on the
 * aps.resources form.
 *
 * Loads the full resource hierarchy (ancestors above, descendants below) for
 * the currently open record by calling the ``get_resource_tree`` Python method
 * via RPC.  It then renders the tree using recursive ``ResourceTreeNode``
 * sub-components.
 *
 * Connection types:
 *   linked     — mark-contributing child (normal text)
 *   supporting — supplementary child (italic text)
 *
 * Usage in a form view:
 *   <widget name="resource_tree_widget"/>
 */
export class ResourceTreeWidget extends Component {
    static template = "aps_sis.ResourceTreeWidget";
    static components = { ResourceTreeNode };
    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            ancestors: [],
            current: null,
        });

        onWillStart(async () => {
            await this._loadTree();
        });

        onWillUpdateProps(async (nextProps) => {
            const nextId = nextProps.record.resId;
            const currId = this.props.record.resId;
            if (nextId && nextId !== currId) {
                await this._loadTree(nextId);
            }
        });
    }

    async _loadTree(resId = null) {
        const id = resId || this.props.record.resId;
        if (!id) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "aps.resources",
                "get_resource_tree",
                [[id]],
            );
            this.state.ancestors = result.ancestors || [];
            this.state.current = result.current || null;
        } catch (error) {
            console.error("ResourceTreeWidget: failed to load tree", error);
            this.state.ancestors = [];
            this.state.current = null;
        } finally {
            this.state.loading = false;
        }
    }

    openResource(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aps.resources",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Return an inline-style string for a row at the given depth. */
    rowStyleForDepth(depth) {
        const fontSize = Math.max(0.75, 1 - depth * 0.07).toFixed(2);
        return `padding-left: ${depth * 20}px; font-size: ${fontSize}em`;
    }
}

registry.category("view_widgets").add("resource_tree_widget", {
    component: ResourceTreeWidget,
});
