/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ImageField } from "@web/views/fields/image/image_field";
import { onMounted, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";
import { createProgressCircleSvg } from "@aps_sis/js/utils/svg_progress_utils";

export class ImageResultField extends ImageField {
    static template = "aps_sis.ImageResultField";
    static props = {
        ...ImageField.props,
        taskId: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.containerRef = useRef("svgContainer");
        this.orm = useService("orm");
        this.lastTaskId = null;
        onMounted(() => this.mountSvg());
        onPatched(() => this.onPatched());
    }

    onPatched() {
        const currentTaskId = this.getRecordId();
        if (currentTaskId !== this.lastTaskId) {
            this.mountSvg();
        }
    }

    async mountSvg() {
        const container = this.containerRef.el;
        if (container) {
            container.innerHTML = '';
            const url = this.getUrl(this.props.name);
            const size = this.props.width || 120;
            const taskId = this.getRecordId();
            this.lastTaskId = taskId;
            
            // Fetch progress data from the server
            let outerPercent = 0;
            let outerColor = "#e6e6e6";
            let segmentColors = [];
            
            if (taskId) {
                try {
                    const data = await this.orm.call(
                        "aps.resource.task",
                        "get_progress_data",
                        [taskId]
                    );
                    outerPercent = data.weighted_result || 0;
                    outerColor = getColorForPercent(outerPercent);
                    segmentColors = (data.submission_results || []).map(r => getColorForPercent(r));
                } catch (e) {
                    console.error("Failed to fetch progress data:", e);
                }
            }
            
            const svg = createProgressCircleSvg(outerPercent, segmentColors, size, outerColor, url);
            container.appendChild(svg);
        }
    }

    getRecordId() {
        const field = this.props.taskId;
        if (field && this.props.record.data[field] !== undefined) {
            const value = this.props.record.data[field];
            // Handle Many2one fields (value is [id, name])
            if (Array.isArray(value)) {
                return value[0];
            }
            return value;
        }
        return this.props.record.resId;
    }

    get sizeStyle() {
        let style = "";
        if (this.props.width) {
            style += `width: ${this.props.width}px;`;
        }
        if (this.props.height) {
            style += `height: ${this.props.height}px;`;
        }
        return style;
    }

    get imgClass() {
        return "img";
    }
}

export const imageResultField = {
    component: ImageResultField,
    extractProps({ options }) {
        const props = {};
        if (options.size && Array.isArray(options.size)) {
            props.width = options.size[0];
            props.height = options.size[1];
        }
        if (options.task_id) {
            props.taskId = options.task_id;
        }
        return props;
    },
};

registry.category("fields").add("image_result", imageResultField);