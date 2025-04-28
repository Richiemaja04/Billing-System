// static/js/income.js
$(document).ready(function() {
    // DataTable Initialization
    const incomeTable = $('#incomeTable').DataTable({
        responsive: true,
        order: [[0, 'desc']],
        ajax: { url: '/api/income', dataSrc: '' },
        columns: [
            { data: 'date', render: formatDate },
            { data: 'description' },
            { data: 'amount', render: formatCurrency, className: 'text-end' },
            { data: 'payment_mode' }, // Added payment_mode column display
            { data: 'id', orderable: false, className: 'text-center', render: function(data, type, row) {
                    return `<button class="btn btn-sm btn-warning edit-income-btn" data-id="${data}" data-row='${JSON.stringify(row)}'><i class="fas fa-edit"></i></button> <button class="btn btn-sm btn-danger delete-income-btn" data-id="${data}" data-bs-toggle="tooltip" title="Delete"><i class="fas fa-trash"></i></button>`;
                }
            }
        ],
        drawCallback: function() {
            $('[data-bs-toggle="tooltip"]').tooltip();
            loadIncomeSummary(); // Reload summary whenever table redraws (e.g., after add/edit/delete)
        },
        language: { search: "_INPUT_", searchPlaceholder: "Search...", /* other options */ },
        dom: '<"row"<"col-sm-12 col-md-6"l><"col-sm-12 col-md-6"f>>' + '<"row dt-row"<"col-sm-12"tr>>' + '<"row"<"col-sm-12 col-md-5"i><"col-sm-12 col-md-7"p>>',
        lengthMenu: [[10, 25, 50, -1], [10, 25, 50, "All"]]
    });

    loadPaymentModes(); // Load modes into selects

    // Initial load for summary
    loadIncomeSummary();

    const today = new Date().toISOString().split('T')[0];
    $('#incomeDate').val(today);

    // Event Listeners (Delegated)
    $('#incomeTable tbody').on('click', '.edit-income-btn', function() { try { editIncomeRecord(JSON.parse($(this).attr('data-row'))); } catch(e) { showAlert("Error loading data.", "danger"); }}); // Pass full row data
    $('#incomeTable tbody').on('click', '.delete-income-btn', function() { showDeleteIncomeModal($(this).data('id')); });
    $('#saveIncomeBtn').click(saveIncome);
    $('#updateIncomeBtn').click(updateIncomeRecord); // Listener for static edit modal
    $('#confirmDeleteIncomeBtn').click(deleteIncomeRecordConfirmed); // Listener for static delete modal
    $('#exportIncomeBtn').click(exportIncomeToExcel);
     $('#addIncomeModal').on('hidden.bs.modal', clearIncomeForm);


    // --- Functions ---

     function loadPaymentModes() { // Reuse payment modes
         $.ajax({
            url: '/api/payment-modes', type: 'GET',
            success: function(modes) {
                const $addSelect = $('#incomePaymentMode'); // Add modal
                const $editSelect = $('#editIncomePaymentMode'); // Edit modal
                $addSelect.find('option:not([value=""])').remove(); // Clear existing, keep placeholder
                $editSelect.find('option:not([value=""])').remove();
                modes.forEach(function(mode) {
                    $addSelect.append(`<option value="${mode}">${mode}</option>`);
                    $editSelect.append(`<option value="${mode}">${mode}</option>`);
                });
            }, error: function() { showAlert("Could not load payment mode options.", "warning"); }
        });
    }

    function loadIncomeSummary() {
        // Set defaults while loading
        $('#totalCash').text('Loading...');
        $('#totalAccount').text('Loading...');
        $('#totalOther').text('Loading...'); // Use a combined field or add more spans

        $.ajax({
            url: '/api/income/summary', // New endpoint
            type: 'GET',
            success: function(response) {
                if (response.success && response.summary) {
                    const summary = response.summary;
                    let totalOtherModes = 0;
                    let otherModesLabels = [];

                    $('#totalCash').text(formatCurrency(summary['CASH'] || 0));
                    $('#totalAccount').text(formatCurrency(summary['ACCOUNT'] || 0));

                    // Calculate "Other" totals (e.g., UPI, CARD, Unspecified)
                    for (const mode in summary) {
                        if (mode !== 'CASH' && mode !== 'ACCOUNT') {
                            totalOtherModes += (summary[mode] || 0);
                            if (summary[mode] > 0) { // Only list modes with amounts
                                 otherModesLabels.push(mode);
                            }
                        }
                    }
                    let otherText = formatCurrency(totalOtherModes);
                    if(otherModesLabels.length > 0) {
                         otherText += ` (${otherModesLabels.join(', ')})`;
                    }
                    $('#totalOther').text(otherText);

                } else {
                     $('#totalCash, #totalAccount, #totalOther').text('Error');
                     showAlert(response.message || 'Could not load income summary.', 'warning');
                }
            },
            error: function() {
                 $('#totalCash, #totalAccount, #totalOther').text('Error');
                 showAlert('Failed to fetch income summary.', 'danger');
            }
        });
    }


    function saveIncome() {
        const date = $('#incomeDate').val();
        const description = $('#incomeDescription').val().trim();
        const amountStr = $('#incomeAmount').val();
        const paymentMode = $('#incomePaymentMode').val(); // Get selected mode

        if (!date || !description || !amountStr || isNaN(parseFloat(amountStr))) {
            showAlert('Please fill fields correctly.', 'warning'); return;
        }
        const amount = parseFloat(amountStr);

        const incomeData = { date: date, description: description, amount: amount, payment_mode: paymentMode || null }; // Send mode (or null if empty)

        $.ajax({
            url: '/api/income', type: 'POST', contentType: 'application/json', data: JSON.stringify(incomeData),
            success: function(response) { if (response.success) { $('#addIncomeModal').modal('hide'); showAlert('Income saved!', 'success'); incomeTable.ajax.reload(); /* Summary reloads on draw */ } else { showAlert(response.message || 'Error saving.', 'danger'); } },
            error: function(xhr) { const msg = xhr.responseJSON ? xhr.responseJSON.message : 'API error.'; showAlert(msg, 'danger'); }
        });
    }

    function editIncomeRecord(record) { // Receive record data
        if (!record) { showAlert('Income data not found!', 'danger'); return; }
        // Populate static edit modal
        $('#editIncomeId').val(record.id);
        $('#editIncomeDate').val(record.date.split('T')[0]);
        $('#editIncomeDescription').val(record.description);
        $('#editIncomeAmount').val(record.amount);
        $('#editIncomePaymentMode').val(record.payment_mode || ''); // Set payment mode, default to empty if null
        $('#editIncomeModal').modal('show');
    }

    function updateIncomeRecord() {
        const recordId = $('#editIncomeId').val();
        const date = $('#editIncomeDate').val();
        const description = $('#editIncomeDescription').val().trim();
        const amountStr = $('#editIncomeAmount').val();
        const paymentMode = $('#editIncomePaymentMode').val(); // Get mode from edit modal

        if (!date || !description || !amountStr || isNaN(parseFloat(amountStr)) || !recordId) {
            showAlert('Please fill fields correctly.', 'warning'); return;
        }
        const amount = parseFloat(amountStr);

        const incomeData = { date: date, description: description, amount: amount, payment_mode: paymentMode || null }; // Send mode

        $.ajax({
            url: `/api/income/${recordId}`, type: 'PUT', contentType: 'application/json', data: JSON.stringify(incomeData),
            success: function(response) { if (response.success) { $('#editIncomeModal').modal('hide'); showAlert('Income updated!', 'success'); incomeTable.ajax.reload(); } else { showAlert(response.message || 'Error updating.', 'danger'); } },
            error: function(xhr) { const msg = xhr.responseJSON ? xhr.responseJSON.message : 'API error.'; showAlert(msg, 'danger'); }
        });
    }

     function showDeleteIncomeModal(recordId) { /* ... Use static modal ... */ $('#deleteIncomeId').val(recordId); $('#confirmDeleteIncomeModal').modal('show'); }
     function deleteIncomeRecordConfirmed() { /* ... Use static modal ... */ const recordId = $('#deleteIncomeId').val(); if (!recordId) return; $.ajax({ url: `/api/income/${recordId}`, type: 'DELETE', success: function(response) { $('#confirmDeleteIncomeModal').modal('hide'); if (response.success) { showAlert('Income deleted!', 'success'); incomeTable.ajax.reload(); } else { showAlert(response.message || 'Error deleting.', 'danger'); } }, error: function(xhr) { $('#confirmDeleteIncomeModal').modal('hide'); const msg = xhr.responseJSON ? xhr.responseJSON.message : 'API error.'; showAlert(msg, 'danger'); } }); }
     function clearIncomeForm() { $('#addIncomeForm')[0].reset(); const today = new Date().toISOString().split('T')[0]; $('#incomeDate').val(today); $('#incomePaymentMode').val(''); } // Reset select too
     function exportIncomeToExcel() { window.location.href = '/api/export/income'; }

    // Shared Helper Functions (Ensure defined once, e.g., in a separate common.js or copy here)
    function showAlert(message, type) { const alertHtml = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">${message}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>`; $('#alertArea').html(alertHtml); setTimeout(function() { $('.alert').alert('close'); }, 5000); }
    function formatDate(dateString) { if (!dateString) return ''; try { const date = new Date(dateString + 'T00:00:00'); return date.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { return dateString; } }
    function formatCurrency(amount) { const num = parseFloat(amount); if (isNaN(num)) return '₹0.00'; const formatter = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 }); return formatter.format(num); }

}); // End document ready