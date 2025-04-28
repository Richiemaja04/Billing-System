// static/js/main.js
$(document).ready(function() {
    // DataTable Initialization
    const billsTable = $('#billsTable').DataTable({
        responsive: true,
        order: [[0, 'desc']],
        ajax: { url: '/api/bills', dataSrc: '' },
        columns: [
            { data: 'serial_number', width: '100px' },
            { data: 'customer_name' },
            { data: 'mobile_number' },
            { data: 'product_size' },
            { data: 'thickness' }, // Added thickness column
            { data: 'order_date', render: formatDate },
            { data: 'delivery_date', render: formatDate },
            { data: 'current_status', render: formatStatusBadge },
            { data: 'quantity' }, // Added quantity column
            { data: 'total_price', render: formatCurrency, className: 'text-end' },
            { data: 'advance_amount', render: formatCurrency, className: 'text-end' },
            { data: 'amount_due', render: formatCurrency, className: 'text-end' },
            { data: 'payment_status', render: formatPaymentStatusBadge },
            { data: 'id', orderable: false, className: 'text-center', render: function(data, type, row) {
                    return `<button class="btn btn-sm btn-warning edit-btn" data-id="${data}" data-row='${JSON.stringify(row)}' data-bs-toggle="tooltip" title="Edit"><i class="fas fa-edit"></i></button> <button class="btn btn-sm btn-danger delete-btn" data-id="${data}" data-bs-toggle="tooltip" title="Delete"><i class="fas fa-trash"></i></button>`;
                }
            }
        ],
        drawCallback: function() { $('[data-bs-toggle="tooltip"]').tooltip(); },
        language: { search: "_INPUT_", searchPlaceholder: "Search bills..." },
        lengthMenu: [[10, 25, 50, -1], [10, 25, 50, "All"]]
    });

    loadPaymentModes();

    // Set today's date for order date fields by default
    const today = new Date().toISOString().split('T')[0];
    $('#orderDate').val(today);
    $('#editOrderDate').val(today);

    // Event Listeners
    // Amount calculations
    $('#totalPrice, #advanceAmount, #quantity').on('input', function() { 
        calculateDueAmount('#totalPrice', '#advanceAmount', '#amountDue', '#quantity'); 
    });
    
    $('#editTotalPrice, #editAdvanceAmount, #editQuantity').on('input', function() { 
        calculateDueAmount('#editTotalPrice', '#editAdvanceAmount', '#editAmountDue', '#editQuantity'); 
    });
    
    // Form submissions
    $('#saveBillBtn').click(saveBill);
    $('#updateBillBtn').click(updateBill);
    $('#confirmDeleteBtn').click(deleteBillConfirmed);
    
    // Search and export
    $('#searchButton').click(searchBills);
    $('#searchInput').keypress(function(e) { if (e.which === 13) searchBills(); });
    $('#exportExcelBtn').click(exportToExcel);
    
    // Shutdown app
    $('#shutdownAppBtn').click(function() {
        showShutdownModal();
    });
    
    $('#confirmShutdownBtn').click(shutdownApplicationConfirmed);
    
    // Table row actions
    $('#billsTable tbody').on('click', '.edit-btn', function() { 
        try { 
            const rowData = $(this).attr('data-row');
            console.log("Row data:", rowData);
            const billId = $(this).data('id');
            const parsedData = JSON.parse(rowData);
            editBill(billId, parsedData); 
        } catch (e) { 
            console.error("Error in edit button click:", e);
            showAlert("Error loading bill data: " + e.message, "danger"); 
        }
    });
    
    $('#billsTable tbody').on('click', '.delete-btn', function() { 
        showDeleteBillModal($(this).data('id')); 
    });
    
    // Modal cleanup
    $('#addBillModal').on('hidden.bs.modal', function () { 
        clearBillForm('#addBillForm', '#orderDate', '#amountDue'); 
    });

    // --- Functions ---

    function loadPaymentModes() {
         $.ajax({
            url: '/api/payment-modes', 
            type: 'GET',
            success: function(modes) {
                const $addAdvance = $('#advancePaymentMode');
                const $editAdvance = $('#editAdvancePaymentMode');
                const $editDue = $('#amountDuePaymentMode');
                
                // Clear existing options except placeholder if it exists
                $addAdvance.find('option:not([value=""])').remove();
                $editAdvance.find('option:not([value=""])').remove();
                $editDue.find('option:not([value=""])').remove();

                modes.forEach(function(mode) {
                    $addAdvance.append(`<option value="${mode}">${mode}</option>`);
                    $editAdvance.append(`<option value="${mode}">${mode}</option>`);
                    $editDue.append(`<option value="${mode}">${mode}</option>`);
                });
            }, 
            error: function() { 
                showAlert("Could not load payment mode options.", "warning"); 
            }
        });
    }

    function calculateDueAmount(totalSelector, advanceSelector, dueSelector, quantitySelector) {
        const totalPrice = parseFloat($(totalSelector).val()) || 0;
        const advanceAmount = parseFloat($(advanceSelector).val()) || 0;
        const quantity = parseInt($(quantitySelector).val()) || 1;
        
        const dueAmount = (totalPrice * quantity) - advanceAmount;
        $(dueSelector).val(dueAmount.toFixed(2));
    }

    function saveBill() {
        const advancePaymentMode = $('#advancePaymentMode').val();
        const customerName = $('#customerName').val().trim();
        const mobileNumber = $('#mobileNumber').val().trim();
        const productSize = $('#productSize').val().trim();
        const thickness = $('#thickness').val().trim();
        const quantity = parseInt($('#quantity').val()) || 1;
        const orderDate = $('#orderDate').val();
        const deliveryDate = $('#deliveryDate').val();
        const currentStatus = $('#currentStatus').val();
        const totalPriceStr = $('#totalPrice').val();
        const advanceAmountStr = $('#advanceAmount').val();
        const paymentStatus = $('#paymentStatus').val();

        if (!customerName || !orderDate || !deliveryDate || !totalPriceStr || !advancePaymentMode || !paymentStatus || !productSize || !thickness) {
            showAlert('Please fill all required fields.', 'warning');
            return;
        }
        
        let totalPrice, advanceAmount;
        try { 
            totalPrice = parseFloat(totalPriceStr); 
            advanceAmount = parseFloat(advanceAmountStr || '0'); 
            if (isNaN(totalPrice) || isNaN(advanceAmount)) throw new Error(); 
        }
        catch (e) { 
            showAlert('Invalid number format for prices.', 'warning'); 
            return; 
        }

        // Check if Amount Due Payment Mode is required when status is PAID
        if (paymentStatus === 'PAID' && totalPrice - advanceAmount > 0) {
            const amountDuePaymentMode = $('#amountDuePaymentMode').val();
            if (!amountDuePaymentMode) {
                showAlert('Please select the Payment Mode for the Amount Due when status is PAID.', 'warning');
                return;
            }
        }

        const billData = {
            customer_name: customerName, 
            mobile_number: mobileNumber, 
            product_size: productSize,
            thickness: thickness,
            quantity: quantity,
            order_date: orderDate, 
            delivery_date: deliveryDate, 
            current_status: currentStatus,
            total_price: totalPrice, 
            advance_payment_mode: advancePaymentMode,
            advance_amount: advanceAmount, 
            payment_status: paymentStatus,
            amount_due_payment_mode: paymentStatus === 'PAID' ? $('#amountDuePaymentMode').val() : null
        };

        $.ajax({
            url: '/api/bills', 
            type: 'POST', 
            contentType: 'application/json', 
            data: JSON.stringify(billData),
            success: function(response) {
                if (response.success) { 
                    $('#addBillModal').modal('hide'); 
                    showAlert(response.message || 'Bill saved!', 'success'); 
                    billsTable.ajax.reload(); 
                }
                else { 
                    showAlert(response.message || 'Error saving bill.', 'danger'); 
                }
            },
            error: function(xhr) { 
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'API error saving bill.'; 
                showAlert(errorMsg, 'danger'); 
            }
        });
    }

    function editBill(billId, billData) { 
        console.log("Editing bill:", billId, billData);
        
        $('#editBillId').val(billData.id); 
        $('#editSerialNumber').val(billData.serial_number); 
        $('#editCustomerName').val(billData.customer_name); 
        $('#editMobileNumber').val(billData.mobile_number); 
        $('#editProductSize').val(billData.product_size);
        $('#editThickness').val(billData.thickness);
        $('#editQuantity').val(billData.quantity || 1);
        $('#editOrderDate').val(billData.order_date); 
        $('#editDeliveryDate').val(billData.delivery_date); 
        $('#editCurrentStatus').val(billData.current_status); 
        $('#editTotalPrice').val(billData.total_price);
        $('#editAdvancePaymentMode').val(billData.advance_payment_mode);
        $('#editAdvanceAmount').val(billData.advance_amount);
        $('#editPaymentStatus').val(billData.payment_status);
        $('#amountDuePaymentMode').val(billData.amount_due_payment_mode || '');
        
        // Manually update the select options for product size and thickness based on current values
        updateSelectBasedOnValue('#editProductSizeSelect', '#editProductSize', billData.product_size);
        updateSelectBasedOnValue('#editThicknessSelect', '#editThickness', billData.thickness);
        
        // Calculate due amount
        calculateDueAmount('#editTotalPrice', '#editAdvanceAmount', '#editAmountDue', '#editQuantity');
        
        // Show the modal
        $('#editBillModal').modal('show');
    }

    function updateSelectBasedOnValue(selectId, inputId, value) {
        const $select = $(selectId);
        
        // First try to find a matching option
        let found = false;
        $select.find('option').each(function() {
            if ($(this).val() !== '' && $(this).val() !== 'custom' && $(this).val() === value) {
                $select.val(value);
                found = true;
                return false; // break the loop
            }
        });
        
        // If not found, set to custom
        if (!found && value) {
            $select.val('custom');
        }
    }

    function updateBill() {
        console.log("Update button clicked");
        
        const billId = $('#editBillId').val();
        if (!billId) { 
            showAlert("Cannot update: ID missing.", "danger"); 
            return; 
        }

        const advancePaymentMode = $('#editAdvancePaymentMode').val();
        const amountDuePaymentMode = $('#amountDuePaymentMode').val();
        const serialNumber = $('#editSerialNumber').val();
        const customerName = $('#editCustomerName').val().trim();
        const mobileNumber = $('#editMobileNumber').val().trim();
        const productSize = $('#editProductSize').val().trim();
        const thickness = $('#editThickness').val().trim();
        const quantity = parseInt($('#editQuantity').val()) || 1;
        const orderDate = $('#editOrderDate').val();
        const deliveryDate = $('#editDeliveryDate').val();
        const currentStatus = $('#editCurrentStatus').val();
        const totalPriceStr = $('#editTotalPrice').val();
        const advanceAmountStr = $('#editAdvanceAmount').val();
        const paymentStatus = $('#editPaymentStatus').val();

        console.log("Form values:", {
            billId, serialNumber, customerName, mobileNumber, productSize, thickness, quantity,
            orderDate, deliveryDate, currentStatus, totalPriceStr, 
            advancePaymentMode, advanceAmountStr, paymentStatus, amountDuePaymentMode
        });

        if (!customerName || !orderDate || !deliveryDate || !totalPriceStr || !advancePaymentMode || !paymentStatus || !serialNumber || !productSize || !thickness) {
            showAlert('Please fill all required fields.', 'warning'); 
            return;
        }
        
        let totalPrice, advanceAmount;
        try { 
            totalPrice = parseFloat(totalPriceStr); 
            advanceAmount = parseFloat(advanceAmountStr || '0'); 
            if (isNaN(totalPrice) || isNaN(advanceAmount)) throw new Error(); 
        }
        catch (e) { 
            showAlert('Invalid number format for prices.', 'warning'); 
            return; 
        }

        // Check if Amount Due Payment Mode is required
        const amountDue = (totalPrice * quantity) - advanceAmount;
        if (paymentStatus === 'PAID' && amountDue > 0 && !amountDuePaymentMode) {
            showAlert('Please select the Payment Mode for the Amount Due when status is PAID.', 'warning');
            return;
        }

        const billData = {
            id: billId, 
            serial_number: serialNumber, 
            customer_name: customerName, 
            mobile_number: mobileNumber, 
            product_size: productSize,
            thickness: thickness,
            quantity: quantity,
            order_date: orderDate, 
            delivery_date: deliveryDate, 
            current_status: currentStatus, 
            total_price: totalPrice,
            advance_payment_mode: advancePaymentMode,
            advance_amount: advanceAmount, 
            payment_status: paymentStatus,
            amount_due_payment_mode: paymentStatus === 'PAID' ? amountDuePaymentMode : null
        };

        console.log("Sending data:", billData);

        $.ajax({
            url: `/api/bills/${billId}`, 
            type: 'PUT', 
            contentType: 'application/json', 
            data: JSON.stringify(billData),
            success: function(response) {
                console.log("Update response:", response);
                if (response.success) { 
                    $('#editBillModal').modal('hide'); 
                    showAlert('Bill updated!', 'success'); 
                    billsTable.ajax.reload(); 
                }
                else { 
                    showAlert(response.message || 'Error updating bill.', 'danger'); 
                }
            },
            error: function(xhr) { 
                console.error("Update error:", xhr);
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'API error updating bill.'; 
                showAlert(errorMsg, 'danger'); 
            }
        });
    }

    function showDeleteBillModal(billId) {
        $('#deleteBillId').val(billId);
        $('#confirmDeleteModal').modal('show');
    }

    function deleteBillConfirmed() {
        const billId = $('#deleteBillId').val();
        if (!billId) return;

        $.ajax({
            url: `/api/bills/${billId}`,
            type: 'DELETE',
            success: function(response) {
                $('#confirmDeleteModal').modal('hide');
                if (response.success) {
                    showAlert('Bill deleted successfully!', 'success');
                    billsTable.ajax.reload();
                } else {
                    showAlert(response.message || 'Error deleting bill.', 'danger');
                }
            },
            error: function(xhr) {
                $('#confirmDeleteModal').modal('hide');
                const errorMsg = xhr.responseJSON ? xhr.responseJSON.message : 'An error occurred deleting the bill.';
                showAlert(errorMsg, 'danger');
            }
        });
    }

    function showShutdownModal() {
        $('#confirmShutdownModal').modal('show');
    }

    function shutdownApplicationConfirmed() {
        $.ajax({
            url: '/shutdown',
            type: 'POST',
            success: function() {
                $('#confirmShutdownModal').modal('hide');
                showAlert('Application shutting down...', 'info');
                setTimeout(function() {
                    window.close();
                }, 2000);
            },
            error: function() {
                $('#confirmShutdownModal').modal('hide');
                showAlert('You can now close the application.', 'danger');
                window.close();
            }
        });
    }

    function searchBills() {
        const searchTerm = $('#searchInput').val().trim();
        billsTable.ajax.url('/api/bills/search?term=' + encodeURIComponent(searchTerm)).load();
    }

    function exportToExcel() {
        window.location.href = '/api/bills/export';
    }

    function clearBillForm(formSelector, dateSelector, dueSelector) {
        $(formSelector)[0].reset();
        const today = new Date().toISOString().split('T')[0];
        $(dateSelector).val(today);
        $(dueSelector).val('');
        
        // Reset quantity to 1
        $(formSelector).find('input#quantity').val('1');
        
        // Reset dropdowns
        $(formSelector).find('select#productSizeSelect').val('');
        $(formSelector).find('select#thicknessSelect').val('');
        $(formSelector).find('input#productSize').val('');
        $(formSelector).find('input#thickness').val('');
    }

    // --- Helper Functions ---
    function showAlert(message, type) {
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>`;
        $('#alertArea').html(alertHtml);
        setTimeout(function() { $('.alert').alert('close'); }, 5000);
    }

    function formatDate(dateString) {
        if (!dateString) return '';
        try {
            const date = new Date(dateString + 'T00:00:00');
            return date.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
        } catch (e) { return dateString; }
    }

    function formatCurrency(amount) {
        const num = parseFloat(amount);
        if (isNaN(num)) return '₹0.00';
        const formatter = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return formatter.format(num);
    }

    function formatStatusBadge(status) {
        if (!status) return '';
        const statusClass = 'status-' + status.toLowerCase().replace(/\s+/g, '-');
        return `<span class="status-badge ${statusClass}">${status}</span>`;
    }

    function formatPaymentStatusBadge(status) {
        if (!status) return '';
        const statusClass = status === 'PAID' ? 'payment-paid' : 'payment-not-paid';
        return `<span class="${statusClass}">${status}</span>`;
    }
});