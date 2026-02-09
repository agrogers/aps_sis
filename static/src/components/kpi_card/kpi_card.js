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
}

KpiCard.template = "apex_dashboard.KpiCard"; // Matches the t-name in kpi_card.xml