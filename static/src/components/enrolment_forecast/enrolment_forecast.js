import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";


export class EnrolmentForecast extends Component {
    static template = "aps_sis.EnrolmentForecast";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: "",
            options: null,
            forecast: null,
            academicYearId: null,
            numberOfYears: 5,
            basis: "confirmed",
        });
        this.onAcademicYearChange = this.onAcademicYearChange.bind(this);
        this.onYearsChange = this.onYearsChange.bind(this);
        this.onBasisChange = this.onBasisChange.bind(this);
        this.onDetailClick = this.onDetailClick.bind(this);

        onWillStart(async () => {
            try {
                this.state.options = await this.orm.call(
                    "aps.enrolment.forecast",
                    "get_options",
                    [],
                );
                this.state.academicYearId = this.state.options.default_year_id;
                await this.loadForecast();
            } catch (error) {
                this.state.error = error.message || "Unable to load the enrolment forecast.";
                this.state.loading = false;
            }
        });
    }

    async loadForecast() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.forecast = await this.orm.call(
                "aps.enrolment.forecast",
                "get_forecast_data",
                [
                    this.state.academicYearId,
                    this.state.numberOfYears,
                    this.state.basis,
                ],
            );
        } catch (error) {
            this.state.forecast = null;
            this.state.error = error.message || "Unable to calculate the enrolment forecast.";
        } finally {
            this.state.loading = false;
        }
    }

    async onAcademicYearChange(event) {
        this.state.academicYearId = Number(event.currentTarget.value);
        await this.loadForecast();
    }

    async onYearsChange(event) {
        this.state.numberOfYears = Number(event.currentTarget.value);
        await this.loadForecast();
    }

    async onBasisChange(event) {
        this.state.basis = event.currentTarget.value;
        await this.loadForecast();
    }

    async onDetailClick(event) {
        const button = event.currentTarget;
        try {
            const action = await this.orm.call(
                "aps.enrolment.forecast",
                "action_open_students",
                [
                    this.state.academicYearId,
                    this.state.numberOfYears,
                    this.state.basis,
                    Number(button.dataset.yearIndex),
                    Number(button.dataset.levelId),
                    button.dataset.movement,
                ],
            );
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = error.message || "Unable to open the selected students.";
        }
    }
}


registry.category("actions").add("aps_enrolment_forecast", EnrolmentForecast);