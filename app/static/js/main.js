/**
 * Balaji Fleet Compliance System - Client-side utilities
 */
document.addEventListener("DOMContentLoaded", function () {
    // Initialize all Bootstrap tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Auto-dismiss standard alerts after 6 seconds
    const autoAlerts = document.querySelectorAll(".alert-dismissible");
    autoAlerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            }
        }, 6000);
    });

    // Prevent double form submissions on buttons
    const forms = document.querySelectorAll("form");
    forms.forEach(function (form) {
        form.addEventListener("submit", function () {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                // Short timeout to allow native HTML5 validation to fire first
                setTimeout(function () {
                    if (form.checkValidity()) {
                        submitBtn.classList.add("disabled");
                    }
                }, 10);
            }
        });
    });
});
