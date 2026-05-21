// attendance.js - Attendance Management

let currentAttendanceData = [];

document.addEventListener('DOMContentLoaded', async () => {
    // Set default date to today
    const dateInput = document.getElementById('attendanceDate');
    if (dateInput) {
        dateInput.value = formatDate();
        dateInput.addEventListener('change', loadAttendanceData);
    }
    
    // Setup RFID input
    const rfidInput = document.getElementById('rfidInput');
    if (rfidInput) {
        rfidInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
                await markAttendance();
            }
        });
        rfidInput.focus();
    }
    
    await loadAttendanceData();
    await loadSummary();
    
    // Refresh button
    document.getElementById('refreshBtn')?.addEventListener('click', async () => {
        await loadAttendanceData();
        await loadSummary();
        showNotification('Attendance data refreshed', 'success');
    });
    
    // Auto refresh every 10 seconds
    setInterval(async () => {
        await loadSummary();
    }, 10000);
});

async function markAttendance() {
    const rfidInput = document.getElementById('rfidInput');
    const rfid = rfidInput.value.trim();
    
    if (!rfid) {
        showAttendanceMessage('Please enter or tap RFID card', 'error');
        return;
    }
    
    const messageDiv = document.getElementById('attendanceMessage');
    messageDiv.style.display = 'none';
    
    try {
        const result = await apiCall(API_ENDPOINTS.MARK_ATTENDANCE, 'POST', { rfid });
        
        if (result.success) {
            if (result.already_marked) {
                showAttendanceMessage(result.message, 'info');
            } else {
                showAttendanceMessage(result.message, 'success');
                await loadAttendanceData();
                await loadSummary();
            }
            rfidInput.value = '';
            rfidInput.focus();
        } else {
            showAttendanceMessage(result.message || 'Failed to mark attendance', 'error');
        }
        
    } catch (error) {
        console.error('Error marking attendance:', error);
        showAttendanceMessage('Failed to mark attendance. Please try again.', 'error');
    }
}

async function loadAttendanceData() {
    const date = document.getElementById('attendanceDate').value;
    const tableBody = document.getElementById('attendanceTable');
    
    if (!date) return;
    
    try {
        const result = await apiCall(`${API_ENDPOINTS.GET_ATTENDANCE}?date=${date}`);
        currentAttendanceData = result.attendance || [];
        
        if (currentAttendanceData.length === 0) {
            tableBody.innerHTML = '<div class="loading">No attendance records for this date</div>';
            return;
        }
        
        // Fetch employee details for each attendance record
        const employees = await apiCall(API_ENDPOINTS.GET_EMPLOYEES);
        const employeeMap = new Map();
        employees.employees?.forEach(emp => {
            employeeMap.set(emp.id, emp.details);
        });
        
        tableBody.innerHTML = currentAttendanceData.map(record => {
            const employee = employeeMap.get(record.employee_id);
            return `
                <div class="table-row">
                    <div class="col-name">
                        <strong>${escapeHtml(record.name || employee?.name || 'N/A')}</strong>
                    </div>
                    <div class="col-phone">${escapeHtml(employee?.phone || 'N/A')}</div>
                    <div class="col-time">${formatDateTime(new Date(record.timestamp))}</div>
                    <div class="col-status">
                        <span class="status-badge attended">Present</span>
                    </div>
                    <div class="col-payment-status">
                        <span class="payment-badge ${employee?.paid ? 'paid' : 'pending'}">
                            ${employee?.paid ? 'Paid' : 'Pending'}
                        </span>
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading attendance:', error);
        tableBody.innerHTML = '<div class="loading">Error loading attendance data</div>';
    }
}

async function loadSummary() {
    try {
        const stats = await apiCall(API_ENDPOINTS.STATS);
        
        document.getElementById('todayAttended').textContent = stats.attended_today || 0;
        document.getElementById('todayPaid').textContent = stats.paid_today || 0;
        
        const pending = (stats.attended_today || 0) - (stats.paid_today || 0);
        document.getElementById('pendingPayment').textContent = pending;
        
    } catch (error) {
        console.error('Error loading summary:', error);
    }
}

function showAttendanceMessage(message, type) {
    const messageDiv = document.getElementById('attendanceMessage');
    messageDiv.textContent = message;
    messageDiv.className = `attendance-message ${type}`;
    messageDiv.style.display = 'block';
    
    setTimeout(() => {
        messageDiv.style.display = 'none';
    }, 3000);
}

function exportAttendance() {
    if (currentAttendanceData.length === 0) {
        showNotification('No data to export', 'error');
        return;
    }
    
    // Prepare CSV data
    const headers = ['Employee Name', 'Phone', 'Attendance Time', 'Status'];
    const rows = currentAttendanceData.map(record => [
        record.name,
        record.employee_id, // You might want to fetch phone numbers here
        record.timestamp,
        'Present'
    ]);
    
    const csvContent = [headers, ...rows].map(row => row.join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `attendance_${document.getElementById('attendanceDate').value}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    
    showNotification('Report exported successfully', 'success');
}

function printReport() {
    const date = document.getElementById('attendanceDate').value;
    const printWindow = window.open('', '_blank');
    
    printWindow.document.write(`
        <html>
        <head>
            <title>Attendance Report - ${date}</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
                th { background-color: #f5f5f5; }
                .header { text-align: center; margin-bottom: 30px; }
                .footer { margin-top: 30px; text-align: center; font-size: 12px; color: #666; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Attendance Report</h1>
                <p>Date: ${date}</p>
                <p>Generated: ${formatDateTime()}</p>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Employee Name</th>
                        <th>Attendance Time</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${currentAttendanceData.map(record => `
                        <tr>
                            <td>${escapeHtml(record.name)}</td>
                            <td>${formatDateTime(new Date(record.timestamp))}</td>
                            <td>Present</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            <div class="footer">
                <p>Total Present: ${currentAttendanceData.length}</p>
            </div>
        </body>
        </html>
    `);
    
    printWindow.document.close();
    printWindow.print();
}