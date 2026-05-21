// employees.js - Employee Management

let allEmployees = [];
let currentFilter = 'all';

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Employees page loaded');
    await loadEmployees();
    setupEventListeners();
});

async function loadEmployees() {
    try {
        console.log('Loading employees...');
        const result = await apiCall(API_ENDPOINTS.GET_EMPLOYEES);
        allEmployees = result.employees || [];
        console.log('Employees loaded:', allEmployees.length);
        renderEmployees();
        
        // Update bulk actions visibility
        updateBulkActions();
        
    } catch (error) {
        console.error('Error loading employees:', error);
        showNotification('Failed to load employees', 'error');
        document.getElementById('employeesTable').innerHTML = '<div class="loading">Error loading employees</div>';
    }
}

function renderEmployees() {
    const tableBody = document.getElementById('employeesTable');
    let filteredEmployees = filterEmployees();
    
    if (filteredEmployees.length === 0) {
        tableBody.innerHTML = '<div class="loading">No employees found</div>';
        return;
    }
    
    tableBody.innerHTML = filteredEmployees.map(emp => {
        const employeeId = emp.id;
        const details = emp.details || {};
        
        return `
            <div class="table-row" data-employee-id="${employeeId}">
                <div class="col-checkbox">
                    <input type="checkbox" class="employee-checkbox" data-id="${employeeId}">
                </div>
                <div class="col-name">
                    <strong>${escapeHtml(details.name || 'N/A')}</strong>
                </div>
                <div class="col-phone">${escapeHtml(details.phone || 'N/A')}</div>
                <div class="col-rfid">${escapeHtml(details.rfid || 'N/A')}</div>
                <div class="col-status">
                    <span class="status-badge ${details.attended ? 'attended' : 'absent'}">
                        ${details.attended ? 'Attended' : 'Absent'}
                    </span>
                </div>
                <div class="col-payment">
                    <span class="payment-badge ${details.paid ? 'paid' : 'pending'}">
                        ${details.paid ? 'Paid' : 'Pending'}
                    </span>
                </div>
                <div class="col-actions">
                    <div class="action-buttons">
                        <button class="action-btn edit" onclick="editEmployee('${employeeId}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="action-btn delete" onclick="deleteEmployee('${employeeId}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    // Add event listeners to checkboxes
    document.querySelectorAll('.employee-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', updateBulkActions);
    });
    
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', (e) => {
            document.querySelectorAll('.employee-checkbox').forEach(cb => {
                cb.checked = e.target.checked;
            });
            updateBulkActions();
        });
    }
}

function filterEmployees() {
    let filtered = [...allEmployees];
    
    // Apply search filter
    const searchTerm = document.getElementById('searchInput')?.value.toLowerCase() || '';
    if (searchTerm) {
        filtered = filtered.filter(emp => {
            const details = emp.details || {};
            return (details.name || '').toLowerCase().includes(searchTerm) ||
                   (details.phone || '').includes(searchTerm) ||
                   (details.rfid || '').toLowerCase().includes(searchTerm);
        });
    }
    
    // Apply status filter
    switch(currentFilter) {
        case 'attended':
            filtered = filtered.filter(emp => emp.details && emp.details.attended);
            break;
        case 'paid':
            filtered = filtered.filter(emp => emp.details && emp.details.paid);
            break;
        case 'pending':
            filtered = filtered.filter(emp => emp.details && !emp.details.paid && emp.details.attended);
            break;
    }
    
    return filtered;
}

function setupEventListeners() {
    // Search input
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', () => renderEmployees());
    }
    
    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            renderEmployees();
        });
    });
    
    // Refresh button
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadEmployees();
            showNotification('Employees refreshed', 'success');
        });
    }
}

function updateBulkActions() {
    const selected = document.querySelectorAll('.employee-checkbox:checked').length;
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');
    
    if (selected > 0 && bulkActions) {
        bulkActions.style.display = 'flex';
        if (selectedCount) selectedCount.textContent = selected;
    } else if (bulkActions) {
        bulkActions.style.display = 'none';
    }
}

async function editEmployee(employeeId) {
    try {
        const result = await apiCall(API_ENDPOINTS.GET_EMPLOYEE(employeeId));
        const employee = result.employee;
        const details = employee.details || {};
        
        document.getElementById('editEmployeeId').value = employeeId;
        document.getElementById('editName').value = details.name || '';
        document.getElementById('editPhone').value = details.phone || '';
        document.getElementById('editRfid').value = details.rfid || '';
        
        const modal = document.getElementById('editModal');
        if (modal) modal.style.display = 'block';
        
    } catch (error) {
        console.error('Error loading employee:', error);
        showNotification('Failed to load employee data', 'error');
    }
}

async function deleteEmployee(employeeId) {
    if (!confirm('Are you sure you want to delete this employee? This action cannot be undone.')) {
        return;
    }
    
    try {
        await apiCall(API_ENDPOINTS.DELETE_EMPLOYEE(employeeId), 'DELETE');
        showNotification('Employee deleted successfully', 'success');
        await loadEmployees();
        
    } catch (error) {
        console.error('Error deleting employee:', error);
        showNotification('Failed to delete employee', 'error');
    }
}

async function bulkDelete() {
    const selected = document.querySelectorAll('.employee-checkbox:checked');
    if (selected.length === 0) return;
    
    if (!confirm(`Are you sure you want to delete ${selected.length} employee(s)? This action cannot be undone.`)) {
        return;
    }
    
    let successCount = 0;
    let errorCount = 0;
    
    for (const checkbox of selected) {
        const employeeId = checkbox.dataset.id;
        try {
            await apiCall(API_ENDPOINTS.DELETE_EMPLOYEE(employeeId), 'DELETE');
            successCount++;
        } catch (error) {
            errorCount++;
        }
    }
    
    showNotification(`Deleted ${successCount} employees${errorCount > 0 ? ` (${errorCount} failed)` : ''}`, 'success');
    await loadEmployees();
}

// Edit form submission
const editForm = document.getElementById('editForm');
if (editForm) {
    editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const employeeId = document.getElementById('editEmployeeId').value;
        const data = {
            name: document.getElementById('editName').value,
            phone: document.getElementById('editPhone').value,
            rfid: document.getElementById('editRfid').value
        };
        
        try {
            await apiCall(API_ENDPOINTS.UPDATE_EMPLOYEE(employeeId), 'PUT', data);
            showNotification('Employee updated successfully', 'success');
            closeModal();
            await loadEmployees();
            
        } catch (error) {
            console.error('Error updating employee:', error);
            showNotification('Failed to update employee', 'error');
        }
    });
}

function closeModal() {
    const modal = document.getElementById('editModal');
    if (modal) modal.style.display = 'none';
}

// Close modal when clicking on X or outside
window.onclick = function(event) {
    const modal = document.getElementById('editModal');
    if (event.target === modal) {
        closeModal();
    }
}