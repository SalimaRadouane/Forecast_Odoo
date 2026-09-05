/** @odoo-module **/

import { Component, useRef, onWillStart, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class SaleForecastChart extends Component {
    static template = "sale_forecast.ForecastChart";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.chart = null;

        this.state = useState({
            products: [],
            selectedProductId: null,
            generating: false,
            forecast30Days: 0,
            forecastRevenue: 0,
            stockouts: 0,
            confidence: 0,
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");

            this.state.products = await this.orm.call(
                "product.product",
                "search_read",
                [[["id", "in", await this._getForecastProductIds()]], ["id", "name"]]
            );

            if (this.state.products.length) {
                this.state.selectedProductId = this.state.products[0].id;
            }

            await this.loadKpis();
        });

        onMounted(() => {
            this.renderChart();
        });
    }

    async _getForecastProductIds() {
        const data = await this.orm.call(
            "sale.forecast",
            "get_forecast_chart_data",
            []
        );

        return [...new Set(data.map((d) => d.product_id))];
    }

    async loadKpis() {
        const data = await this.orm.call(
            "sale.forecast",
            "get_forecast_kpis",
            [this.state.selectedProductId]
        );

        this.state.forecast30Days = data.forecast_30_days;
        this.state.forecastRevenue = data.forecast_revenue;
        this.state.stockouts = data.stockouts;
        this.state.confidence = data.confidence;
    }

    async onGenerateForecast() {
        this.state.generating = true;

        try {
            await this.orm.call(
                "sale.forecast",
                "generate_product_forecast",
                [[]]
            );

            this.state.products = await this.orm.call(
                "product.product",
                "search_read",
                [[["id", "in", await this._getForecastProductIds()]], ["id", "name"]]
            );

            if (
                this.state.products.length &&
                !this.state.selectedProductId
            ) {
                this.state.selectedProductId =
                    this.state.products[0].id;
            }

            await this.renderChart();
            await this.loadKpis();

            this.notification.add(
                "Forecast report generated successfully.",
                {
                    type: "success",
                }
            );
        } catch (error) {
            this.notification.add(
                "An error occurred while generating the forecast report.",
                {
                    type: "danger",
                }
            );

            console.error(error);
        } finally {
            this.state.generating = false;
        }
    }

    async renderChart() {
        if (!this.state.selectedProductId) {
            return;
        }

        const data = await this.orm.call(
            "sale.forecast",
            "get_forecast_chart_data",
            [this.state.selectedProductId]
        );

        const labels = data.map((d) => d.date);
        const values = data.map((d) => d.predicted_sales);
        const lowerBounds = data.map((d) => d.lower_bound);
        const upperBounds = data.map((d) => d.upper_bound);

        if (this.chart) {
            this.chart.destroy();
        }

        const ctx = this.canvasRef.el.getContext("2d");

        this.chart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        // Hidden from the legend (see plugins.legend.labels.filter
                        // below): this is a visual confidence band, not a
                        // series the user picks.
                        label: "Upper Bound",
                        data: upperBounds,
                        borderColor: "transparent",
                        backgroundColor: "rgba(46, 125, 50, 0.08)",
                        fill: "+1",
                        pointRadius: 0,
                        tension: 0.3,
                    },
                    {
                        label: "Lower Bound",
                        data: lowerBounds,
                        borderColor: "transparent",
                        backgroundColor: "rgba(46, 125, 50, 0.08)",
                        fill: false,
                        pointRadius: 0,
                        tension: 0.3,
                    },
                    {
                        label: "Forecast Sales",
                        data: values,
                        borderColor: "#2E7D32",
                        backgroundColor: "rgba(46, 125, 50, 0.1)",
                        fill: false,
                        tension: 0.3,
                        pointRadius: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: "Date",
                        },
                    },
                    y: {
                        title: {
                            display: true,
                            text: "Forecast Quantity",
                        },
                        beginAtZero: true,
                    },
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            // Only show the actual forecast line in the
                            // legend; the upper/lower bound datasets only
                            // exist to draw the confidence band.
                            filter: (item) =>
                                item.text === "Forecast Sales",
                        },
                    },
                },
            },
        });
    }

    async onProductChange(ev) {
        this.state.selectedProductId = parseInt(
            ev.target.value,
            10
        );

        await this.renderChart();
        await this.loadKpis();
    }
}

registry
    .category("actions")
    .add("sale_forecast_chart_action", SaleForecastChart);