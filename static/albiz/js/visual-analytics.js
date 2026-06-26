(function () {
    'use strict';

    function readChartData() {
        var element = document.getElementById('visual-analytics-data');
        if (!element) {
            return null;
        }

        try {
            return JSON.parse(element.textContent);
        } catch (error) {
            console.error('Unable to parse visual analytics chart data.', error);
            return null;
        }
    }

    function chartColors() {
        return ['#405189', '#0ab39c', '#f7b84b', '#f06548', '#299cdb', '#6559cc', '#34c38f', '#ff8a65', '#6c757d'];
    }

    function renderChart(selector, options) {
        var element = document.querySelector(selector);
        if (!element || !window.ApexCharts) {
            return;
        }

        new window.ApexCharts(element, options).render();
    }

    function pieOptions(dataset, chartType) {
        return {
            chart: {
                height: 280,
                type: chartType || 'donut',
                toolbar: { show: false }
            },
            colors: chartColors(),
            dataLabels: { enabled: false },
            labels: dataset.labels || [],
            legend: {
                position: 'bottom'
            },
            series: dataset.series || []
        };
    }

    function barOptions(dataset, horizontal) {
        var options = {
            chart: {
                height: 320,
                type: 'bar',
                toolbar: { show: false }
            },
            colors: ['#405189'],
            dataLabels: { enabled: false },
            grid: {
                borderColor: '#f1f1f1'
            },
            plotOptions: {
                bar: {
                    borderRadius: 3,
                    columnWidth: '55%',
                    horizontal: Boolean(horizontal)
                }
            },
            series: [{
                name: 'Companies',
                data: dataset.series || []
            }],
            xaxis: {
                categories: dataset.labels || [],
                labels: {}
            },
            yaxis: {
                labels: {}
            },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return Number(value).toLocaleString() + ' companies';
                    }
                }
            }
        };

        if (horizontal) {
            options.xaxis.labels.formatter = function (value) {
                return Number(value).toLocaleString();
            };
        } else {
            options.xaxis.labels.rotate = -45;
            options.yaxis.labels.formatter = function (value) {
                return Number(value).toLocaleString();
            };
        }

        return options;
    }

    document.addEventListener('DOMContentLoaded', function () {
        var data = readChartData();
        if (!data || !window.ApexCharts) {
            return;
        }

        renderChart('#legal-form-chart', pieOptions(data.legalForms, 'donut'));
        renderChart('#subject-status-chart', pieOptions(data.subjectStatuses, 'pie'));
        renderChart('#registration-year-chart', barOptions(data.registrationYears, false));
        renderChart('#ratio-band-chart', barOptions(data.ratioBands, false));
        renderChart('#risk-indicator-chart', barOptions(data.riskIndicators, true));
    });
})();
