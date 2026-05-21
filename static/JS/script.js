// script.js - Dashboard Functionality

let attendanceChart, paymentChart;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', async () => {
    console.log('Dashboard loaded, fetching data...');
    await loadDashboardData();
    initializeCharts();
    
    // Refresh button
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadDashboardData();
            updateCharts();
            showNotification('Dashboard refreshed', 'success');
        });
    }
    
    // Auto refresh every 30 seconds
    setInterval(loadDashboardData, 30000);
});

async function loadDashboardData() {
    try {
        console.log('Fetching stats...');
        const stats = await apiCall(API_ENDPOINTS.STATS);
        console.log('Stats received:', stats);
        
        // Update stats
        const totalEmployeesEl = document.getElementById('totalEmployees');
        const attendedTodayEl = document.getElementById('attendedToday');
        const paidTodayEl = document.getElementById('paidToday');
        const attendancePercentageEl = document.getElementById('attendancePercentage');
        
        if (totalEmployeesEl) totalEmployeesEl.textContent = stats.total_employees || 0;
        if (attendedTodayEl) attendedTodayEl.textContent = stats.attended_today || 0;
        if (paidTodayEl) paidTodayEl.textContent = stats.paid_today || 0;
        if (attendancePercentageEl) attendancePercentageEl.textContent = `${stats.attendance_percentage || 0}%`;
        
        // Load recent activity
        await loadRecentActivity();
        
        // Update charts
        updateCharts();
        
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showNotification('Failed to load dashboard data: ' + error.message, 'error');
    }
}

async function loadRecentActivity() {
    try {
        console.log('Fetching employees for activity...');
        const employees = await apiCall(API_ENDPOINTS.GET_EMPLOYEES);
        const activityList = document.getElementById('recentActivity');
        
        if (!employees.employees || employees.employees.length === 0) {
            activityList.innerHTML = '<div class="loading">No recent activity</div>';
            return;
        }
        
        // Get recent attendance records
        let activities = [];
        
        for (const emp of employees.employees) {
            const attendance = emp.details.attendance || [];
            const lastAttendance = attendance[attendance.length - 1];
            
            if (lastAttendance) {
                activities.push({
                    type: 'attendance',
                    name: emp.details.name,
                    time: lastAttendance.timestamp,
                    details: 'Marked attendance'
                });
            }
        }
        
        // Sort by time (most recent first)
        activities.sort((a, b) => new Date(b.time) - new Date(a.time));
        activities = activities.slice(0, 5);
        
        if (activities.length === 0) {
            activityList.innerHTML = '<div class="loading">No recent activity</div>';
            return;
        }
        
        activityList.innerHTML = activities.map(activity => `
            <div class="activity-item">
                <div class="activity-icon ${activity.type}">
                    <i class="fas ${activity.type === 'attendance' ? 'fa-fingerprint' : 'fa-money-bill-wave'}"></i>
                </div>
                <div class="activity-details">
                    <strong>${escapeHtml(activity.name)}</strong>
                    <small>${activity.details}</small>
                </div>
                <small>${formatDateTime(new Date(activity.time))}</small>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Error loading activity:', error);
    }
}

function initializeCharts() {
    const ctx1 = document.getElementById('attendanceChart')?.getContext('2d');
    const ctx2 = document.getElementById('paymentChart')?.getContext('2d');
    
    if (ctx1) {
        attendanceChart = new Chart(ctx1, {
            type: 'doughnut',
            data: {
                labels: ['Attended', 'Absent'],
                datasets: [{
                    data: [0, 0],
                    backgroundColor: ['#10b981', '#ef4444'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
    
    if (ctx2) {
        paymentChart = new Chart(ctx2, {
            type: 'bar',
            data: {
                labels: ['Paid', 'Pending'],
                datasets: [{
                    data: [0, 0],
                    backgroundColor: ['#f59e0b', '#6b7280'],
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
}

async function updateCharts() {
    try {
        const stats = await apiCall(API_ENDPOINTS.STATS);
        const total = stats.total_employees || 0;
        const attended = stats.attended_today || 0;
        const paid = stats.paid_today || 0;
        
        if (attendanceChart) {
            attendanceChart.data.datasets[0].data = [attended, total - attended];
            attendanceChart.update();
        }
        
        if (paymentChart) {
            paymentChart.data.datasets[0].data = [paid, attended - paid];
            paymentChart.update();
        }
        
    } catch (error) {
        console.error('Error updating charts:', error);
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}