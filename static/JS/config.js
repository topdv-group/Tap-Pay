// config.js - API Configuration
const API_BASE_URL = ''; // Empty string means use same origin

// API endpoints
const API_ENDPOINTS = {
    REGISTER: '/register',
    GET_EMPLOYEES: '/get_employees',
    GET_EMPLOYEE: (id) => `/get_employee/${id}`,
    UPDATE_EMPLOYEE: (id) => `/update_employee/${id}`,
    DELETE_EMPLOYEE: (id) => `/delete_employee/${id}`,
    MARK_ATTENDANCE: '/markAttendance',
    GET_ATTENDANCE: '/get_attendance',
    STATS: '/stats',
    WEBHOOK: '/pawapay/webhook'
};

// Helper function for API calls
async function apiCall(endpoint, method = 'GET', data = null) {
    const url = `${API_BASE_URL}${endpoint}`;
    console.log(`Making API call to: ${url}`, { method, data });
    
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    if (data && (method === 'POST' || method === 'PUT')) {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, options);
        const result = await response.json();
        
        console.log(`API response from ${endpoint}:`, result);
        
        if (!response.ok) {
            throw new Error(result.error || result.message || 'API call failed');
        }
        
        return result;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Utility functions
function showNotification(message, type = 'success') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Add styles dynamically
    if (!document.querySelector('#notification-styles')) {
        const style = document.createElement('style');
        style.id = 'notification-styles';
        style.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 12px 20px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                display: flex;
                align-items: center;
                gap: 10px;
                z-index: 10000;
                animation: slideIn 0.3s ease;
                font-size: 14px;
                font-weight: 500;
            }
            .notification.success {
                border-left: 4px solid #10b981;
                color: #065f46;
            }
            .notification.error {
                border-left: 4px solid #ef4444;
                color: #991b1b;
            }
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
        `;
        document.head.appendChild(style);
    }
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// HTML escape function to prevent XSS attacks
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(date = new Date()) {
    return date.toISOString().split('T')[0];
}

function formatDateTime(date = new Date()) {
    return date.toLocaleString('en-RW', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

// Update time display
function updateTimeDisplay() {
    const timeElement = document.getElementById('currentTime');
    if (timeElement) {
        const now = new Date();
        timeElement.textContent = now.toLocaleTimeString('en-RW');
    }
}

// Auto refresh time every second
setInterval(updateTimeDisplay, 1000);
updateTimeDisplay();