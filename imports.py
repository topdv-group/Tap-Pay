# imports.py - Consolidated imports with file logging
import os
import sys
import time
import uuid
import logging
import threading
import signal
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, db
from waitress import serve

# Create logs directory if it doesn't exist
LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Configure logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler(os.path.join(LOG_DIR, 'system.log'), encoding='utf-8')  # File output
    ]
)
logger = logging.getLogger(__name__)

# Global shutdown event for graceful termination
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    logger.info("Shutdown signal received. Stopping services...")
    shutdown_event.set()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)