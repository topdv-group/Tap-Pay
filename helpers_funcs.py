# helpers_funcs.py - Helper functions for attendance and payment processing
import time
from datetime import datetime, timedelta
from threading import Timer
import os
import threading
import uuid
import requests
from datetime import datetime
from dotenv import load_dotenv
from firebase_admin import db
from imports import logger, shutdown_event


# Add these constants after existing imports
MAX_PAYMENT_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 minutes between retries
PAYMENT_STATUS_CHECK_INTERVAL = 300  # Check pending payments every 5 minutes
WEBHOOK_TIMEOUT_HOURS = 24  # How long to keep retrying before manual intervention

# Load environment variables
load_dotenv()

# Default settings (will be overridden by Firebase)
DEFAULT_SETTINGS = {
    "shiftExpirelyTime": "17:00",
    "paymentTime": "17:30",
    "payAmount": 100,
    "pawapayApiUrl": "https://api.sandbox.pawapay.io/v2/payouts"
}

# Global settings dictionary
settings = DEFAULT_SETTINGS.copy()

# Thread locks
reset_lock = threading.Lock()
payment_lock = threading.Lock()

# Daily trackers
last_reset_date = None
last_payment_date = None

def is_time_reached(target_time_str):
    """Check if current time has reached or passed target time"""
    try:
        now = datetime.now()
        target = datetime.strptime(target_time_str, "%H:%M").time()
        current = now.time()
        
        # Compare as time objects, not strings
        return current >= target
    except Exception as e:
        logger.error(f"Time comparison error: {e}")
        return False

def load_settings_from_firebase():
    """Load settings from Firebase database"""
    global settings
    
    try:
        settings_ref = db.reference("SYSTEM_SETTINGS")
        firebase_settings = settings_ref.get()
        
        if firebase_settings:
            # Update settings with values from Firebase
            if "shiftExpirelyTime" in firebase_settings:
                settings["shiftExpirelyTime"] = firebase_settings["shiftExpirelyTime"]
            if "paymentTime" in firebase_settings:
                settings["paymentTime"] = firebase_settings["paymentTime"]
            if "payAmount" in firebase_settings:
                settings["payAmount"] = int(firebase_settings["payAmount"])
            if "pawapayApiUrl" in firebase_settings:
                settings["pawapayApiUrl"] = firebase_settings["pawapayApiUrl"]
            
            logger.info(f"Settings loaded from Firebase: {settings}")
        else:
            # Initialize default settings in Firebase
            save_settings_to_firebase(settings)
            logger.info("Default settings saved to Firebase")
            
    except Exception as e:
        logger.error(f"Error loading settings from Firebase: {e}")

def save_settings_to_firebase(new_settings):
    """Save settings to Firebase database"""
    global settings
    
    try:
        settings_ref = db.reference("SYSTEM_SETTINGS")
        settings_ref.update(new_settings)
        settings.update(new_settings)
        logger.info(f"Settings saved to Firebase: {new_settings}")
        return True
    except Exception as e:
        logger.error(f"Error saving settings to Firebase: {e}")
        return False

def get_setting(key, default=None):
    """Get a setting value"""
    return settings.get(key, default)

def init_settings():
    """Initialize settings from Firebase"""
    try:
        load_settings_from_firebase()
        logger.info(f"Current settings - Payment Time: {get_setting('paymentTime')}, Amount: {get_setting('payAmount')}, Shift Expiry: {get_setting('shiftExpirelyTime')}")
    except Exception as e:
        logger.error(f"Settings initialization error: {e}")

def isRfidFound(rfid):
    """Check if RFID exists in database"""
    try:
        if not rfid:
            return False, None, None

        employee_ref = db.reference("EMPLOYEES")
        snapshot = employee_ref.get()

        if not snapshot:
            return False, None, None

        for key, details in snapshot.items():
            if str(details.get("rfid")) == str(rfid):
                return True, key, details

        return False, None, None

    except Exception as e:
        logger.error(f"Error checking RFID: {e}")
        return False, None, None

def checkDuplicatePhoneOrRFID(phone, rfid):
    """Check duplicate phone or RFID"""
    try:
        employee_ref = db.reference("EMPLOYEES")
        snapshot = employee_ref.get()

        if not snapshot:
            return False, None

        for key, details in snapshot.items():
            if str(details.get("phone")) == str(phone):
                return True, "phone"
            if str(details.get("rfid")) == str(rfid):
                return True, "rfid"

        return False, None

    except Exception as e:
        logger.error(f"Duplicate check error: {e}")
        return False, None

def markAttendanceByRFID(rfid, custom_timestamp=None):
    """Mark attendance using RFID"""
    try:
        found, employee_id, employee_details = isRfidFound(rfid)

        if not found:
            return {
                "success": False,
                "message": f"RFID {rfid} not found"
            }

        current_time = (
            custom_timestamp
            if custom_timestamp
            else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        today_date = current_time.split(" ")[0]

        employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
        current_data = employee_ref.get()

        if not current_data:
            return {
                "success": False,
                "message": "Employee data not found"
            }

        if "attendance" not in current_data:
            current_data["attendance"] = []

        already_marked = False
        for record in current_data.get("attendance", []):
            timestamp = record.get("timestamp", "")
            if timestamp.startswith(today_date):
                already_marked = True
                break

        if already_marked:
            return {
                "success": True,
                "already_marked": True,
                "message": f"{employee_details.get('name')} already attended today"
            }

        attendance_record = {
            "timestamp": current_time,
            "date": today_date
        }

        current_data["attendance"].append(attendance_record)

        employee_ref.update({
            "attendance": current_data["attendance"],
            "attended": True,
            "last_attendance": current_time,
            "last_attendance_date": today_date
        })

        logger.info(f"Attendance marked for {employee_details.get('name')}")

        return {
            "success": True,
            "message": f"Attendance marked for {employee_details.get('name')}",
            "data": {
                "employee_id": employee_id,
                "name": employee_details.get("name"),
                "timestamp": current_time
            }
        }

    except Exception as e:
        logger.error(f"Attendance error: {e}")
        return {
            "success": False,
            "message": str(e)
        }

def resetAttendance():
    """Reset attendance daily"""
    global last_reset_date

    with reset_lock:
        current_date = datetime.now().strftime("%Y-%m-%d")
        shift_expire_time = get_setting("shiftExpirelyTime", "17:00")
        
        logger.info(f"Reset check - Time: {datetime.now().strftime('%H:%M')}, Target: {shift_expire_time}, Last reset: {last_reset_date}, Today: {current_date}")

        if is_time_reached(shift_expire_time) and last_reset_date != current_date:
            try:
                logger.info("Starting attendance reset...")
                employee_ref = db.reference("EMPLOYEES")
                employees = employee_ref.get()

                if not employees:
                    logger.info("No employees to reset")
                    last_reset_date = current_date
                    return

                reset_count = 0
                for key, details in employees.items():
                    single_ref = db.reference(f"EMPLOYEES/{key}")
                    single_ref.update({
                        "attended": False,
                        "paid": False
                    })
                    reset_count += 1

                last_reset_date = current_date
                logger.info(f"Attendance reset complete for {reset_count} employees")

            except Exception as e:
                logger.error(f"Attendance reset error: {e}")

def payEmployees():
    """Process employee payments - Request payment, wait for webhook confirmation"""
    global last_payment_date

    with payment_lock:
        current_date = datetime.now().strftime("%Y-%m-%d")
        payment_time = get_setting("paymentTime", "17:30")
        pay_amount = get_setting("payAmount", 100)
        api_key = os.getenv("PAWAPAY_API_KEY")
        api_url = get_setting("pawapayApiUrl", "https://api.sandbox.pawapay.io/v2/payouts")
        
        logger.info(f"Payment check - Time: {datetime.now().strftime('%H:%M')}, Target: {payment_time}")

        if is_time_reached(payment_time) and last_payment_date != current_date:
            logger.info("Starting employee payment requests...")

            try:
                employee_ref = db.reference("EMPLOYEES")
                employees = employee_ref.get()

                if not employees:
                    logger.info("No employees found")
                    last_payment_date = current_date
                    return

                if not api_key:
                    logger.error("PAWAPAY_API_KEY missing")
                    last_payment_date = current_date
                    return

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                successful_requests = 0
                failed_requests = 0
                skipped_payments = 0

                for key, details in employees.items():
                    try:
                        # Skip if already paid today (confirmed by webhook)
                        if details.get("paid") is True:
                            skipped_payments += 1
                            continue

                        # Skip if payment already requested and pending
                        if details.get("payment_status") == "PENDING":
                            logger.info(f"Payment already pending for employee {key}")
                            skipped_payments += 1
                            continue

                        # Skip absent users
                        if details.get("attended") is False:
                            skipped_payments += 1
                            continue

                        phone = details.get("phone")
                        if not phone:
                            logger.warning(f"No phone for employee {key}")
                            failed_requests += 1
                            continue

                        clean_phone = ''.join(filter(str.isdigit, str(phone)))
                        if len(clean_phone) < 9:
                            logger.warning(f"Invalid phone number {phone}")
                            failed_requests += 1
                            continue

                        formatted_phone = f"250{clean_phone[-9:]}"
                        payout_id = str(uuid.uuid4())

                        payload = {
                            "payoutId": payout_id,
                            "amount": pay_amount,
                            "currency": "RWF",
                            "recipient": {
                                "type": "MMO",
                                "accountDetails": {
                                    "phoneNumber": formatted_phone,
                                    "provider": "MTN_MOMO_RWA"
                                }
                            }
                        }

                        logger.info(f"Requesting payment of {pay_amount} RWF to {formatted_phone}")

                        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                        response_data = response.json()

                        employee_single_ref = db.reference(f"EMPLOYEES/{key}")

                        if response.status_code in [200, 201, 202] and response_data.get("status") == "ACCEPTED":
                            # IMPORTANT: Mark as PENDING, NOT paid!
                            # Wait for webhook to confirm actual payment
                            employee_single_ref.update({
                                "paid": False,  # ← NOT paid yet! Webhook will update this
                                "payment_status": "PENDING",
                                "payment_request_date": current_date,
                                "payment_amount": pay_amount,
                                "payment_currency": "RWF",
                                "payoutId": payout_id,
                                "recipient_phone": formatted_phone
                            })
                            successful_requests += 1
                            logger.info(f"✓ Payment request ACCEPTED for {formatted_phone}. Waiting for webhook confirmation.")
                        else:
                            employee_single_ref.update({
                                "payment_status": response_data.get("status", "FAILED"),
                                "payment_error": response_data.get("message", "Unknown error"),
                                "last_payment_attempt": current_date
                            })
                            failed_requests += 1
                            logger.error(f"✗ Payment request FAILED for {formatted_phone}: {response_data}")

                    except requests.exceptions.Timeout:
                        failed_requests += 1
                        logger.error(f"Payment timeout for employee {key}")
                    except requests.exceptions.RequestException as e:
                        failed_requests += 1
                        logger.error(f"Request error for employee {key}: {e}")
                    except Exception as e:
                        failed_requests += 1
                        logger.error(f"Employee payment error: {e}")

                last_payment_date = current_date
                logger.info(f"Payment request process complete. Accepted={successful_requests}, Failed={failed_requests}, Skipped={skipped_payments}")
                logger.info("⏳ Waiting for webhook callbacks to confirm actual payment completion...")

            except Exception as e:
                logger.error(f"Payment processing error: {e}")


def check_missed_events_on_startup():
    """Check if any events were missed while server was offline"""
    global last_payment_date, last_reset_date
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")
    shift_expire_time = get_setting("shiftExpirelyTime", "17:00")
    payment_time = get_setting("paymentTime", "17:30")
    
    logger.info("Checking for missed events on startup...")
    
    if current_time >= payment_time and last_payment_date != current_date:
        logger.info("Payment time already passed today - processing payments on startup")
        payEmployees()
    
    if current_time >= shift_expire_time and last_reset_date != current_date:
        logger.info("Reset time already passed today - resetting on startup")
        resetAttendance()

def attendanceResetTimer():
    """Background timer for attendance reset"""
    logger.info("Attendance reset timer thread started")
    
    while not shutdown_event.is_set():
        try:
            resetAttendance()
        except Exception as e:
            logger.error(f"Attendance timer error: {e}")
        
        shutdown_event.wait(30)

def paymentTimer():
    """Background timer for payments"""
    logger.info("Payment timer thread started")
    
    while not shutdown_event.is_set():
        try:
            payEmployees()
        except Exception as e:
            logger.error(f"Payment timer error: {e}")
        
        shutdown_event.wait(30)


def check_pending_payments():
    """
    Check status of pending payments (fallback if webhook fails)
    This acts as a safety net for missed webhooks
    """
    try:
        logger.info("🔍 Checking pending payment statuses (fallback mechanism)...")
        
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        if not employees:
            logger.info("No employees found")
            return
        
        api_key = os.getenv("PAWAPAY_API_KEY")
        if not api_key:
            logger.error("PAWAPAY_API_KEY missing, cannot check pending payments")
            return
        
        api_url = get_setting("pawapayApiUrl", "https://api.sandbox.pawapay.io/v2/payouts")
        headers = {"Authorization": f"Bearer {api_key}"}
        
        pending_count = 0
        updated_count = 0
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        for key, details in employees.items():
            # Check for pending payments
            payment_status = details.get("payment_status")
            payout_id = details.get("payoutId")
            
            if payment_status == "PENDING" and payout_id:
                pending_count += 1
                retry_count = details.get("payment_retry_count", 0)
                
                # Check if we should stop retrying
                payment_request_date = details.get("payment_request_date")
                if payment_request_date:
                    try:
                        request_date = datetime.strptime(payment_request_date, "%Y-%m-%d")
                        hours_pending = (datetime.now() - request_date).total_seconds() / 3600
                        
                        if hours_pending > WEBHOOK_TIMEOUT_HOURS:
                            logger.warning(f"Payment {payout_id} for employee {key} has been pending for {hours_pending:.1f} hours - marking for manual review")
                            single_ref = db.reference(f"EMPLOYEES/{key}")
                            single_ref.update({
                                "payment_status": "MANUAL_REVIEW_REQUIRED",
                                "payment_error": f"Webhook timeout after {WEBHOOK_TIMEOUT_HOURS} hours",
                                "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            continue
                    except:
                        pass
                
                # Check status with PawaPay API
                try:
                    logger.info(f"Checking status for payout {payout_id} (retry {retry_count}/{MAX_PAYMENT_RETRIES})")
                    
                    response = requests.get(
                        f"{api_url}/{payout_id}",
                        headers=headers,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        payout_data = response.json()
                        status = payout_data.get("status")
                        
                        single_ref = db.reference(f"EMPLOYEES/{key}")
                        
                        if status == "COMPLETED":
                            # Payment succeeded
                            single_ref.update({
                                "paid": True,
                                "payment_status": "COMPLETED",
                                "payment_confirmed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "payment_confirmed_via": "fallback_check",
                                "payment_retry_count": 0
                            })
                            updated_count += 1
                            logger.info(f"✅ Payment confirmed via fallback for employee {key}")
                            
                        elif status in ["FAILED", "REJECTED", "EXPIRED"]:
                            # Payment failed permanently
                            single_ref.update({
                                "paid": False,
                                "payment_status": status,
                                "payment_error": payout_data.get("message", "Payment failed"),
                                "payment_failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "payment_retry_count": 0
                            })
                            updated_count += 1
                            logger.warning(f"❌ Payment failed for employee {key}: {status}")
                            
                        elif status == "PENDING" and retry_count < MAX_PAYMENT_RETRIES:
                            # Still pending, increment retry count
                            single_ref.update({
                                "payment_retry_count": retry_count + 1,
                                "last_status_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            logger.info(f"⏳ Payment still pending for employee {key} (check {retry_count + 1}/{MAX_PAYMENT_RETRIES})")
                            
                        elif status == "PENDING" and retry_count >= MAX_PAYMENT_RETRIES:
                            # Max retries exceeded
                            single_ref.update({
                                "payment_status": "MAX_RETRIES_EXCEEDED",
                                "payment_error": f"Still pending after {MAX_PAYMENT_RETRIES} checks",
                                "requires_manual_intervention": True
                            })
                            logger.error(f"⚠️ Payment pending for employee {key} after {MAX_PAYMENT_RETRIES} checks - requires manual intervention")
                    
                    elif response.status_code == 404:
                        logger.warning(f"Payout {payout_id} not found in PawaPay system")
                        single_ref = db.reference(f"EMPLOYEES/{key}")
                        single_ref.update({
                            "payment_status": "NOT_FOUND",
                            "payment_error": "Payout ID not found in payment system",
                            "requires_manual_intervention": True
                        })
                    
                    else:
                        logger.error(f"Error checking payout {payout_id}: HTTP {response.status_code}")
                        
                except requests.exceptions.Timeout:
                    logger.error(f"Timeout checking payout {payout_id}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Request error checking payout {payout_id}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error checking payout {payout_id}: {e}")
                
                # Add delay to avoid rate limiting
                time.sleep(1)
        
        if pending_count > 0:
            logger.info(f"Fallback check complete: {pending_count} pending payments, {updated_count} updated")
        else:
            logger.info("No pending payments found")
            
    except Exception as e:
        logger.error(f"Error in pending payment check: {e}")

def retry_failed_payments():
    """
    Retry failed payments automatically
    """
    try:
        logger.info("🔄 Checking for failed payments to retry...")
        
        employee_ref = db.reference("EMPLOYEES")
        employees = employee_ref.get()
        
        if not employees:
            return
        
        api_key = os.getenv("PAWAPAY_API_KEY")
        if not api_key:
            logger.error("PAWAPAY_API_KEY missing, cannot retry payments")
            return
        
        api_url = get_setting("pawapayApiUrl", "https://api.sandbox.pawapay.io/v2/payouts")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        retry_count = 0
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        for key, details in employees.items():
            # Check if payment should be retried
            payment_status = details.get("payment_status")
            retry_attempts = details.get("retry_attempts", 0)
            attended = details.get("attended", False)
            paid = details.get("paid", False)
            
            # Conditions for retry:
            # 1. Payment failed or rejected
            # 2. Employee attended
            # 3. Not already paid
            # 4. Less than 3 retry attempts
            # 5. Last retry was more than 1 hour ago (if retried before)
            should_retry = (
                payment_status in ["FAILED", "REJECTED", "EXPIRED"] and
                attended and
                not paid and
                retry_attempts < 3
            )
            
            if should_retry:
                # Check if enough time has passed since last retry
                last_retry = details.get("last_retry_date")
                if last_retry:
                    try:
                        last_retry_time = datetime.strptime(last_retry, "%Y-%m-%d %H:%M:%S")
                        hours_since_retry = (datetime.now() - last_retry_time).total_seconds() / 3600
                        if hours_since_retry < 1:
                            continue  # Wait at least 1 hour between retries
                    except:
                        pass
                
                logger.info(f"Retrying payment for employee {key} (attempt {retry_attempts + 1}/3)")
                
                phone = details.get("phone")
                if not phone:
                    logger.warning(f"No phone for employee {key}")
                    continue
                
                clean_phone = ''.join(filter(str.isdigit, str(phone)))
                if len(clean_phone) < 9:
                    logger.warning(f"Invalid phone number {phone}")
                    continue
                
                formatted_phone = f"250{clean_phone[-9:]}"
                payout_id = str(uuid.uuid4())
                pay_amount = get_setting("payAmount", 100)
                
                payload = {
                    "payoutId": payout_id,
                    "amount": pay_amount,
                    "currency": "RWF",
                    "recipient": {
                        "type": "MMO",
                        "accountDetails": {
                            "phoneNumber": formatted_phone,
                            "provider": "MTN_MOMO_RWA"
                        }
                    }
                }
                
                try:
                    response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                    response_data = response.json()
                    
                    single_ref = db.reference(f"EMPLOYEES/{key}")
                    
                    if response.status_code in [200, 201, 202] and response_data.get("status") == "ACCEPTED":
                        single_ref.update({
                            "paid": False,
                            "payment_status": "PENDING",
                            "payment_retry_date": current_date,
                            "payment_amount": pay_amount,
                            "payoutId": payout_id,
                            "recipient_phone": formatted_phone,
                            "retry_attempts": retry_attempts + 1,
                            "last_retry_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        retry_count += 1
                        logger.info(f"✅ Payment retry initiated for employee {key}")
                    else:
                        single_ref.update({
                            "payment_status": response_data.get("status", "RETRY_FAILED"),
                            "payment_error": response_data.get("message", "Retry failed"),
                            "retry_attempts": retry_attempts + 1,
                            "last_retry_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        logger.error(f"❌ Payment retry failed for employee {key}")
                        
                except Exception as e:
                    logger.error(f"Error retrying payment for employee {key}: {e}")
                
                time.sleep(2)  # Delay between retries
        
        if retry_count > 0:
            logger.info(f"Retried {retry_count} failed payments")
        
    except Exception as e:
        logger.error(f"Error in retry_failed_payments: {e}")

def manual_payment_verification(employee_id):
    """
    Manually verify and fix a payment status
    This can be called from an admin endpoint
    """
    try:
        employee_ref = db.reference(f"EMPLOYEES/{employee_id}")
        employee = employee_ref.get()
        
        if not employee:
            return {"success": False, "message": "Employee not found"}
        
        payout_id = employee.get("payoutId")
        if not payout_id:
            return {"success": False, "message": "No payout ID found for this employee"}
        
        api_key = os.getenv("PAWAPAY_API_KEY")
        if not api_key:
            return {"success": False, "message": "API key not configured"}
        
        api_url = get_setting("pawapayApiUrl", "https://api.sandbox.pawapay.io/v2/payouts")
        headers = {"Authorization": f"Bearer {api_key}"}
        
        response = requests.get(f"{api_url}/{payout_id}", headers=headers, timeout=30)
        
        if response.status_code == 200:
            payout_data = response.json()
            status = payout_data.get("status")
            
            updates = {
                "payment_status": status,
                "last_manual_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if status == "COMPLETED":
                updates["paid"] = True
                updates["payment_confirmed_via"] = "manual_verification"
                message = "Payment confirmed successfully"
            elif status in ["FAILED", "REJECTED", "EXPIRED"]:
                updates["paid"] = False
                message = f"Payment failed with status: {status}"
            else:
                message = f"Payment status: {status}"
            
            employee_ref.update(updates)
            return {"success": True, "message": message, "status": status}
        else:
            return {"success": False, "message": f"API error: HTTP {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Manual verification error: {e}")
        return {"success": False, "message": str(e)}

# Add new background timer for payment status checking
def paymentStatusChecker():
    """Background thread to check pending payment statuses"""
    logger.info("Payment status checker thread started")
    
    while not shutdown_event.is_set():
        try:
            check_pending_payments()
            retry_failed_payments()
        except Exception as e:
            logger.error(f"Payment status checker error: {e}")
        
        # Wait before next check
        shutdown_event.wait(PAYMENT_STATUS_CHECK_INTERVAL)


# Startup logs
logger.info("Helper functions loaded - Settings will be loaded from Firebase")