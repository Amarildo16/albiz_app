(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    function readData() {
        var element = byId('company-financials-data');
        if (!element) {
            return [];
        }
        try {
            return JSON.parse(element.textContent || '[]');
        } catch (error) {
            console.error('Unable to parse company financial enrichment data.', error);
            return [];
        }
    }

    function numberOrNull(value) {
        if (value === null || value === '' || typeof value === 'undefined') {
            return null;
        }
        var parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function formatMoney(value) {
        var parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 'N/A';
        }
        return parsed.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function renderChart(rows) {
        var container = byId('company-financials-chart');
        var warning = byId('company-financials-chart-warning');
        if (!container || !Array.isArray(rows) || !rows.length) {
            return;
        }
        if (typeof window.ApexCharts === 'undefined') {
            if (warning) {
                warning.classList.remove('d-none');
            }
            return;
        }

        var years = rows.map(function (row) {
            return String(row.year);
        });
        var revenue = rows.map(function (row) {
            return numberOrNull(row.revenue_amount);
        });
        var profit = rows.map(function (row) {
            return numberOrNull(row.profit_before_tax_amount);
        });

        var chart = new window.ApexCharts(container, {
            chart: {
                type: 'line',
                height: 340,
                toolbar: { show: true },
                zoom: { enabled: true }
            },
            series: [
                { name: 'Revenue amount', data: revenue },
                { name: 'Profit before tax', data: profit }
            ],
            xaxis: {
                categories: years,
                title: { text: 'Financial year' }
            },
            yaxis: {
                labels: {
                    formatter: function (value) {
                        if (Math.abs(value) >= 1000000) {
                            return (value / 1000000).toFixed(1) + 'M';
                        }
                        if (Math.abs(value) >= 1000) {
                            return (value / 1000).toFixed(1) + 'K';
                        }
                        return value.toFixed(0);
                    }
                }
            },
            stroke: {
                curve: 'smooth',
                width: 3
            },
            markers: {
                size: 4
            },
            dataLabels: { enabled: false },
            colors: ['#405189', '#0ab39c'],
            legend: { position: 'top' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatMoney(value);
                    }
                }
            },
            noData: {
                text: 'No chart data available'
            }
        });
        chart.render();
    }

    document.addEventListener('DOMContentLoaded', function () {
        renderChart(readData());
    });
})();
