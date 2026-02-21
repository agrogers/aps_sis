import { Component } from "@odoo/owl";

export class KpiCard extends Component {
    /**
     * The component receives props from the parent dashboard:
     * - name: The title of the KPI (e.g., "Quotations") [cite: 17]
     * - value: The main numeric value to display [cite: 17]
     * - percentage: The change percentage [cite: 17]
     * - icon: The FontAwesome icon class [cite: 14]
     * - onClick: The function to execute for drill-down actions 
     */
    static props = {
        name: { type: String, optional: true },
        value: { type: [Number, String], optional: true },
        max: { type: [Number, String], optional: true },
        zones: { type: Array, optional: true },
        points_from_next: { type: [Number, String], optional: true },
        total_students: { type: [Number, String], optional: true },
        icon: { type: String, optional: true },
        period_name: { type: String, optional: true },
        onClick: { type: Function, optional: true },
        percentage: { type: [Number, String], optional: true },
    };    
}

KpiCard.template = "apex_dashboard.KpiCard"; // Matches the t-name in kpi_card.xml