// static/js/expenses.js
$(document).ready(function() {
    // Initialize DataTable
    const expensesTable = $('#expensesTable').DataTable({
        responsive: true, // Added responsiveness
        order: [[0, 'desc']], // Sort by date descending
        // Data source is AJAX
        ajax: {
            url: '/api/expenses',
            dataSrc: '' // Response is expected to be an array of objects
        },
        columns: [
            { data: 'date', render: formatDate }, // Use helper function if available, else simple render
            { data: 'description' },
            { 
                data: 'quantity',
                render: function(data) {
                    return data || 1; // Default to 1 if quantity is not available
                },
                className: 'text-center'
            },
            {
                data: 'amount',
                render: function(data) {
                    return formatCurrency(data); // Use helper function
                },
                className: 'text-end' // Align amount right
            },
            {
                data: 'id', // Use 'id' from API response
                orderable: false,
                className: 'text-center',
                render: function(data, type, row) {
                    // Added data-row attribute to store full row data for editing
                    return `
                        <button class="btn btn-sm btn-warning edit-expense" data-id="${data}" data-row='${JSON.stringify(row)}' data-bs-toggle="tooltip" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger delete-expense-btn" data-id="${data}" data-bs-toggle="tooltip" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    `;
                }
            }
        ],
        // Callback to initialize tooltips after table draw
        drawCallback: function() {
            $('[data-bs-toggle="tooltip"]').tooltip();
        },
        // Add language options for consistency if needed
         language: {
             search: "_INPUT_",
             searchPlaceholder: "Search...",
             lengthMenu: "Show _MENU_ entries",
             info: "Showing _START_ to _END_ of _TOTAL_ entries",
             emptyTable: "No expenses found",
             infoEmpty: "Showing 0 to 0 of 0 entries",
             infoFiltered: "(filtered from _MAX_ total entries)"
         },
         dom: '<"row"<"col-sm-12 col-md-6"l><"col-sm-12 col-md-6"f>>' + // Length and Filter
              '<"row dt-row"<"col-sm-12"tr>>' + // Table
              '<"row"<"col-sm-12 col-md-5"i><"col-sm-12 col-md-7"p>>', // Info and Pagination
    });

    // Set today's date as default for the add form
    $('#expenseDate').val(new Date().toISOString().split('T')[0]);

    // --- Save/Update Expense ---
    $('#saveExpenseBtn').on('click', function() {
        const expenseId = $(this).data('edit-id'); // Check if editing
        const date = $('#expenseDate').val();
        const description = $('#expenseDescription').val();
        const quantity = $('#expenseQuantity').val();
        const amount = $('#expenseAmount').val();

        if (!date || !description || !amount || isNaN(parseFloat(amount)) || !quantity || isNaN(parseInt(quantity))) {
            showAlert('Please fill all fields correctly.', 'warning');
            return;
        }

        const expenseData = {
            date: date,
            description: description,
            quantity: parseInt(quantity),
            amount: parseFloat(amount)
        };

        const ajaxUrl = expenseId ? `/api/expenses/${expenseId}` : '/api/expenses';
        const ajaxMethod = expenseId ? 'PUT' : 'POST';

        // Show spinner (optional)
        // showSpinner();

        $.ajax({
            url: ajaxUrl,
            type: ajaxMethod,
            contentType: 'application/json',
            data: JSON.stringify(expenseData),
            success: function(response) {
                if (response.success) {
                    $('#addExpenseModal').modal('hide');
                    showAlert(response.message, 'success');
                    expensesTable.ajax.reload(); // Reload DataTable data
                } else {
                    showAlert(response.message || 'An error occurred.', 'danger');
                }
            },
            error: function(xhr) {
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'An error occurred while saving the expense.';
                showAlert(errorMsg, 'danger');
            },
            complete: function() {
                // hideSpinner(); // Hide spinner
            }
        });
    });

    // --- Edit Expense Button Click (Event Delegation) ---
    $('#expensesTable tbody').on('click', '.edit-expense', function() {
        try {
            const rowData = JSON.parse($(this).attr('data-row')); // Get row data stored earlier
            const id = rowData.id; // Get ID

            // Populate the modal
            $('#expenseDate').val(rowData.date);
            $('#expenseDescription').val(rowData.description);
            $('#expenseQuantity').val(rowData.quantity || 1); // Default to 1 if not set
            $('#expenseAmount').val(rowData.amount);

            // Change modal title and button text/data
            $('#addExpenseModal .modal-title').html('<i class="fas fa-edit me-2"></i>Edit Expense');
            $('#saveExpenseBtn').text('Update Expense').data('edit-id', id); // Store ID for update

            $('#addExpenseModal').modal('show');
        } catch (e) {
            console.error("Error parsing row data for edit:", e);
            showAlert("Could not load expense data for editing.", "danger");
        }
    });

    // --- Delete Expense Button Click (Event Delegation) ---
    $('#expensesTable tbody').on('click', '.delete-expense-btn', function() {
        const expenseId = $(this).data('id');
        // Store the expense ID in the hidden input and show the confirmation modal
        $('#deleteExpenseId').val(expenseId);
        $('#confirmDeleteExpenseModal').modal('show');
    });

    // --- Confirm Delete Button Click ---
    $('#confirmDeleteExpenseBtn').on('click', function() {
        const expenseId = $('#deleteExpenseId').val();
        
        // Show spinner (optional)
        // showSpinner();
        
        $.ajax({
            url: `/api/expenses/${expenseId}`,
            type: 'DELETE',
            success: function(response) {
                if (response.success) {
                    $('#confirmDeleteExpenseModal').modal('hide');
                    showAlert(response.message, 'success');
                    expensesTable.ajax.reload();
                } else {
                    showAlert(response.message || 'An error occurred.', 'danger');
                }
            },
            error: function(xhr) {
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'An error occurred while deleting the expense.';
                showAlert(errorMsg, 'danger');
            },
            complete: function() {
                // hideSpinner();
            }
        });
    });

    // --- Reset modal when closed ---
    $('#addExpenseModal').on('hidden.bs.modal', function() {
        $('#addExpenseForm')[0].reset();
        $('#expenseDate').val(new Date().toISOString().split('T')[0]); // Reset date
        $('#expenseQuantity').val(1); // Reset quantity to default of 1
        // Reset modal title and button
        $('#addExpenseModal .modal-title').html('<i class="fas fa-plus-circle me-2"></i>Add New Expense');
        $('#saveExpenseBtn').text('Save Expense').removeData('edit-id');
    });

    // --- Helper Functions (Keep consistent with other JS files) ---
    function showAlert(message, type) {
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>`;
        // Prepend to avoid messing with table layout if inside container
        $('#alertArea').html(alertHtml);
        // Auto dismiss after 5 seconds
        setTimeout(function() {
            $('.alert').alert('close');
        }, 5000);
    }

    function formatDate(dateString) {
        if (!dateString) return '';
        try {
            // Assuming dateString is YYYY-MM-DD from API
            const date = new Date(dateString + 'T00:00:00'); // Ensure correct date parsing
            return date.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
        } catch (e) {
            return dateString; // Fallback
        }
    }

    function formatCurrency(amount) {
        const formatter = new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
        try {
            return formatter.format(amount);
        } catch (e) {
            // Fallback for invalid amount
             const num = parseFloat(amount);
             return isNaN(num) ? '₹0.00' : '₹' + num.toFixed(2);
        }
    }
});