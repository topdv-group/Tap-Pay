# tapandpay_server.py - Main Flask server for attendance and payment system
import os
import sys
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db
from waitress import serve
import hashlib
import secrets
import json
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import logger first
try:
    from imports import logger
except ImportError:
    # Fallback logger if imports module doesn't exist
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

from helpers_funcs import (
    checkDuplicatePhoneOrRFID,
    markAttendanceByRFID,
    attendanceResetTimer,
    paymentTimer,
    check_missed_events_on_startup,
    init_settings,
    get_setting,
    save_settings_to_firebase,
    paymentStatusChecker,
    retry_failed_payments,
    manual_payment_verification,
    check_pending_payments
)

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Load environmental variables
load_dotenv()

# Get Firebase configuration from environment
firebase_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
firebase_key_path = os.getenv("FIREBASE_KEY_PATH")
DATABASE_URL = os.getenv("DATABASE_URL")

# Validate environment variables before startup
if not firebase_key_path and not firebase_json:
    logger.error("Either FIREBASE_KEY_PATH or FIREBASE_SERVICE_ACCOUNT must be set in .env")
    raise ValueError("Firebase configuration missing in .env")

if not DATABASE_URL:
    logger.error("DATABASE_URL missing in .env")
    raise ValueError("DATABASE_URL missing in .env")

# Initialize Firebase credentials
if firebase_json:
    try:
        cred_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cred_dict)
        logger.info("Firebase credentials loaded from environment variable")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse FIREBASE_SERVICE_ACCOUNT JSON: {e}")
        raise
else:
    cred = credentials.Certificate(firebase_key_path)
    logger.info("Firebase credentials loaded from file")

# Initialize Firebase SDK
try:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            'databaseURL': DATABASE_URL
        })
        logger.info("Firebase initialized successfully")
    else:
        logger.info("Firebase already initialized")
except Exception as e:
    logger.error(f"Firebase initialization error: {e}")
    raise

# Create Flask app
app = Flask(__name__, static_folder='static')
CORS(app)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "default-secret-key-change-in-production")
app.config['JSON_SORT_KEYS'] = False

# Initialize rate limiter (after app creation)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Initialize settings from Firebase
try:
    init_settings()
    logger.info("System settings loaded from Firebase")
except Exception as e:
    logger.error(f"Error loading settings: {e}")

# Store user data in Firebase
def init_admin_user():
    """Initialize default admin user if none exists"""
    try:
        users_ref = db.reference("USERS")
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@tapandpay.com').lower()
        admin_password = os.getenv('ADMIN_PASSWORD', 'Admin123!')
        
        # Get all users
        users = users_ref.get()
        
        # Check if admin user already exists
        admin_exists = False
        if users:
            for key, user in users.items():
                if user.get('email', '').lower() == admin_email:
                    admin_exists = True
                    logger.info(f"Admin user already exists: {admin_email}")
                    break
        
        # Create admin if not exists
        if not admin_exists:
            salt = secrets.token_hex(16)
            hashed = hashlib.pbkdf2_hmac('sha256', admin_password.encode(), salt.encode(), 100000)
            
            new_user_ref = users_ref.push()
            new_user_ref.set({
                'email': admin_email,
                'password_hash': hashed.hex(),
                'salt': salt,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'role': 'admin'
            })
            logger.info(f"✓ Default admin user created: {admin_email}")
            logger.info(f"✓ Default password: {admin_password}")
        else:
            logger.info(f"✓ Admin user exists, skipping creation")
            
    except Exception as e:
        logger.error(f"Error initializing admin user: {e}")
        import traceback
        traceback.print_exc()

# Call this after Firebase initialization
try:
    init_admin_user()
except Exception as e:
    logger.error(f"Failed to initialize admin user: {e}")


# =========================
# SERVE FRONTEND STATIC FILES
# =========================

@app.route('/')
def serve_index():
    """Serve the main dashboard"""
    return send_from_directory('static', 'index.html')

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Serve all static files (HTML, CSS, JS)"""
    # Define valid file extensions
    valid_extensions = ('.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg')
    
    # Check if file has a valid extension
    if filename.endswith(valid_extensions):
        return send_from_directory('static', filename)
    
    # If file not found in static, try to serve HTML files
    if filename.endswith('.html'):
        return send_from_directory('static', filename)
    
    # For JS files in JS folder
    if filename.startswith('JS/') and filename.endswith('.js'):
        return send_from_directory('static', filename)
    
    # Default - try to serve from static
    return send_from_directory('static', filename)


# =========================
# HEALTH CHECK ENDPOINTS
# =========================

@app.route("/health", methods=["GET"])
def health_check():
    """Detailed health check endpoint"""
    try:
        db.reference("/").get(shallow=True)
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "timestamp": datetime.now().isoformat()
    }), 200 if db_status == "connected" else 503


# =========================
# EMPLOYEE MANAGEMENT ENDPOINTS
# =========================

@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute") 
def register():
    """Register a new employee"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()
        rfid = data.get("rfid", "").strip()
        
        if not all([name, phone, rfid]):
            return jsonify({
                "error": "Missing required fields: name, phone, and rfid are required"
            }), 400
        
        if not phone.isdigit() or len(phone) < 9:
            return jsonify({
                "error": "Invalid phone number. Must contain only digits and be at least 9 digits"
            }), 400
        
        duplicate_found, duplicate_type = checkDuplicatePhoneOrRFID(phone, rfid)
        
        if duplicate_found:
            return jsonify({
                "status": "fail",
                "message": f"Registration failed. The {duplicate_type} already exists."
            }), 409
        
        employee_ref = db.reference("EMPLOYEES")
        new_emp_ref = employee_ref.push({
            'rfid': rfid,
            'name': name,
            'phone': phone,
            'registerTime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'attended': False,
            'paid': False,
            'attendance': []
        })
        
        logger.info(f"New employee registered: {name} (ID: {new_emp_ref.key})")
        
        return jsonify({
            "status": "success",
            "message": "User registered successfully",
            "data": {
                "id": new_emp_ref.key,
                "name": name,
                "phone": phone,
                "rfid": rfid
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500

@app.route("/get_employees", methods=["GET"])
def get_employees():
    """Retrieve all employees"""
    try:
        target_ref = db.reference("EMPLOYEES")
        snapshot = target_ref.get()
        
        if not snapshot:
            return jsonify({
                "status": "success",
                "message": "No employees found in database",
                "employees": [],
                "count": 0
            }), 200
        
        employee_list = []
        for key, details in snapshot.items():
            employee_list.append({
                "id": key,
                "details": details
            })
        
        logger.info(f"Retrieved {len(employee_list)} employees")
        
        return jsonify({
            "status": "success",
            "employees": employee_list,
            "count": len(employee_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Retrieval error: {str(e)}")
        return jsonify({"error": f"Failed to retrieve employee data: {str(e)}"}), 500

@app.route("/get_employee/<employee_id>", methods=["GET"])
def get_employee(employee_id):
    """Retrieve a single employee by ID"""
    try:
        employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
        employee_data = employee_ref.get()
        
        if not employee_data:
            return jsonify({"error": "Employee not found"}), 404
        
        return jsonify({
            "status": "success",
            "employee": {
                "id": employee_id,
                "details": employee_data
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving employee: {str(e)}")
        return jsonify({"error": f"Failed to retrieve employee: {str(e)}"}), 500

@app.route("/update_employee/<employee_id>", methods=["PUT"])
def update_employee(employee_id):
    """Update employee information"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
        existing = employee_ref.get()
        
        if not existing:
            return jsonify({"error": "Employee not found"}), 404
        
        updates = {}
        allowed_fields = ["name", "phone", "rfid"]
        for field in allowed_fields:
            if field in data and data[field]:
                updates[field] = data[field].strip()
        
        if updates:
            updates["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            employee_ref.update(updates)
            logger.info(f"Employee {employee_id} updated")
        
        return jsonify({
            "status": "success",
            "message": "Employee updated successfully",
            "updated_fields": list(updates.keys())
        }), 200
        
    except Exception as e:
        logger.error(f"Update error: {str(e)}")
        return jsonify({"error": f"Failed to update employee: {str(e)}"}), 500

@app.route("/delete_employee/<employee_id>", methods=["DELETE"])
def delete_employee(employee_id):
    """Delete an employee"""
    try:
        employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
        existing = employee_ref.get()
        
        if not existing:
            return jsonify({"error": "Employee not found"}), 404
        
        employee_ref.delete()
        logger.info(f"Employee {employee_id} deleted")
        
        return jsonify({
            "status": "success",
            "message": "Employee deleted successfully"
        }), 200
        
    except Exception as e:
        logger.error(f"Deletion error: {str(e)}")
        return jsonify({"error": f"Failed to delete employee: {str(e)}"}), 500


# =========================
# ATTENDANCE ENDPOINTS
# =========================

@app.route('/markAttendance', methods=["POST"])
@limiter.limit("30 per minute")
def mark_attendance():
    """Mark attendance using RFID"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        rfid = data.get("rfid")
        if not rfid:
            return jsonify({"error": "RFID is required"}), 400
        
        timestamp = data.get("time")
        result = markAttendanceByRFID(rfid, timestamp)
        
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Attendance marking error: {str(e)}")
        return jsonify({"error": f"Failed to mark attendance: {str(e)}"}), 500

@app.route("/get_attendance", methods=["GET"])
def get_attendance():
    """Get attendance records for date range"""
    try:
        date = request.args.get("date")
        employee_id = request.args.get("employee_id")
        
        if not date and not employee_id:
            return jsonify({"error": "Provide either date or employee_id"}), 400
        
        if employee_id:
            employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
            employee_data = employee_ref.get()
            
            if not employee_data:
                return jsonify({"error": "Employee not found"}), 404
            
            attendance = employee_data.get("attendance", [])
            return jsonify({
                "status": "success",
                "employee_id": employee_id,
                "employee_name": employee_data.get("name"),
                "attendance": attendance,
                "total_days": len(attendance)
            }), 200
        
        else:
            employees_ref = db.reference("EMPLOYEES")
            employees = employees_ref.get()
            
            if not employees:
                return jsonify({"attendance": []}), 200
            
            attendance_list = []
            for key, details in employees.items():
                for record in details.get("attendance", []):
                    if record.get("date") == date:
                        attendance_list.append({
                            "employee_id": key,
                            "name": details.get("name"),
                            "timestamp": record.get("timestamp")
                        })
            
            return jsonify({
                "status": "success",
                "date": date,
                "attendance": attendance_list,
                "count": len(attendance_list)
            }), 200
            
    except Exception as e:
        logger.error(f"Error retrieving attendance: {str(e)}")
        return jsonify({"error": f"Failed to retrieve attendance: {str(e)}"}), 500


# =========================
# PAYMENT WEBHOOK ENDPOINT
# =========================

@app.route("/pawapay/webhook", methods=["POST"])
def pawapay_webhook():
    """Handle PawaPay webhook callbacks"""
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        payout_id = data.get("payoutId")
        status = data.get("status")  # COMPLETED, FAILED, REJECTED, EXPIRED
        
        if not payout_id:
            return jsonify({"error": "Missing payoutId"}), 400
        
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        found = False
        if employees:
            for key, details in employees.items():
                if details.get("payoutId") == payout_id:
                    single_ref = db.reference(f"EMPLOYEES/{key}")
                    
                    # Update payment status from webhook
                    single_ref.update({
                        "payment_status": status,
                        "webhook_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "webhook_data": data
                    })
                    
                    # ONLY mark as paid when webhook says COMPLETED
                    if status == "COMPLETED":
                        single_ref.update({"paid": True})
                        logger.info(f"✓ Payment CONFIRMED for employee {key}")
                    elif status in ["FAILED", "REJECTED", "EXPIRED"]:
                        single_ref.update({"paid": False})
                        logger.warning(f"✗ Payment FAILED for employee {key}: {status}")
                    
                    found = True
                    break
        
        if not found:
            logger.warning(f"Webhook received for unknown payoutId: {payout_id}")
        
        return jsonify({"success": True, "message": "Webhook processed"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# =========================
# STATISTICS ENDPOINT
# =========================

@app.route("/stats", methods=["GET"])
def get_stats():
    """Get system statistics"""
    try:
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        if not employees:
            return jsonify({
                "total_employees": 0,
                "attended_today": 0,
                "paid_today": 0
            }), 200
        
        total = len(employees)
        attended = sum(1 for emp in employees.values() if emp.get("attended", False))
        paid = sum(1 for emp in employees.values() if emp.get("paid", False))
        
        return jsonify({
            "total_employees": total,
            "attended_today": attended,
            "paid_today": paid,
            "attendance_percentage": round((attended / total * 100) if total > 0 else 0, 2),
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Stats error: {str(e)}")
        return jsonify({"error": f"Failed to get stats: {str(e)}"}), 500


# =========================
# ADMIN ENDPOINTS
# =========================

@app.route('/admin/settings', methods=['GET'])
def get_admin_settings():
    """Get current system settings from Firebase"""
    try:
        settings_ref = db.reference("SYSTEM_SETTINGS")
        firebase_settings = settings_ref.get()
        
        if not firebase_settings:
            firebase_settings = {
                'paymentTime': '17:30',
                'payAmount': 100,
                'shiftExpirelyTime': '17:00'
            }
        
        settings = {
            'paymentTime': firebase_settings.get('paymentTime', '17:30'),
            'payAmount': int(firebase_settings.get('payAmount', 100)),
            'shiftExpirelyTime': firebase_settings.get('shiftExpirelyTime', '17:00'),
            'pawapayApiUrl': firebase_settings.get('pawapayApiUrl', 'https://api.sandbox.pawapay.io/v2/payouts'),
            'environment': 'production' if os.getenv('PRODUCTION') == 'true' else 'development'
        }
        
        return jsonify(settings), 200
        
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/settings/payment', methods=['POST'])
def update_payment_settings():
    """Update payment settings in Firebase"""
    try:
        data = request.get_json()
        updates = {}
        
        if 'paymentTime' in data:
            updates['paymentTime'] = data['paymentTime']
            
        if 'payAmount' in data:
            updates['payAmount'] = int(data['payAmount'])
            
        if 'shiftExpireTime' in data:
            updates['shiftExpirelyTime'] = data['shiftExpireTime']
            
        if 'pawapayApiUrl' in data:
            updates['pawapayApiUrl'] = data['pawapayApiUrl']
        
        if updates:
            settings_ref = db.reference("SYSTEM_SETTINGS")
            settings_ref.update(updates)
            
            # Also update the global settings in helpers_funcs
            try:
                from helpers_funcs import settings as helpers_settings
                helpers_settings.update(updates)
            except ImportError:
                pass
            
            logger.info(f"Payment settings updated in Firebase: {updates}")
            
        return jsonify({"success": True, "message": "Settings updated successfully"}), 200
        
    except Exception as e:
        logger.error(f"Error updating payment settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/settings/reset', methods=['POST'])
def reset_settings():
    """Reset settings to default values in Firebase"""
    try:
        default_settings = {
            'paymentTime': '17:30',
            'payAmount': 100,
            'shiftExpirelyTime': '17:00',
            'pawapayApiUrl': 'https://api.sandbox.pawapay.io/v2/payouts'
        }
        
        settings_ref = db.reference("SYSTEM_SETTINGS")
        settings_ref.set(default_settings)
        
        try:
            from helpers_funcs import settings as helpers_settings
            helpers_settings.update(default_settings)
        except ImportError:
            pass
        
        logger.info("Settings reset to defaults in Firebase")
        return jsonify({"success": True, "message": "Settings reset to defaults"}), 200
        
    except Exception as e:
        logger.error(f"Error resetting settings: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# BACKUP ENDPOINT - Database Backup
# =========================

@app.route('/admin/backup', methods=['GET'])
def backup_database():
    """Download database backup as JSON"""
    try:
        import json
        from datetime import datetime
        
        employees_ref = db.reference("EMPLOYEES")
        employees = employees_ref.get()
        
        settings_ref = db.reference("SYSTEM_SETTINGS")
        system_settings = settings_ref.get()
        
        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'employees': employees,
            'system_settings': system_settings,
            'exported_by': 'admin_panel'
        }
        
        response = make_response(json.dumps(backup_data, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        return response
        
    except Exception as e:
        logger.error(f"Error backing up database: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# LOGS ENDPOINTS - System Logs
# =========================

@app.route('/admin/logs', methods=['GET'])
def get_system_logs():
    """Get recent system logs from file"""
    try:
        import glob
        
        log_files = glob.glob('logs/*.log')
        logs = []
        
        # Get the main system log
        log_file = 'logs/system.log'
        
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                # Read last 200 lines
                lines = f.readlines()[-200:]
                
                for line in lines:
                    try:
                        # Parse log format: 2024-01-01 12:00:00,123 - name - LEVEL - message
                        parts = line.split(' - ', 3)
                        if len(parts) >= 4:
                            logs.append({
                                'timestamp': parts[0],
                                'level': parts[2],
                                'message': parts[3].strip()
                            })
                        else:
                            # Fallback for different format
                            logs.append({
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'level': 'INFO',
                                'message': line.strip()
                            })
                    except Exception as parse_error:
                        logger.error(f"Error parsing log line: {parse_error}")
                        continue
        
        # Return logs in reverse order (newest first)
        logs.reverse()
        
        return jsonify(logs), 200
        
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return jsonify({"error": str(e), "logs": []}), 500

@app.route('/admin/logs/clear', methods=['POST'])
def clear_logs():
    """Clear all system logs"""
    try:
        import glob
        
        log_files = glob.glob('logs/*.log')
        
        for log_file in log_files:
            with open(log_file, 'w') as f:
                f.write(f"Logs cleared at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        logger.warning("System logs were cleared by admin")
        
        return jsonify({"success": True, "message": "Logs cleared successfully"}), 200
        
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/logs/download', methods=['GET'])
def download_logs():
    """Download all logs as a file"""
    try:
        log_file = 'logs/system.log'
        
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
            
            response = make_response(log_content)
            response.headers['Content-Type'] = 'text/plain'
            response.headers['Content-Disposition'] = f'attachment; filename=system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            return response
        else:
            return jsonify({"error": "No log file found"}), 404
            
    except Exception as e:
        logger.error(f"Error downloading logs: {e}")
        return jsonify({"error": str(e)}), 500

# =========================
# SYSTEM SETTINGS ENDPOINTS
# =========================

@app.route('/admin/system-info', methods=['GET'])
def get_system_info():
    """Get system information"""
    try:
        import platform
        import flask
        
        # Calculate uptime
        uptime_string = "N/A"
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                uptime_days = int(uptime_seconds // 86400)
                uptime_hours = int((uptime_seconds % 86400) // 3600)
                uptime_minutes = int((uptime_seconds % 3600) // 60)
                uptime_string = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m"
        except:
            pass
        
        info = {
            'python_version': platform.python_version(),
            'flask_version': flask.__version__,
            'firebase_status': 'Connected' if firebase_admin._apps else 'Disconnected',
            'server_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'system_uptime': uptime_string,
            'environment': 'Production' if os.getenv('PRODUCTION') == 'true' else 'Development'
        }
        
        return jsonify(info), 200
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/backup-info', methods=['GET'])
def get_backup_info():
    """Get backup information"""
    try:
        backup_dir = 'backups'
        last_backup = 'Never'
        
        if os.path.exists(backup_dir):
            backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.json')])
            if backups:
                last_backup_time = os.path.getmtime(os.path.join(backup_dir, backups[-1]))
                last_backup = datetime.fromtimestamp(last_backup_time).strftime("%Y-%m-%d %H:%M:%S")
        
        return jsonify({'last_backup': last_backup}), 200
    except:
        return jsonify({'last_backup': 'Never'}), 200

@app.route('/admin/update-credentials', methods=['POST'])
def update_credentials():
    """Update admin credentials"""
    try:
        data = request.get_json()
        
        # Save to Firebase for persistence
        creds_ref = db.reference("ADMIN_CREDENTIALS")
        if data.get('username'):
            creds_ref.update({'username': data['username']})
        if data.get('password'):
            # In production, hash the password!
            creds_ref.update({'password': data['password']})
        
        logger.info("Admin credentials updated")
        return jsonify({"success": True, "message": "Credentials updated"}), 200
        
    except Exception as e:
        logger.error(f"Error updating credentials: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/session-settings', methods=['POST'])
def save_session_settings():
    """Save session settings"""
    try:
        data = request.get_json()
        
        # Store in Firebase
        session_ref = db.reference("SESSION_SETTINGS")
        session_ref.update({
            'session_timeout': data.get('session_timeout', 30),
            'two_factor_auth': data.get('two_factor_auth', False),
            'email_notifications': data.get('email_notifications', True),
            'updated_at': datetime.now().isoformat()
        })
        
        logger.info("Session settings updated")
        return jsonify({"success": True, "message": "Settings saved"}), 200
        
    except Exception as e:
        logger.error(f"Error saving session settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/clear-sessions', methods=['POST'])
def clear_sessions():
    """Clear all active sessions"""
    try:
        # This would clear session tokens in production
        logger.warning("All admin sessions cleared")
        return jsonify({"success": True, "message": "All sessions cleared"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/admin/restore', methods=['POST'])
def restore_database():
    """Restore database from backup file"""
    try:
        if 'backup' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['backup']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        import json
        backup_data = json.load(file)
        
        # Restore employees
        if 'employees' in backup_data and backup_data['employees']:
            employees_ref = db.reference("EMPLOYEES")
            employees_ref.set(backup_data['employees'])
        
        # Restore settings
        if 'system_settings' in backup_data and backup_data['system_settings']:
            settings_ref = db.reference("SYSTEM_SETTINGS")
            settings_ref.set(backup_data['system_settings'])
        
        logger.warning("Database restored from backup")
        return jsonify({"success": True, "message": "Database restored"}), 200
        
    except Exception as e:
        logger.error(f"Error restoring database: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/factory-reset', methods=['POST'])
def factory_reset():
    """Factory reset - clear all data and reset settings"""
    try:
        data = request.get_json()
        if not data or not data.get('confirm'):
            return jsonify({"error": "Confirmation required"}), 400
        
        # Clear all employees
        employees_ref = db.reference("EMPLOYEES")
        employees_ref.delete()
        
        # Reset settings to defaults
        default_settings = {
            'paymentTime': '17:30',
            'payAmount': 100,
            'shiftExpirelyTime': '17:00',
            'pawapayApiUrl': 'https://api.sandbox.pawapay.io/v2/payouts'
        }
        settings_ref = db.reference("SYSTEM_SETTINGS")
        settings_ref.set(default_settings)
        
        logger.warning("FACTORY RESET performed - ALL DATA DELETED")
        return jsonify({"success": True, "message": "Factory reset complete"}), 200
        
    except Exception as e:
        logger.error(f"Error during factory reset: {e}")
        return jsonify({"error": str(e)}), 500

# =========================
# AUTHENTICATION ENDPOINTS
# =========================

@app.route('/auth/login', methods=['POST'])
@limiter.limit("10 per minute") 
def auth_login():
    """Authenticate user and return token"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        remember_me = data.get('rememberMe', False)
        
        logger.info(f"Login attempt for email: {email}")
        
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        
        # Find user
        users_ref = db.reference("USERS")
        users = users_ref.get()
        
        if not users:
            users = {}
        
        user_id = None
        user_data = None
        
        for key, user in users.items():
            if user.get('email', '').lower() == email:
                user_id = key
                user_data = user
                break
        
        if not user_data:
            logger.warning(f"User not found: {email}")
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Verify password
        salt = user_data.get('salt')
        stored_hash = str(user_data.get('password_hash', ''))
        
        if not salt or not stored_hash:
            logger.error(f"Invalid user data for {email}")
            return jsonify({"error": "Invalid credentials"}), 401
        
        computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        
        if computed_hash != stored_hash:
            logger.warning(f"Invalid password for {email}")
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Generate session token
        token = secrets.token_urlsafe(32)
        
        # Store session
        sessions_ref = db.reference("SESSIONS")
        expiry = datetime.now() + timedelta(days=7 if remember_me else 1)
        
        session_data = {
            'user_id': user_id,
            'email': email,
            'created_at': datetime.now().isoformat(),
            'expires_at': expiry.isoformat(),
            'remember_me': remember_me
        }
        
        sessions_ref.child(token).set(session_data)
        
        logger.info(f"✓ User logged in successfully: {email}")
        
        return jsonify({
            "success": True,
            "token": token,
            "email": email,
            "message": "Login successful"
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/auth/verify', methods=['GET'])
def auth_verify():
    """Verify authentication token"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return jsonify({"valid": False}), 401
        
        sessions_ref = db.reference("SESSIONS")
        session = sessions_ref.child(token).get()
        
        if not session:
            return jsonify({"valid": False}), 401
        
        # Check expiry
        expires_at = datetime.fromisoformat(session['expires_at'])
        if expires_at < datetime.now():
            sessions_ref.child(token).delete()
            return jsonify({"valid": False}), 401
        
        return jsonify({"valid": True, "email": session['email']}), 200
        
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return jsonify({"valid": False}), 401

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    """Logout user"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if token:
            sessions_ref = db.reference("SESSIONS")
            sessions_ref.child(token).delete()
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return jsonify({"success": False}), 500

@app.route('/auth/forgot-password', methods=['POST'])
def auth_forgot_password():
    """Send password reset link via email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({"error": "Email required"}), 400
        
        # Find user
        users_ref = db.reference("USERS")
        users = users_ref.get()
        
        user_id = None
        if users:
            for key, user in users.items():
                if user.get('email') == email:
                    user_id = key
                    break
        
        if not user_id:
            # For security, don't reveal that user doesn't exist
            return jsonify({
                "success": True, 
                "message": "If an account exists with this email, a reset link has been sent."
            }), 200
        
        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        
        # Store reset request
        resets_ref = db.reference("PASSWORD_RESETS")
        resets_ref.child(reset_token).set({
            'user_id': user_id,
            'email': email,
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=1)).isoformat()
        })
        
        # Create reset link
        base_url = request.host_url.rstrip('/')
        reset_link = f"{base_url}/reset-password.html?token={reset_token}"
        
        logger.info(f"Password reset requested for {email}")
        logger.info(f"Reset link: {reset_link}")
        
        # Try to send email
        email_sent = send_reset_email(email, reset_link)
        
        if email_sent:
            return jsonify({
                "success": True,
                "message": "Password reset link has been sent to your email address."
            }), 200
        else:
            # Fallback: show link on screen if email fails
            return jsonify({
                "success": True,
                "message": "Email could not be sent. Please use the link below to reset your password.",
                "reset_link": reset_link
            }), 200
        
    except Exception as e:
        logger.error(f"Forgot password error: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# EMAIL CONFIGURATION
# =========================

def send_reset_email(email, reset_link):
    """Send password reset email via SMTP"""
    try:
        # Check if SMTP is enabled
        smtp_enabled = os.getenv('SMTP_ENABLED', 'false').lower() == 'true'
        
        if not smtp_enabled:
            logger.info(f"SMTP disabled. Reset link for {email}: {reset_link}")
            return False
        
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Get SMTP configuration
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        smtp_from_email = os.getenv('SMTP_FROM_EMAIL', smtp_username)
        smtp_from_name = os.getenv('SMTP_FROM_NAME', 'Tap & Pay System')
        
        if not smtp_username or not smtp_password:
            logger.error("SMTP credentials missing. Check SMTP_USERNAME and SMTP_PASSWORD")
            return False
        
        logger.info(f"Attempting to send email to {email} via {smtp_server}:{smtp_port}")
        
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = f"{smtp_from_name} <{smtp_from_email}>"
        msg['To'] = email
        msg['Subject'] = 'Tap & Pay - Password Reset Request'
        
        # Email body (HTML)
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #e5e7eb; }}
                .button {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0; }}
                .footer {{ text-align: center; font-size: 12px; color: #6b7280; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h1>🔐 Password Reset Request</h1></div>
                <div class="content">
                    <p>Hello,</p>
                    <p>You requested to reset your password for your Tap & Pay account.</p>
                    <p>Click the button below to reset your password:</p>
                    <div style="text-align: center;">
                        <a href="{reset_link}" class="button">Reset Password</a>
                    </div>
                    <p>Or copy this link into your browser:</p>
                    <p style="background: #f3f4f6; padding: 10px; border-radius: 5px; word-break: break-all;">
                        <a href="{reset_link}" style="color: #667eea;">{reset_link}</a>
                    </p>
                    <p><strong>⚠️ This link will expire in 1 hour.</strong></p>
                    <p>If you didn't request this, please ignore this email.</p>
                </div>
                <div class="footer"><p>Tap & Pay System - Automated Attendance & Payment Management</p></div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        # Connect and send
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"✅ Password reset email sent successfully to {email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send reset email: {e}")
        return False

@app.route('/auth/reset-password', methods=['POST'])
def auth_reset_password():
    """Reset password using token"""
    try:
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('password')
        
        if not token or not new_password:
            return jsonify({"error": "Token and password required"}), 400
        
        if len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        # Verify reset token
        resets_ref = db.reference("PASSWORD_RESETS")
        reset_data = resets_ref.child(token).get()
        
        if not reset_data:
            return jsonify({"error": "Invalid or expired reset token"}), 400
        
        # Check expiry
        expires_at = datetime.fromisoformat(reset_data['expires_at'])
        if expires_at < datetime.now():
            resets_ref.child(token).delete()
            return jsonify({"error": "Reset token has expired"}), 400
        
        # Update password
        user_id = reset_data['user_id']
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac('sha256', new_password.encode(), salt.encode(), 100000)
        
        users_ref = db.reference("USERS")
        users_ref.child(user_id).update({
            'password_hash': hashed.hex(),
            'salt': salt,
            'updated_at': datetime.now().isoformat()
        })
        
        # Delete used reset token
        resets_ref.child(token).delete()
        
        # Delete all sessions for this user
        sessions_ref = db.reference("SESSIONS")
        all_sessions = sessions_ref.get()
        if all_sessions:
            for session_token, session in all_sessions.items():
                if session.get('user_id') == user_id:
                    sessions_ref.child(session_token).delete()
        
        logger.info(f"Password reset for user: {reset_data['email']}")
        
        return jsonify({"success": True, "message": "Password reset successful"}), 200
        
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/auth/change-password', methods=['POST'])
def auth_change_password():
    """Change password for authenticated user"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return jsonify({"error": "Authentication required"}), 401
        
        # Verify session
        sessions_ref = db.reference("SESSIONS")
        session = sessions_ref.child(token).get()
        
        if not session:
            return jsonify({"error": "Invalid session"}), 401
        
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({"error": "Current and new password required"}), 400
        
        # Get user
        users_ref = db.reference("USERS")
        user = users_ref.child(session['user_id']).get()
        
        # Verify current password
        salt = user.get('salt')
        stored_hash = user.get('password_hash')
        computed_hash = hashlib.pbkdf2_hmac('sha256', current_password.encode(), salt.encode(), 100000).hex()
        
        if computed_hash != stored_hash:
            return jsonify({"error": "Current password is incorrect"}), 401
        
        # Update to new password
        new_salt = secrets.token_hex(16)
        new_hashed = hashlib.pbkdf2_hmac('sha256', new_password.encode(), new_salt.encode(), 100000)
        
        users_ref.child(session['user_id']).update({
            'password_hash': new_hashed.hex(),
            'salt': new_salt,
            'updated_at': datetime.now().isoformat()
        })
        
        logger.info(f"Password changed for user: {session['email']}")
        
        return jsonify({"success": True, "message": "Password changed successfully"}), 200
        
    except Exception as e:
        logger.error(f"Change password error: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# PAYMENT ADMIN ENDPOINTS
# =========================

@app.route('/admin/payments/pending', methods=['GET'])
def get_pending_payments():
    """Get all pending payments for manual review"""
    try:
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        pending_payments = []
        
        if employees:
            for key, details in employees.items():
                if details.get("payment_status") == "PENDING":
                    pending_payments.append({
                        "employee_id": key,
                        "name": details.get("name"),
                        "phone": details.get("phone"),
                        "payout_id": details.get("payoutId"),
                        "amount": details.get("payment_amount"),
                        "request_date": details.get("payment_request_date"),
                        "retry_count": details.get("payment_retry_count", 0),
                        "status": details.get("payment_status")
                    })
        
        return jsonify({
            "status": "success",
            "pending_count": len(pending_payments),
            "payments": pending_payments
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting pending payments: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/payments/verify/<employee_id>', methods=['POST'])
def verify_payment_manually(employee_id):
    """Manually verify and fix payment status"""
    try:
        result = manual_payment_verification(employee_id)
        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/payments/retry-all', methods=['POST'])
def retry_all_failed_payments():
    """Manually trigger retry for all failed payments"""
    try:
        retry_failed_payments()
        return jsonify({
            "status": "success",
            "message": "Payment retry process triggered"
        }), 200
    except Exception as e:
        logger.error(f"Error triggering retry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/payments/check-pending', methods=['POST'])
def check_pending_payments_manual():
    """Manually trigger pending payment check"""
    try:
        check_pending_payments()
        return jsonify({
            "status": "success",
            "message": "Pending payment check triggered"
        }), 200
    except Exception as e:
        logger.error(f"Error checking pending payments: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/payments/stats', methods=['GET'])
def get_payment_stats():
    """Get payment statistics"""
    try:
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        stats = {
            "total_payments_requested": 0,
            "pending": 0,
            "completed": 0,
            "failed": 0,
            "manual_review": 0,
            "total_amount_paid": 0
        }
        
        if employees:
            for details in employees.values():
                status = details.get("payment_status")
                if status:
                    stats["total_payments_requested"] += 1
                    
                    if status == "PENDING":
                        stats["pending"] += 1
                    elif status == "COMPLETED":
                        stats["completed"] += 1
                        stats["total_amount_paid"] += details.get("payment_amount", 0)
                    elif status in ["FAILED", "REJECTED", "EXPIRED"]:
                        stats["failed"] += 1
                    elif status == "MANUAL_REVIEW_REQUIRED":
                        stats["manual_review"] += 1
        
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error getting payment stats: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# ERROR HANDLERS
# =========================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


# =========================
# MAIN ENTRY POINT
# =========================
if __name__ == "__main__":
    # Start background threads
    logger.info("Starting background threads...")
    
    attendance_thread = threading.Thread(
        target=attendanceResetTimer,
        name="AttendanceResetThread",
        daemon=True
    )
    attendance_thread.start()
    
    payment_thread = threading.Thread(
        target=paymentTimer,
        name="PaymentThread",
        daemon=True
    )
    payment_thread.start()

    # Start payment status checker thread (fallback mechanism)
    payment_checker_thread = threading.Thread(
        target=paymentStatusChecker,
        name="PaymentStatusCheckerThread",
        daemon=True
    )
    payment_checker_thread.start()
    logger.info("Payment status checker thread started (fallback for missed webhooks)")
    
    logger.info("Background threads started successfully")
    
    # Check for missed events on startup
    try:
        check_missed_events_on_startup()
    except Exception as e:
        logger.error(f"Error checking missed events: {e}")
    
    # Get port from environment variable
    port = int(os.environ.get("PORT", 5000))
    
    logger.info(f"Starting Flask server on http://0.0.0.0:{port}")
    logger.info(f"Open your browser and go to: http://localhost:{port}")
    
    # Serve with waitress
    serve(app, host="0.0.0.0", port=port)
