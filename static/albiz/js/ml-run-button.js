(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    function readJsonScript(id) {
        var element = byId(id);
        if (!element) {
            return [];
        }
        try {
            return JSON.parse(element.textContent || '[]');
        } catch (error) {
            console.error('Unable to parse ML page messages.', error);
            return [];
        }
    }

    function hasSwal() {
        return typeof window.Swal !== 'undefined';
    }

    function messageIcon(level) {
        if ((level || '').indexOf('error') !== -1) {
            return 'error';
        }
        if ((level || '').indexOf('warning') !== -1) {
            return 'warning';
        }
        if ((level || '').indexOf('success') !== -1) {
            return 'success';
        }
        return 'info';
    }

    function messageTitle(icon) {
        if (icon === 'success') {
            return 'ML results refreshed';
        }
        if (icon === 'error') {
            return 'ML refresh failed';
        }
        if (icon === 'warning') {
            return 'ML refresh not started';
        }
        return 'ML results';
    }

    function showPageMessage() {
        if (!hasSwal()) {
            return;
        }
        var messages = readJsonScript('ml-page-messages');
        if (!Array.isArray(messages) || !messages.length) {
            return;
        }
        var message = messages[0];
        var icon = messageIcon(message.level);
        window.Swal.fire({
            title: messageTitle(icon),
            text: message.text || '',
            icon: icon,
            confirmButtonText: 'OK'
        });
    }

    function setRunningState(form) {
        var button = form.querySelector('[data-ml-run-button]');
        if (!button) {
            return;
        }
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> Running ML analysis...';
    }

    function submitWithLoading(form) {
        setRunningState(form);
        if (hasSwal()) {
            window.Swal.fire({
                title: 'Running ML analysis',
                text: 'Please wait while the modelling dataset is rebuilt and exploratory ML outputs are regenerated.',
                allowOutsideClick: false,
                allowEscapeKey: false,
                didOpen: function () {
                    window.Swal.showLoading();
                }
            });
        }
        form.submit();
    }

    function bindRunForm() {
        var form = byId('ml-run-form');
        if (!form) {
            return;
        }

        form.addEventListener('submit', function (event) {
            event.preventDefault();

            var title = form.getAttribute('data-confirm-title') || 'Refresh ML Results?';
            var text = form.getAttribute('data-confirm-text') || 'This will rebuild the modelling dataset and rerun exploratory ML analysis. It may take some time. No database writes are performed.';

            if (!hasSwal()) {
                if (window.confirm(text)) {
                    submitWithLoading(form);
                }
                return;
            }

            window.Swal.fire({
                title: title,
                text: text,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, run analysis',
                cancelButtonText: 'Cancel',
                reverseButtons: true
            }).then(function (result) {
                if (result.isConfirmed) {
                    submitWithLoading(form);
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        showPageMessage();
        bindRunForm();
    });
})();
