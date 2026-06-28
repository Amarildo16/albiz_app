(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    function readJsonScript(id) {
        var element = byId(id);
        if (!element) {
            return null;
        }
        try {
            return JSON.parse(element.textContent || '{}');
        } catch (_error) {
            return null;
        }
    }

    function hasApexCharts() {
        return typeof window.ApexCharts !== 'undefined';
    }

    function render(containerId, options) {
        var container = byId(containerId);
        if (!container) {
            return null;
        }
        if (!hasApexCharts()) {
            container.innerHTML = '<div class="alert alert-light border mb-0">Chart library is unavailable. The table below remains available.</div>';
            return null;
        }
        var chart = new window.ApexCharts(container, options);
        chart.render();
        return chart;
    }

    function hasSeries(dataset) {
        return dataset && Array.isArray(dataset.labels) && Array.isArray(dataset.series) && dataset.labels.length && dataset.series.length;
    }

    function colors() {
        return ['#405189', '#0ab39c', '#299cdb', '#f7b84b', '#f06548', '#6559cc', '#34c38f', '#6c757d'];
    }

    function numberValue(value) {
        var parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function formatCount(value) {
        return numberValue(value).toLocaleString();
    }

    function formatPercent(value) {
        return (numberValue(value) * 100).toFixed(1) + '%';
    }

    function emptyChartOptions(message) {
        return {
            chart: { type: 'bar', height: 240, toolbar: { show: false } },
            series: [],
            noData: { text: message || 'No chart data available' }
        };
    }

    function barOptions(dataset, settings) {
        settings = settings || {};
        if (!hasSeries(dataset)) {
            return emptyChartOptions();
        }
        return {
            chart: {
                type: 'bar',
                height: settings.height || 320,
                toolbar: { show: false }
            },
            colors: settings.colors || [colors()[0]],
            dataLabels: { enabled: false },
            plotOptions: {
                bar: {
                    horizontal: Boolean(settings.horizontal),
                    borderRadius: 3,
                    columnWidth: settings.columnWidth || '55%',
                    barHeight: settings.barHeight || '70%'
                }
            },
            grid: { borderColor: '#f1f1f1' },
            series: [{
                name: settings.seriesName || 'Companies',
                data: dataset.series || []
            }],
            xaxis: {
                categories: dataset.labels || [],
                labels: {
                    rotate: settings.horizontal ? 0 : -35,
                    formatter: settings.horizontal ? formatCount : undefined
                }
            },
            yaxis: {
                labels: {
                    formatter: settings.horizontal ? undefined : formatCount
                }
            },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatCount(value);
                    }
                }
            },
            responsive: [{
                breakpoint: 576,
                options: {
                    chart: { height: Math.min(settings.height || 320, 280) },
                    xaxis: { labels: { rotate: settings.horizontal ? 0 : -45 } }
                }
            }]
        };
    }

    function lineOptions(dataset, settings) {
        settings = settings || {};
        if (!hasSeries(dataset)) {
            return emptyChartOptions();
        }
        var labels = dataset.labels || [];
        var labelEvery = Number(settings.labelEvery || 1);
        return {
            chart: {
                type: 'line',
                height: settings.height || 320,
                toolbar: { show: false },
                zoom: { enabled: false }
            },
            colors: [settings.color || colors()[2]],
            stroke: { curve: 'smooth', width: 2 },
            markers: { size: 0 },
            series: [{
                name: settings.seriesName || 'Companies',
                data: dataset.series || []
            }],
            xaxis: {
                categories: labels,
                labels: {
                    rotate: settings.rotate || -45,
                    hideOverlappingLabels: true,
                    trim: true,
                    formatter: function (value) {
                        if (labelEvery <= 1) {
                            return value;
                        }
                        var index = labels.indexOf(value);
                        if (index === -1) {
                            return value;
                        }
                        return index % labelEvery === 0 || index === labels.length - 1 ? value : '';
                    }
                },
                tickAmount: settings.tickAmount
            },
            yaxis: {
                labels: {
                    formatter: formatCount
                }
            },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatCount(value);
                    }
                }
            },
            responsive: [{
                breakpoint: 576,
                options: {
                    chart: { height: Math.min(settings.height || 320, 280) },
                    xaxis: { labels: { rotate: -35 } }
                }
            }]
        };
    }

    function donutOptions(dataset, settings) {
        settings = settings || {};
        if (!hasSeries(dataset)) {
            return emptyChartOptions();
        }
        return {
            chart: {
                type: 'donut',
                height: settings.height || 300,
                toolbar: { show: false }
            },
            labels: dataset.labels || [],
            series: (dataset.series || []).map(numberValue),
            colors: settings.colors || colors(),
            dataLabels: { enabled: false },
            legend: { position: 'bottom' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatCount(value);
                    }
                }
            }
        };
    }

    function groupedMetricOptions(dataset, settings) {
        settings = settings || {};
        if (!dataset || !Array.isArray(dataset.models) || !dataset.models.length) {
            return emptyChartOptions();
        }
        return {
            chart: {
                type: 'bar',
                height: settings.height || 330,
                toolbar: { show: false }
            },
            colors: settings.colors || [colors()[0], colors()[1], colors()[2], colors()[3]],
            dataLabels: { enabled: false },
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '50%',
                    borderRadius: 3
                }
            },
            series: settings.series,
            xaxis: {
                categories: dataset.models,
                labels: { rotate: -25, trim: true }
            },
            yaxis: {
                min: 0,
                max: 1,
                labels: {
                    formatter: function (value) {
                        return Number(value).toFixed(2);
                    }
                }
            },
            legend: { position: 'top' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return Number(value).toFixed(4);
                    }
                }
            }
        };
    }

    function percentBarOptions(dataset, settings) {
        settings = settings || {};
        if (!hasSeries(dataset)) {
            return emptyChartOptions();
        }
        return {
            chart: {
                type: 'bar',
                height: settings.height || 330,
                toolbar: { show: false }
            },
            colors: settings.colors || [colors()[1]],
            dataLabels: {
                enabled: true,
                formatter: function (value) {
                    return Number(value).toFixed(1) + '%';
                }
            },
            plotOptions: {
                bar: {
                    horizontal: true,
                    borderRadius: 3,
                    barHeight: settings.barHeight || '65%'
                }
            },
            series: [{
                name: settings.seriesName || 'Completeness',
                data: dataset.series || []
            }],
            xaxis: {
                categories: dataset.labels || [],
                max: 100,
                labels: {
                    formatter: function (value) {
                        return Number(value).toFixed(0) + '%';
                    }
                }
            },
            yaxis: { labels: { maxWidth: 260 } },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return Number(value).toFixed(1) + '%';
                    }
                }
            },
            responsive: [{
                breakpoint: 576,
                options: {
                    chart: { height: Math.min(settings.height || 330, 300) },
                    dataLabels: { enabled: false }
                }
            }]
        };
    }

    function renderRegistryCharts(data) {
        if (!data) {
            return;
        }
        render('registry-coverage-funnel-chart', barOptions(data.coverageFunnel, {
            horizontal: true,
            height: 300,
            seriesName: 'Companies',
            colors: ['#405189']
        }));
        render('registry-legal-form-chart', barOptions(data.legalForms, {
            horizontal: true,
            height: 280,
            seriesName: 'QKB companies',
            colors: ['#0ab39c']
        }));
        render('registry-top-cities-chart', barOptions(data.topCities, {
            horizontal: true,
            height: 340,
            seriesName: 'QKB companies',
            colors: ['#299cdb']
        }));
        render('registry-registration-year-chart', lineOptions(data.registrationYears, {
            height: 320,
            seriesName: 'Registrations',
            labelEvery: 5,
            tickAmount: 12
        }));
    }

    function renderRiskCharts(data) {
        if (!data) {
            return;
        }
        render('risk-indicator-frequency-chart', barOptions(data.riskIndicatorFrequency, {
            horizontal: true,
            height: 360,
            seriesName: 'Companies',
            colors: ['#f7b84b']
        }));
        render('risk-indicator-count-chart', donutOptions(data.riskIndicatorCountDistribution, {
            height: 300,
            colors: ['#0ab39c', '#f7b84b', '#f06548', '#405189']
        }));
    }

    function renderDashboardCharts(data) {
        if (!data) {
            return;
        }
        render('dashboard-data-coverage-chart', barOptions(data.dataCoverageSnapshot, {
            horizontal: true,
            height: 300,
            seriesName: 'Rows / companies',
            colors: ['#405189']
        }));
    }

    function renderDataQualityCharts(data) {
        if (!data) {
            return;
        }
        render('data-quality-coverage-chart', barOptions(data.coverageSnapshot, {
            horizontal: true,
            height: 300,
            seriesName: 'Rows / companies',
            colors: ['#405189']
        }));
        render('data-quality-completeness-chart', percentBarOptions(data.completenessRates, {
            height: 340,
            seriesName: 'Present rate',
            colors: ['#0ab39c']
        }));
        render('data-quality-legal-form-chart', barOptions(data.legalForms, {
            horizontal: true,
            height: 300,
            seriesName: 'Companies',
            colors: ['#299cdb']
        }));
        render('data-quality-status-chart', barOptions(data.statuses, {
            horizontal: true,
            height: 260,
            seriesName: 'Companies',
            colors: ['#f7b84b']
        }));
    }

    window.AlbizCharts = {
        readJsonScript: readJsonScript,
        render: render,
        barOptions: barOptions,
        lineOptions: lineOptions,
        donutOptions: donutOptions,
        groupedMetricOptions: groupedMetricOptions,
        percentBarOptions: percentBarOptions,
        formatCount: formatCount,
        formatPercent: formatPercent
    };

    document.addEventListener('DOMContentLoaded', function () {
        renderRegistryCharts(readJsonScript('registry-chart-data'));
        renderRiskCharts(readJsonScript('risk-overview-chart-data'));
        renderDashboardCharts(readJsonScript('dashboard-chart-data'));
        renderDataQualityCharts(readJsonScript('data-quality-chart-data'));
    });
})();
