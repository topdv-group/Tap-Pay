// register.js - Employee Registration

document.addEventListener('DOMContentLoaded', async () => {
    await loadStats();
    setupForm();
    setupRFIDListener();
});

function setupForm() {
    const form = document.getElementById('registerForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await registerEmployee();
    });
}

function setupRFIDListener() {
    const rfidInput = document.getElementById('rfid');
    
    // Auto-focus RFID input
    rfidInput.focus();
    
    // Optional: Listen for RFID scanner input
    rfidInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            // Move to next field or submit
            document.getElementById('name').focus();
        }
    });
}

async function registerEmployee() {
    // Get form values
    const name = document.getElementById('name').value.trim();
    const phone = document.getElementById('phone').value.trim();
    const rfid = document.getElementById('rfid').value.trim();
    
    // Clear previous errors
    clearErrors();
    
    // Validate
    let isValid = true;
    
    if (!name) {
        showError('nameError', 'Name is required');
        isValid = false;
    } else if (name.length < 2) {
        showError('nameError', 'Name must be at least 2 characters');
        isValid = false;
    }
    
    if (!phone) {
        showError('phoneError', 'Phone number is required');
        isValid = false;
    } else if (!/^\d{9,10}$/.test(phone)) {
        showError('phoneError', 'Phone number must be 9-10 digits');
        isValid = false;
    }
    
    if (!rfid) {
        showError('rfidError', 'RFID tag is required');
        isValid = false;
    } else if (rfid.length < 4) {
        showError('rfidError', 'RFID tag must be at least 4 characters');
        isValid = false;
    }
    
    if (!isValid) return;
    
    // Show loading state
    const submitBtn = document.querySelector('#registerForm button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registering...';
    submitBtn.disabled = true;
    
    try {
        const result = await apiCall(API_ENDPOINTS.REGISTER, 'POST', {
            name,
            phone,
            rfid
        });
        
        if (result.status === 'success') {
            // Show success message
            const successDiv = document.getElementById('successMessage');
            successDiv.style.display = 'block';
            
            // Reset form
            resetForm();
            
            // Reload stats
            await loadStats();
            
            // Hide success message after 3 seconds
            setTimeout(() => {
                successDiv.style.display = 'none';
            }, 3000);
            
            // Focus on RFID for next registration
            document.getElementById('rfid').focus();
        }
        
    } catch (error) {
        console.error('Registration error:', error);
        showNotification(error.message || 'Registration failed. Please try again.', 'error');
        
        // Show error in form
        if (error.message.includes('phone')) {
            showError('phoneError', error.message);
        } else if (error.message.includes('rfid')) {
            showError('rfidError', error.message);
        } else {
            showNotification(error.message, 'error');
        }
        
    } finally {
        // Reset button
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

function resetForm() {
    document.getElementById('registerForm').reset();
    clearErrors();
    
    // Focus back on RFID
    document.getElementById('rfid').focus();
}

function clearErrors() {
    document.querySelectorAll('.error-message').forEach(el => {
        el.textContent = '';
    });
}

function showError(elementId, message) {
    const errorElement = document.getElementById(elementId);
    if (errorElement) {
        errorElement.textContent = message;
    }
}

async function loadStats() {
    try {
        const stats = await apiCall(API_ENDPOINTS.STATS);
        
        document.getElementById('totalCount').textContent = stats.total_employees || 0;
        document.getElementById('todayCount').textContent = stats.attended_today || 0;
        
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}