import { Component, useState, onWillStart, onMounted, onPatched, onWillPatch, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { markup } from "@odoo/owl";

export class ResourceNotesDialog extends Component {
    static template = "aps_sis.ResourceNotesDialog";
    static components = { Dialog };
    static props = {
        resourceId: { type: Number },
        resourceName: { type: String },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            notes: "",
        });
        this.notesBodyRef = useRef("notesBody");
        this._notesMarkup = "";
        this._notesScrollTop = 0;

        onWillStart(async () => {
            const [data] = await this.orm.read(
                "aps.resources",
                [this.props.resourceId],
                ["notes"],
            );
            this.state.notes = data?.notes || "";
            this._notesMarkup = this.state.notes ? markup(this.state.notes) : "";
            this.state.loading = false;
        });

        onMounted(() => this._renderMath());
        onWillPatch(() => {
            const el = this.notesBodyRef.el;
            this._notesScrollTop = el ? el.scrollTop : 0;
        });
        onPatched(() => {
            this._renderMath();
            const el = this.notesBodyRef.el;
            if (el) {
                el.scrollTop = this._notesScrollTop;
            }
        });
    }

    _renderMath() {
        const el = this.notesBodyRef.el;
        if (!el || !window.renderMathInElement) return;
        window.renderMathInElement(el, {
            delimiters: [
                { left: "$$", right: "$$", display: true },
                { left: "$", right: "$", display: false },
                { left: "\\(", right: "\\)", display: false },
                { left: "\\[", right: "\\]", display: true },
            ],
            throwOnError: false,
            ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
            ignoredClasses: ["katex", "katex-html"],
        });
    }

    get notesMarkup() {
        return this._notesMarkup;
    }
}
