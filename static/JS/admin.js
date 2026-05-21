// admin.js - Admin Settings Management

let currentSettings = {};
let pendingAction = null;

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Admin page loaded');
    await loadSettings();
    setupEventListeners();
    startCountdownTimer();
});

async function loadSettings() {
    try {
        console.log('Loading system settings...');
        const settings = await apiCall('/admin/settings');
        currentSettings = settings;
        
        // Update payment settings form
        if (settings.paymentTime) {
            document.getElementById('paymentTime').value = settings.paymentTime;
            const currentPaymentTime = document.getElementById('currentPaymentTime');
            if (currentPaymentTime) {
                currentPaymentTime.innerHTML = `<small>Current: ${settings.paymentTime}</small>`;
            }
        }
        
        if (settings.payAmount) {
            document.getElementById('payAmount').value = settings.payAmount;
            const currentPayAmount = document.getElementById('currentPayAmount');
            if (currentPayAmount) {
                currentPayAmount.innerHTML = `<small>Current: ${settings.payAmount} RWF</small>`;
            }
        }
        
        if (settings.shiftExpirelyTime) {
            document.getElementById('shiftExpireTime').value = settings.shiftExpirelyTime;
            const currentShiftExpireTime = document.getElementById('currentShiftExpireTime');
            if (currentShiftExpireTime) {
                currentShiftExpireTime.innerHTML = `<small>Current: ${settings.shiftExpirelyTime}</small>`;
            }
            // Also update attendance reset time field if it exists
            const attendanceResetTime = document.getElementById('attendanceResetTime');
            if (attendanceResetTime) {
                attendanceResetTime.value = settings.shiftExpirelyTime;
            }
            const currentAttendanceResetTime = document.getElementById('currentAttendanceResetTime');
            if (currentAttendanceResetTime) {
                currentAttendanceResetTime.innerHTML = `<small>Current: ${settings.shiftExpirelyTime}</small>`;
            }
        }
        
        // Update statistics
        updatePaymentStats();
        
    } catch (error) {
        console.error('Error loading settings:', error);
        showNotification('Failed to load settings', 'error');
    }
}

async function updatePaymentSettings() {
    const paymentTime = document.getElementById('paymentTime').value;
    const payAmount = document.getElementById('payAmount').value;
    const shiftExpireTime = document.getElementById('shiftExpireTime').value;
    
    if (!paymentTime || !payAmount || !shiftExpireTime) {
        showNotification('Please fill all fields', 'error');
        return false;
    }
    
    try {
        const result = await apiCall('/admin/settings/payment', 'POST', {
            paymentTime: paymentTime,
            payAmount: parseInt(payAmount),
            shiftExpireTime: shiftExpireTime
        });
        
        if (result.success) {
            showNotification('Payment settings updated successfully', 'success');
            await loadSettings(); // Reload settings
            return true;
        }
        
    } catch (error) {
        console.error('Error updating payment settings:', error);
        showNotification('Failed to update settings: ' + error.message, 'error');
        return false;
    }
}

async function updateAttendanceSettings() {
    const resetTime = document.getElementById('attendanceResetTime').value;
    
    if (!resetTime) {
        showNotification('Please select reset time', 'error');
        return false;
    }
    
    try {
        // Use the same payment settings endpoint since shiftExpirelyTime is the same setting
        const result = await apiCall('/admin/settings/payment', 'POST', {
            shiftExpireTime: resetTime
        });
        
        if (result.success) {
            showNotification('Attendance settings updated successfully', 'success');
            await loadSettings();
            return true;
        }
        
    } catch (error) {
        console.error('Error updating attendance settings:', error);
        showNotification('Failed to update settings: ' + error.message, 'error');
        return false;
    }
}

async function updateSystemSettings() {
    const username = document.getElementById('adminUsername').value;
    const password = document.getElementById('adminPassword').value;
    
    if (!username && !password) {
        showNotification('Please enter at least one field to update', 'error');
        return false;
    }
    
    const data = {};
    if (username) data.username = username;
    if (password) data.password = password;
    
    try {
        const result = await apiCall('/admin/settings/system', 'POST', data);
        
        if (result.success) {
            showNotification('System settings updated successfully', 'success');
            document.getElementById('adminUsername').value = '';
            document.getElementById('adminPassword').value = '';
            return true;
        }
        
    } catch (error) {
        console.error('Error updating system settings:', error);
        showNotification('Failed to update settings: ' + error.message, 'error');
        return false;
    }
}

function resetPaymentSettings() {
    showConfirmModal('Reset all payment settings to default values?', async () => {
        try {
            const result = await apiCall('/admin/settings/reset', 'POST');
            if (result.success) {
                showNotification('Settings reset to default', 'success');
                await loadSettings();
            }
        } catch (error) {
            console.error('Error resetting settings:', error);
            showNotification('Failed to reset settings: ' + error.message, 'error');
        }
    });
}

async function backupDatabase() {
    showConfirmModal('Download database backup?', async () => {
        try {
            window.location.href = '/admin/backup';
            showNotification('Backup download started', 'success');
        } catch (error) {
            console.error('Error backing up database:', error);
            showNotification('Failed to backup database', 'error');
        }
    });
}

async function clearAllData() {
    showConfirmModal('WARNING: This will delete ALL employee data! This action cannot be undone. Are you absolutely sure?', async () => {
        try {
            const result = await apiCall('/admin/clear-data', 'POST', { confirm: true });
            if (result.success) {
                showNotification('All data has been cleared', 'success');
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            }
        } catch (error) {
            console.error('Error clearing data:', error);
            showNotification('Failed to clear data: ' + error.message, 'error');
        }
    });
}

async function loadSystemLogs() {
    try {
        const logs = await apiCall('/admin/logs');
        const logsContainer = document.getElementById('logsContainer');
        
        if (!logsContainer) return;
        
        if (!logs || logs.length === 0) {
            logsContainer.innerHTML = '<div class="loading">No logs available</div>';
            return;
        }
        
        logsContainer.innerHTML = logs.map(log => `
            <div class="log-entry ${log.level.toLowerCase()}">
                <div class="log-time">${log.timestamp}</div>
                <div class="log-message">${escapeHtml(log.message)}</div>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Error loading logs:', error);
        const logsContainer = document.getElementById('logsContainer');
        if (logsContainer) {
            logsContainer.innerHTML = '<div class="loading">Error loading logs</div>';
        }
    }
}

function updatePaymentStats() {
    // Calculate expected payout
    fetch('/stats')
        .then(res => res.json())
        .then(stats => {
            const attended = stats.attended_today || 0;
            const amount = currentSettings.payAmount || 100;
            const expected = attended * amount;
            const expectedPayout = document.getElementById('expectedPayout');
            if (expectedPayout) {
                expectedPayout.textContent = `${expected.toLocaleString()} RWF`;
            }
        })
        .catch(error => console.error('Error fetching stats:', error));
    
    // Calculate next payment time
    if (currentSettings.paymentTime) {
        const nextPaymentTime = document.getElementById('nextPaymentTime');
        if (nextPaymentTime) {
            nextPaymentTime.textContent = currentSettings.paymentTime;
        }
    }
}

function startCountdownTimer() {
    setInterval(() => {
        if (currentSettings.paymentTime) {
            const now = new Date();
            const paymentTime = currentSettings.paymentTime.split(':');
            const paymentDate = new Date();
            paymentDate.setHours(parseInt(paymentTime[0]), parseInt(paymentTime[1]), 0);
            
            let diff = paymentDate - now;
            if (diff < 0) {
                paymentDate.setDate(paymentDate.getDate() + 1);
                diff = paymentDate - now;
            }
            
            const hours = Math.floor(diff / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            
            const timeUntilPayment = document.getElementById('timeUntilPayment');
            if (timeUntilPayment) {
                timeUntilPayment.textContent = `${hours}h ${minutes}m`;
            }
        }
    }, 1000);
}

function setupEventListeners() {
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            switchTab(tabId);
        });
    });
    
    // Payment settings form
    const paymentForm = document.getElementById('paymentSettingsForm');
    if (paymentForm) {
        paymentForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await updatePaymentSettings();
        });
    }
    
    // Attendance settings form
    const attendanceForm = document.getElementById('attendanceSettingsForm');
    if (attendanceForm) {
        attendanceForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await updateAttendanceSettings();
        });
    }
    
    // System settings form
    const systemForm = document.getElementById('systemSettingsForm');
    if (systemForm) {
        systemForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await updateSystemSettings();
        });
    }
    
    // Refresh button
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadSettings();
            if (document.querySelector('.tab-btn[data-tab="logs"].active')) {
                await loadSystemLogs();
            }
            showNotification('Settings refreshed', 'success');
        });
    }
}

function switchTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabId) {
            btn.classList.add('active');
        }
    });
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    const activeTab = document.getElementById(`${tabId}Tab`);
    if (activeTab) {
        activeTab.classList.add('active');
    }
    
    // Load logs if logs tab is selected
    if (tabId === 'logs') {
        loadSystemLogs();
    }
}

function showConfirmModal(message, onConfirm) {
    const modal = document.getElementById('confirmModal');
    const confirmMessage = document.getElementById('confirmMessage');
    const confirmBtn = document.getElementById('confirmActionBtn');
    
    if (!modal) return;
    
    confirmMessage.textContent = message;
    modal.style.display = 'block';
    
    // Remove previous event listener
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
    
    newConfirmBtn.addEventListener('click', () => {
        onConfirm();
        closeConfirmModal();
    });
}

function closeConfirmModal() {
    const modal = document.getElementById('confirmModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// System Settings Functions

async function loadSystemInfo() {
    try {
        // Get system info
        const response = await fetch('/admin/system-info');
        const info = await response.json();
        
        document.getElementById('pythonVersion').textContent = info.python_version || '--';
        document.getElementById('flaskVersion').textContent = info.flask_version || '--';
        document.getElementById('firebaseStatus').textContent = info.firebase_status || '--';
        document.getElementById('serverTime').textContent = info.server_time || '--';
        document.getElementById('systemUptime').textContent = info.system_uptime || '--';
        document.getElementById('environment').textContent = info.environment || '--';
        
        // Load database stats
        const stats = await apiCall('/stats');
        document.getElementById('totalRecords').textContent = stats.total_employees || 0;
        
        // Get backup info
        const backupInfo = await apiCall('/admin/backup-info');
        if (backupInfo.last_backup) {
            document.getElementById('lastBackup').textContent = backupInfo.last_backup;
        }
        
    } catch (error) {
        console.error('Error loading system info:', error);
    }
}

async function saveSessionSettings() {
    const sessionTimeout = document.getElementById('sessionTimeout').value;
    const twoFactorAuth = document.getElementById('twoFactorAuth').checked;
    const emailNotifications = document.getElementById('emailNotifications').checked;
    
    try {
        const result = await apiCall('/admin/session-settings', 'POST', {
            session_timeout: parseInt(sessionTimeout),
            two_factor_auth: twoFactorAuth,
            email_notifications: emailNotifications
        });
        
        if (result.success) {
            showNotification('Session settings saved successfully', 'success');
        }
    } catch (error) {
        console.error('Error saving session settings:', error);
        showNotification('Failed to save session settings', 'error');
    }
}

async function clearAllSessions() {
    showConfirmModal('Clear all active admin sessions? Users will need to login again.', async () => {
        try {
            const result = await apiCall('/admin/clear-sessions', 'POST');
            if (result.success) {
                showNotification('All sessions cleared', 'success');
            }
        } catch (error) {
            console.error('Error clearing sessions:', error);
            showNotification('Failed to clear sessions', 'error');
        }
    });
}

async function restoreDatabase() {
    const fileInput = document.getElementById('restoreFile');
    const file = fileInput.files[0];
    
    if (!file) {
        showNotification('Please select a backup file first', 'error');
        return;
    }
    
    showConfirmModal('Restoring will replace ALL current data. This cannot be undone. Continue?', async () => {
        const formData = new FormData();
        formData.append('backup', file);
        
        try {
            const response = await fetch('/admin/restore', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                showNotification('Database restored successfully', 'success');
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                showNotification('Restore failed: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error restoring database:', error);
            showNotification('Failed to restore database', 'error');
        }
    });
}

async function resetSystem() {
    showConfirmModal('WARNING: This will reset the ENTIRE system to factory settings. All employees, attendance records, and settings will be lost. This action CANNOT be undone. Type "RESET" to confirm.', async () => {
        const confirmText = prompt('Type "RESET" to confirm factory reset:');
        if (confirmText === 'RESET') {
            try {
                const result = await apiCall('/admin/factory-reset', 'POST', { confirm: true });
                if (result.success) {
                    showNotification('System reset to factory settings', 'success');
                    setTimeout(() => {
                        window.location.reload();
                    }, 2000);
                }
            } catch (error) {
                console.error('Error resetting system:', error);
                showNotification('Failed to reset system', 'error');
            }
        } else {
            showNotification('Reset cancelled', 'warning');
        }
    });
}

function refreshSystemInfo() {
    loadSystemInfo();
    showNotification('System info refreshed', 'success');
}

// File upload handler
document.getElementById('restoreFile')?.addEventListener('change', function(e) {
    const restoreBtn = document.getElementById('restoreBtn');
    if (e.target.files.length > 0) {
        restoreBtn.style.display = 'inline-flex';
        showNotification(`Selected: ${e.target.files[0].name}`, 'success');
    } else {
        restoreBtn.style.display = 'none';
    }
});

// Admin credentials update
document.getElementById('systemSettingsForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const username = document.getElementById('adminUsername').value;
    const password = document.getElementById('adminPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    if (password && password !== confirmPassword) {
        showNotification('Passwords do not match', 'error');
        return;
    }
    
    try {
        const result = await apiCall('/admin/update-credentials', 'POST', {
            username: username || null,
            password: password || null
        });
        
        if (result.success) {
            showNotification('Admin credentials updated successfully', 'success');
            document.getElementById('adminUsername').value = '';
            document.getElementById('adminPassword').value = '';
            document.getElementById('confirmPassword').value = '';
            loadSystemInfo();
        }
    } catch (error) {
        console.error('Error updating credentials:', error);
        showNotification('Failed to update credentials', 'error');
    }
});

// Close modal when clicking on X or outside
window.onclick = function(event) {
    const modal = document.getElementById('confirmModal');
    if (event.target === modal) {
        closeConfirmModal();
    }
}