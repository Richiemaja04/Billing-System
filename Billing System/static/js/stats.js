// static/js/stats.js
$(document).ready(function() {
    let monthlyChart = null; // Variable to hold the chart instance

    // Load data and draw chart on page load
    loadStatsData();

    // Function to load statistics from the API
    function loadStatsData() {
        // showSpinner(); // Optional: show loading indicator

        $.ajax({
            url: '/api/stats',
            type: 'GET',
            success: function(response) {
                if (response.success) {
                    updateDashboardCards(response);
                    prepareAndDrawChart(response.monthly_data || []);
                } else {
                    console.error("API Error:", response.message);
                    showStatError("Could not load statistics data from server.");
                }
            },
            error: function(xhr) {
                console.error("AJAX Error:", xhr);
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'Failed to connect to statistics API.';
                showStatError(errorMsg);
            },
            complete: function() {
                // hideSpinner(); // Optional: hide loading indicator
            }
        });
    }

    // Function to update the summary cards
    function updateDashboardCards(data) {
        $('#totalIncome').text(formatCurrency(data.total_income || 0));
        $('#totalExpenses').text(formatCurrency(data.total_expenses || 0));
        $('#netProfit').text(formatCurrency(data.net_profit || 0));
        $('#pendingPayments').text(formatCurrency(data.pending_payments || 0));

        // Update Net Profit card color
        const $netProfitCard = $('#netProfit').closest('.card'); // Find parent card
        $netProfitCard.removeClass('bg-success bg-danger'); // Remove existing classes
        if (data.net_profit >= 0) {
            $netProfitCard.addClass('bg-success');
        } else {
            $netProfitCard.addClass('bg-danger');
        }
    }

    // Function to process monthly data and draw/update the chart
    function prepareAndDrawChart(monthlyData) {
        const labels = [];
        const incomeDataset = [];
        const expensesDataset = [];

        // Ensure monthlyData is an array
        if (!Array.isArray(monthlyData)) {
             console.error("Monthly data is not an array:", monthlyData);
             monthlyData = []; // Prevent errors later
        }


        // Process data received from API (already sorted by backend)
        monthlyData.forEach(item => {
            // Format month label (e.g., Apr 2025)
            try {
                const date = new Date(item.month + '-01T00:00:00'); // Add day for Date object
                const monthName = date.toLocaleString('default', { month: 'short' });
                const year = date.getFullYear();
                labels.push(`${monthName} ${year}`);
            } catch (e) {
                 labels.push(item.month); // Fallback label
            }

            incomeDataset.push(item.income || 0);
            expensesDataset.push(item.expenses || 0);
        });

        const chartData = {
            labels: labels,
            datasets: [
                {
                    label: 'Income',
                    data: incomeDataset,
                    backgroundColor: 'rgba(40, 167, 69, 0.7)', // Success color
                    borderColor: 'rgba(40, 167, 69, 1)',
                    borderWidth: 1
                },
                {
                    label: 'Expenses',
                    data: expensesDataset,
                    backgroundColor: 'rgba(220, 53, 69, 0.7)', // Danger color
                    borderColor: 'rgba(220, 53, 69, 1)',
                    borderWidth: 1
                }
            ]
        };

        drawOrUpdateChart(chartData);
    }

    // Function to draw or update the Chart.js instance
    function drawOrUpdateChart(chartData) {
        const ctx = document.getElementById('monthlyChart');
        if (!ctx) {
            console.error("Canvas element #monthlyChart not found.");
            return;
        }
        const context = ctx.getContext('2d');

        if (monthlyChart) {
            // Update existing chart
            monthlyChart.data = chartData;
            monthlyChart.update();
            // console.log("Chart updated");
        } else {
            // Create new chart
            monthlyChart = new Chart(context, {
                type: 'bar',
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false, // Allow custom height via canvas attributes or CSS
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    // Use the same currency formatter
                                    return formatCurrency(value);
                                }
                            }
                        },
                        x: {
                             // Optional: configure x-axis if needed
                        }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let label = context.dataset.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    // Use currency formatter for tooltip value
                                    label += formatCurrency(context.raw);
                                    return label;
                                }
                            }
                        },
                        legend: {
                            position: 'top', // Position legend
                        }
                    }
                }
            });
            // console.log("Chart created");
        }
    }

    // Function to show errors specifically on the stats page
    function showStatError(message) {
        // You could display this in the chart area or a dedicated alert zone
         const chartContainer = $('#monthlyChart').parent(); // Get card body
         chartContainer.html(`<div class="alert alert-danger">${message}</div>`);
         // Clear dashboard card values
         $('#totalIncome, #totalExpenses, #netProfit, #pendingPayments').text('Error');

    }

    // --- Currency Formatter (needed locally) ---
    function formatCurrency(amount) {
        const num = parseFloat(amount);
        if (isNaN(num)) return '₹0.00';
        const formatter = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return formatter.format(num);
    }

    // Optional: Spinner functions
    // function showSpinner() { $('.spinner-overlay').show(); }
    // function hideSpinner() { $('.spinner-overlay').hide(); }

}); // End document ready