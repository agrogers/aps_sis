import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onPatched, useRef } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";
import { createProgressCircleSvg } from "@aps_sis/js/utils/svg_progress_utils";
import { ResourceLinkButtons, openResourceLink } from "@aps_sis/components/resource_link_buttons/resource_link_buttons";

export class ResourceLinksField extends Component {
    static template = "aps_sis.ResourceLinksField";
    static components = { ResourceLinkButtons };
    static props = { ...standardFieldProps,
        size: { type: String, optional: true },
        showName: { type: Boolean, optional: true },
        showResults: { type: Boolean, optional: true },
     };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ progressData: {} });
        this.containerRef = useRef("linksContainer");
        this.lastRecordId = null;
        
        if (this.props.showResults) {
            onMounted(() => this.loadProgressData());
            onPatched(() => this.onPatched());
        }
    }

    onPatched() {
        const currentRecordId = this.props.record.resId;
        if (currentRecordId !== this.lastRecordId) {
            // Record changed, clear old data and reload
            this.state.progressData = {};
            this.loadProgressData();
        }
    }

    async loadProgressData() {
        this.lastRecordId = this.props.record.resId;
        const studentId = this.getStudentId();
        if (!studentId) return;
        
        const links = this.links;
        for (const link of links) {
            if (link.id) {
                try {
                    const data = await this.orm.call(
                        "aps.resource.task",
                        "get_progress_data_by_resource",
                        [link.id, studentId]
                    );
                    this.state.progressData[link.id] = data;
                } catch (e) {
                    console.error(`Failed to fetch progress for resource ${link.id}:`, e);
                }
            }
        }
        
        // Render SVGs after all data is loaded
        this.renderAllProgressSvgs();
    }

    renderAllProgressSvgs() {
        const container = this.containerRef.el;
        if (!container) return;
        
        const svgContainers = container.querySelectorAll('.progress-svg-container');
        svgContainers.forEach(el => {
            const resourceId = parseInt(el.dataset.resourceId, 10);
            const iconUrl = el.dataset.iconUrl || '';
            const progressData = this.state.progressData[resourceId];
            
            if (progressData) {
                el.innerHTML = '';
                const sizeNum = parseInt(this.props.size, 10) || 40;
                const outerPercent = progressData.weighted_result || 0;
                const outerColor = getColorForPercent(outerPercent);
                const segmentColors = (progressData.submission_results || []).map(r => getColorForPercent(r));
                
                const svg = createProgressCircleSvg(
                    outerPercent,
                    segmentColors,
                    sizeNum,
                    outerColor,
                    iconUrl
                );
                el.appendChild(svg);
            }
        });
    }

    getStudentId() {
        // Get student_id from the current record
        const studentField = this.props.record.data.student_id;
        if (studentField) {
            // Many2one field returns [id, name]
            if (Array.isArray(studentField)) {
                return studentField[0];
            }
            return studentField;
        }
        return null;
    }

    get links() {
        const value = this.props.record.data[this.props.name];
        if (!value) return [];
        // Handle both string JSON and already-parsed array
        if (typeof value === 'string') {
            try {
                return JSON.parse(value);
            } catch (e) {
                return [];
            }
        }
        return Array.isArray(value) ? value : [];
    }

    openUrl(linkData) {
        const context = {
            active_id: this.props.record.resId,
            active_model: this.props.record.resModel,
            out_of_marks: this.props.record.data.out_of_marks || 10,
            submission_state: this.props.record.data.state,
        };
        openResourceLink(linkData, { action: this.action, orm: this.orm }, context);
    }
}

export const resourceLinksField = {
    component: ResourceLinksField,
    supportedTypes: ["json"],
    supportedOptions: [
        {
            label: "Size",
            name: "size",
            type: "string",
            default: "24px",
        },
        {
            label: "Show Name",
            name: "show_name",
            type: "boolean",
            default: false,
        },
        {
            label: "Show Results",
            name: "show_results",
            type: "boolean",
            default: false,
        },
    ],    
    extractProps({ options }) {
        return {
            size: options.size || "24px",
            showName: options.show_name || false,
            showResults: options.show_results || false,
        };
    },
};

registry.category("fields").add("resource_links", resourceLinksField);
