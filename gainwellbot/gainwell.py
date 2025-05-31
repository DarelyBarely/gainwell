
#!/usr/bin/env python3
"""
GainWell Telegram Bot - GCash Earning Platform
Complete bot in single file
"""

import os
import logging
import sqlite3
import threading
import re
import hashlib
import time
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, CallbackContext
)

# Bot Configuration
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM')
CHANNEL_USERNAME = '@gainwell'
BOT_USERNAME = '@gainwellbot'
ADMIN_ID = int(os.getenv('ADMIN_ID', '6495786170'))

# Database Configuration
DATABASE_NAME = 'bot_users.db'

# Reward Configuration
DAILY_REWARD_AMOUNT = 0.0053
REFERRAL_BONUS_PERCENTAGE = 0.10  # 10% of referral earnings
MINIMUM_WITHDRAWAL = 0.35
# SHORTLINK_REWARD_AMOUNT will be read from database settings

# Shortlink Configuration
OII_IO_API_KEY = "e853fb23f6fb9e60a950cd597c3b02663d62990e"
REWARD_WEBSITE_URL = "https://9ee9395e-a6cb-45b7-95e1-493300763cf1-00-1ofic7era7y5e.pike.replit.dev/reward.html"

# Conversation states
GCASH_NUMBER, UPDATE_GCASH, WITHDRAW_AMOUNT, WITHDRAW_CONFIRM = range(4)
# Admin conversation states removed - using web admin interface

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE CLASS
# =============================================================================

class Database:
    def __init__(self):
        self.lock = threading.Lock()
        self._init_database()

    def get_connection(self):
        """Get a thread-safe database connection"""
        return sqlite3.connect(DATABASE_NAME, check_same_thread=False)

    def _init_database(self):
        """Initialize database tables"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Create users table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                referrals INTEGER DEFAULT 0,
                referred_by INTEGER DEFAULT NULL,
                last_login TEXT,
                last_reward_claimed TEXT,
                gcash_number TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_banned INTEGER DEFAULT 0
            )
            ''')

            # Create transactions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                description TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create withdrawals table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                gcash_number TEXT,
                status TEXT DEFAULT 'pending',
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                admin_note TEXT,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create shortlink_clicks table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS shortlink_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                click_code TEXT UNIQUE,
                reward_claimed INTEGER DEFAULT 0,
                click_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create captcha_sessions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS captcha_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT UNIQUE,
                captchas_completed INTEGER DEFAULT 0,
                total_captchas INTEGER DEFAULT 10,
                reward_per_captcha REAL DEFAULT 0.0671,
                session_completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_captcha_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create captcha_links table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS captcha_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                link_number INTEGER,
                captcha_code TEXT UNIQUE,
                completed INTEGER DEFAULT 0,
                completed_at TEXT,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (session_id) REFERENCES captcha_sessions (session_id)
            )
            ''')

            # Create watch_ads table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS watch_ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ad_code TEXT UNIQUE,
                reward_claimed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                claimed_at TEXT,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create user_notifications table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id INTEGER PRIMARY KEY,
                daily_reward INTEGER DEFAULT 1,
                shortlink INTEGER DEFAULT 1,
                captcha INTEGER DEFAULT 1,
                watch_ads INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Create settings table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            ''')

            # Insert default settings if they don't exist
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('shortlink_reward_amount', '0.0724')
            ''')

            cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('reward_page_url', 'https://example.com')
    ''')

            cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('captcha_reward_amount', '0.0671')
    ''')

            cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('captcha_page_url', 'https://example.com')
    ''')

            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('watch_ads_reward_amount', '0.0532')
            ''')

            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('watch_ads_page_url', 'https://example.com')
            ''')

            conn.commit()
            conn.close()

    def add_user(self, user_id, username, first_name, referred_by=None):
        """Add new user to database"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
                if cursor.fetchone():
                    return False  # User already exists

                cursor.execute(
                    """INSERT INTO users (user_id, username, first_name, referred_by, last_login, last_reward_claimed) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, username, first_name, referred_by, datetime.now().isoformat(), None)
                )

                # Track referral but don't give immediate bonus (percentage-based system)
                if referred_by:
                    cursor.execute(
                        "UPDATE users SET referrals = referrals + 1 WHERE user_id=?",
                        (referred_by,)
                    )

                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding user: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def get_user(self, user_id):
        """Get user data"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
                result = cursor.fetchone()
                return result
            except Exception as e:
                logger.error(f"Error getting user: {e}")
                return None
            finally:
                conn.close()

    def update_user_balance(self, user_id, amount, transaction_type, description=""):
        """Update user balance and log transaction"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id=?",
                    (amount, user_id)
                )
                self._log_transaction(cursor, user_id, transaction_type, amount, description)

                # Give referral bonus if this is an earning transaction
                if transaction_type in ['daily_reward', 'shortlink_reward']:
                    cursor.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
                    referrer_result = cursor.fetchone()
                    if referrer_result and referrer_result[0]:
                        referrer_id = referrer_result[0]
                        referral_bonus = amount * REFERRAL_BONUS_PERCENTAGE
                        cursor.execute(
                            "UPDATE users SET balance = balance + ? WHERE user_id=?",
                            (referral_bonus, referrer_id)
                        )
                        self._log_transaction(cursor, referrer_id, "referral_bonus", referral_bonus, f"10% referral bonus from user {user_id}")

                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating balance: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def update_gcash_number(self, user_id, gcash_number):
        """Update user's GCash number"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "UPDATE users SET gcash_number = ? WHERE user_id=?",
                    (gcash_number, user_id)
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating GCash number: {e}")
                return False
            finally:
                conn.close()

    def update_last_reward_claimed(self, user_id):
        """Update when user last claimed daily reward"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "UPDATE users SET last_reward_claimed = ? WHERE user_id=?",
                    (datetime.now().isoformat(), user_id)
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating last reward claimed: {e}")
                return False
            finally:
                conn.close()

    def get_user_transactions(self, user_id, limit=10):
        """Get user transaction history"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """SELECT type, amount, description, timestamp 
                       FROM transactions WHERE user_id=? 
                       ORDER BY timestamp DESC LIMIT ?""",
                    (user_id, limit)
                )
                return cursor.fetchall()
            except Exception as e:
                logger.error(f"Error getting transactions: {e}")
                return []
            finally:
                conn.close()

    def get_user_withdrawals(self, user_id, limit=10):
        """Get user withdrawal history"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """SELECT id, amount, gcash_number, status, timestamp 
                       FROM withdrawals WHERE user_id=? 
                       ORDER BY timestamp DESC LIMIT ?""",
                    (user_id, limit)
                )
                return cursor.fetchall()
            except Exception as e:
                logger.error(f"Error getting withdrawals: {e}")
                return []
            finally:
                conn.close()

    def create_withdrawal_request(self, user_id, amount, gcash_number):
        """Create a withdrawal request"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # Deduct amount from balance
                cursor.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id=?",
                    (amount, user_id)
                )

                # Create withdrawal request
                cursor.execute(
                    """INSERT INTO withdrawals (user_id, amount, gcash_number) 
                       VALUES (?, ?, ?)""",
                    (user_id, amount, gcash_number)
                )

                # Log transaction
                self._log_transaction(cursor, user_id, "withdrawal_request", -amount, f"Withdrawal request to {gcash_number}")

                withdrawal_id = cursor.lastrowid
                conn.commit()
                return withdrawal_id
            except Exception as e:
                logger.error(f"Error creating withdrawal request: {e}")
                conn.rollback()
                return None
            finally:
                conn.close()

    def get_pending_withdrawals(self):
        """Get all pending withdrawal requests"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """SELECT w.id, w.user_id, u.username, w.amount, w.gcash_number, w.timestamp
                       FROM withdrawals w
                       JOIN users u ON w.user_id = u.user_id
                       WHERE w.status = 'pending'
                       ORDER BY w.timestamp ASC"""
                )
                return cursor.fetchall()
            except Exception as e:
                logger.error(f"Error getting pending withdrawals: {e}")
                return []
            finally:
                conn.close()

    def approve_withdrawal(self, withdrawal_id, admin_note=""):
        """Approve a withdrawal request"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """UPDATE withdrawals 
                       SET status = 'approved', admin_note = ?, completed_at = ?
                       WHERE id = ?""",
                    (admin_note, datetime.now().isoformat(), withdrawal_id)
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error approving withdrawal: {e}")
                return False
            finally:
                conn.close()

    def reject_withdrawal(self, withdrawal_id, admin_note=""):
        """Reject a withdrawal request and refund balance"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # Get withdrawal details
                cursor.execute("SELECT user_id, amount FROM withdrawals WHERE id = ?", (withdrawal_id,))
                result = cursor.fetchone()
                if not result:
                    return False

                user_id, amount = result

                # Refund balance
                cursor.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (amount, user_id)
                )

                # Update withdrawal status
                cursor.execute(
                    """UPDATE withdrawals 
                       SET status = 'rejected', admin_note = ?, completed_at = ?
                       WHERE id = ?""",
                    (admin_note, datetime.now().isoformat(), withdrawal_id)
                )

                # Log refund transaction
                self._log_transaction(cursor, user_id, "withdrawal_refund", amount, "Withdrawal rejected - refund")

                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error rejecting withdrawal: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def get_all_users(self):
        """Get all users for admin panel"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """SELECT user_id, username, first_name, balance, referrals, created_at, is_banned
                       FROM users ORDER BY created_at DESC"""
                )
                return cursor.fetchall()
            except Exception as e:
                logger.error(f"Error getting all users: {e}")
                return []
            finally:
                conn.close()

    def ban_user(self, user_id):
        """Ban a user"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error banning user: {e}")
                return False
            finally:
                conn.close()

    def unban_user(self, user_id):
        """Unban a user"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error unbanning user: {e}")
                return False
            finally:
                conn.close()

    def create_shortlink_code(self, user_id):
        """Create a unique shortlink code for user"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # Generate unique code using user_id and timestamp
                timestamp = str(int(time.time()))
                raw_code = f"{user_id}_{timestamp}_{hashlib.md5(str(user_id + int(timestamp)).encode()).hexdigest()[:8]}"
                click_code = hashlib.sha256(raw_code.encode()).hexdigest()[:16]

                # Store in database
                cursor.execute(
                    "INSERT INTO shortlink_clicks (user_id, click_code) VALUES (?, ?)",
                    (user_id, click_code)
                )
                conn.commit()
                return click_code
            except Exception as e:
                logger.error(f"Error creating shortlink code: {e}")
                return None
            finally:
                conn.close()

    def claim_shortlink_reward(self, click_code, ip_address=None, user_agent=None):
        """Claim shortlink reward if valid and not already claimed"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # Check if code exists and not claimed
                cursor.execute(
                    "SELECT user_id, reward_claimed FROM shortlink_clicks WHERE click_code = ?",
                    (click_code,)
                )
                result = cursor.fetchone()

                if not result:
                    return {"success": False, "title": "Invalid Link", "message": "This reward link is invalid or expired."}

                user_id, reward_claimed = result

                if reward_claimed:
                    return {"success": False, "title": "Already Claimed", "message": "You have already claimed this reward."}

                # Mark as claimed
                cursor.execute(
                    "UPDATE shortlink_clicks SET reward_claimed = 1, ip_address = ?, user_agent = ? WHERE click_code = ?",
                    (ip_address, user_agent, click_code)
                )

                # Get current shortlink reward amount
                shortlink_reward = get_shortlink_reward_amount()

                # Add reward to user balance
                cursor.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (shortlink_reward, user_id)
                )

                # Log transaction
                self._log_transaction(cursor, user_id, "shortlink_reward", shortlink_reward, "Shortlink click reward")

                conn.commit()
                return {"success": True, "amount": shortlink_reward}

            except Exception as e:
                logger.error(f"Error claiming shortlink reward: {e}")
                conn.rollback()
                return {"success": False, "title": "Error", "message": "Unable to process reward. Please try again."}
            finally:
                conn.close()

    def get_user_notifications(self, user_id):
        """Get user notification preferences"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT daily_reward, shortlink, captcha, watch_ads FROM user_notifications WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                
                if not result:
                    # Create default preferences if they don't exist
                    cursor.execute(
                        "INSERT INTO user_notifications (user_id, daily_reward, shortlink, captcha, watch_ads) VALUES (?, 1, 1, 1, 1)",
                        (user_id,)
                    )
                    conn.commit()
                    return (1, 1, 1, 1)  # Default: all notifications enabled
                
                return result
            except Exception as e:
                logger.error(f"Error getting user notifications: {e}")
                return (1, 1, 1, 1)  # Default: all notifications enabled
            finally:
                conn.close()

    def update_user_notification(self, user_id, notification_type, enabled):
        """Update specific notification preference"""
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # Ensure user has notification preferences record
                cursor.execute("SELECT user_id FROM user_notifications WHERE user_id = ?", (user_id,))
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO user_notifications (user_id, daily_reward, shortlink, captcha, watch_ads) VALUES (?, 1, 1, 1, 1)",
                        (user_id,)
                    )

                # Update the specific notification type
                cursor.execute(
                    f"UPDATE user_notifications SET {notification_type} = ? WHERE user_id = ?",
                    (1 if enabled else 0, user_id)
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating user notification: {e}")
                return False
            finally:
                conn.close()

    def _log_transaction(self, cursor, user_id, trans_type, amount, description):
        """Internal method to log transaction (requires existing cursor)"""
        cursor.execute(
            """INSERT INTO transactions (user_id, type, amount, description) 
               VALUES (?, ?, ?, ?)""",
            (user_id, trans_type, amount, description)
        )

# Global database instance
db = Database()

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def validate_gcash_number(number):
    """Validate GCash number format (11 digits starting with 09)"""
    if not number:
        return False

    # Remove any spaces or special characters
    clean_number = re.sub(r'[^\d]', '', number)

    # Check if it's exactly 11 digits and starts with 09
    pattern = re.compile(r'^09\d{9}$')
    return bool(pattern.match(clean_number))

def format_gcash_number(number):
    """Format GCash number for display"""
    if not number:
        return ""

    clean_number = re.sub(r'[^\d]', '', number)
    if len(clean_number) == 11:
        return f"{clean_number[:4]}{clean_number[4:7]}{clean_number[7:]}"
    return clean_number

def parse_amount(amount_text, balance):
    """Parse amount from text input, handling shortcuts like 'Min' and 'Max'"""
    if not amount_text:
        return None

    try:
        # Check for Min/Max shortcuts
        if amount_text.lower() == 'min':
            return MINIMUM_WITHDRAWAL
        elif amount_text.lower() == 'max':
            return float(balance)

        # Try to parse as number
        amount = float(amount_text.replace('₱', '').replace(',', '').strip())
        return amount
    except ValueError:
        return None

def format_currency(amount):
    """Format amount with proper currency symbols"""
    if amount == 0:
        return "₱0"
    elif amount == int(amount):
        return f"₱{int(amount)}"
    else:
        return f"₱{amount:.4f}".rstrip('0').rstrip('.')

def can_claim_daily_reward(last_claimed_str):
    """Check if user can claim daily reward"""
    if not last_claimed_str:
        return True

    try:
        last_claimed = datetime.fromisoformat(last_claimed_str)
        time_since_last = datetime.now() - last_claimed
        return time_since_last.total_seconds() >= 24 * 3600  # 24 hours
    except:
        return True

def can_generate_shortlink(user_id):
    """Check if user can generate a new shortlink (24-hour cooldown or has unused link)"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # First check if user has an unused shortlink
            cursor.execute(
                "SELECT click_code FROM shortlink_clicks WHERE user_id = ? AND reward_claimed = 0 ORDER BY click_timestamp DESC LIMIT 1",
                (user_id,)
            )
            unused_link = cursor.fetchone()

            if unused_link:
                return False  # User has an unused shortlink

            # Check 24-hour cooldown from last used/accessed shortlink
            cursor.execute(
                "SELECT click_timestamp FROM shortlink_clicks WHERE user_id = ? AND reward_claimed = 1 ORDER BY click_timestamp DESC LIMIT 1",
                (user_id,)
            )
            result = cursor.fetchone()

            if not result:
                return True  # No previous used shortlinks

            last_used = datetime.fromisoformat(result[0])
            time_since_last = datetime.now() - last_used
            return time_since_last.total_seconds() >= 24 * 3600  # 24 hours
        except:
            return True
        finally:
            conn.close()

def calculate_time_until_next_reward(last_claimed_str):
    """Calculate time until next daily reward can be claimed"""
    if not last_claimed_str:
        return "Available now!"

    try:
        last_claimed_time = datetime.fromisoformat(last_claimed_str)
        next_claim_time = last_claimed_time + timedelta(days=1)
        time_remaining = next_claim_time - datetime.now()

        if time_remaining.total_seconds() <= 0:
            return "Available now!"

        # Format time as HH:MM:SS
        total_seconds = int(time_remaining.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}H {minutes}M {seconds}s"
    except:
        return "Available now!"

def is_valid_withdrawal_amount(amount, balance, min_amount=MINIMUM_WITHDRAWAL):
    """Validate withdrawal amount"""
    if amount is None:
        return False, "Invalid amount format"

    if amount < min_amount:
        return False, f"Minimum withdrawal is {format_currency(min_amount)}"

    if amount > balance:
        return False, "Insufficient balance"

    return True, ""

async def is_user_in_channel(user_id, context):
    """Check if user is a member of the required channel"""
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership for user {user_id}: {e}")
        return False

def send_message_to_user(context, user_id, message, parse_mode=None, reply_markup=None):
    """Send a message to a specific user"""
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
        return False

def check_user_banned(user_data):
    """Check if user is banned"""
    if not user_data:
        return False
    return bool(user_data[10])  # is_banned field

def is_admin(user_id):
    """Check if user is admin"""
    return user_id == ADMIN_ID

def get_shortlink_reward_amount():
    """Get shortlink reward amount from settings database"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'shortlink_reward_amount'")
        result = cursor.fetchone()

        if result:
            amount = float(result[0])
            logger.info(f"Retrieved shortlink reward amount from database: {amount}")
            return amount
        else:
            # Return default amount if not set
            logger.warning("Shortlink reward amount not found in settings, using default")
            return 0.0724
    except Exception as e:
        logger.error(f"Error getting shortlink reward amount from settings: {e}")
        # Return default amount on error
        return 0.0724
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_reward_url_from_settings():
    """Get reward page URL from settings database"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'reward_page_url'")
        result = cursor.fetchone()

        if result:
            return result[0]
        else:
            # Return default URL if not set
            return "https://example.com"
    except Exception as e:
        logger.error(f"Error getting reward URL from settings: {e}")
        # Return default URL on error
        return "https://example.com"
    finally:
        try:
            conn.close()
        except:
            pass

def get_captcha_reward_amount():
    """Get captcha reward amount from settings database"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'captcha_reward_amount'")
        result = cursor.fetchone()

        if result:
            amount = float(result[0])
            logger.info(f"Retrieved captcha reward amount from database: {amount}")
            return amount
        else:
            # Return default amount if not set
            logger.warning("Captcha reward amount not found in settings, using default")
            return 0.0671
    except Exception as e:
        logger.error(f"Error getting captcha reward amount from settings: {e}")
        # Return default amount on error
        return 0.0671
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_captcha_url_from_settings():
    """Get captcha page URL from settings database"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'captcha_page_url'")
        result = cursor.fetchone()

        if result:
            return result[0]
        else:
            # Return default URL if not set
            return "https://example.com"
    except Exception as e:
        logger.error(f"Error getting captcha URL from settings: {e}")
        # Return default URL on error
        return "https://example.com"
    finally:
        try:
            conn.close()
        except:
            pass

def can_generate_captcha_session(user_id):
    """Check if user can generate a new captcha session (24-hour cooldown)"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # Check if user has an active/incomplete session
            cursor.execute(
                "SELECT session_id FROM captcha_sessions WHERE user_id = ? AND session_completed = 0 ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
            active_session = cursor.fetchone()

            if active_session:
                return False  # User has an active session

            # Check 24-hour cooldown from last completed session
            cursor.execute(
                "SELECT last_captcha_at FROM captcha_sessions WHERE user_id = ? AND session_completed = 1 ORDER BY last_captcha_at DESC LIMIT 1",
                (user_id,)
            )
            result = cursor.fetchone()

            if not result:
                return True  # No previous completed sessions

            last_completed = datetime.fromisoformat(result[0])
            time_since_last = datetime.now() - last_completed
            return time_since_last.total_seconds() >= 24 * 3600  # 24 hours
        except:
            return True
        finally:
            conn.close()

def create_captcha_session(user_id):
    """Create a new captcha session with 10 captcha links"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # Generate unique session ID
            timestamp = str(int(time.time()))
            raw_session = f"{user_id}_{timestamp}_captcha"
            session_id = hashlib.sha256(raw_session.encode()).hexdigest()[:24]

            # Get current captcha reward amount
            captcha_reward = get_captcha_reward_amount()

            # Create captcha session
            cursor.execute(
                "INSERT INTO captcha_sessions (user_id, session_id, total_captchas, reward_per_captcha) VALUES (?, ?, ?, ?)",
                (user_id, session_id, 10, captcha_reward)
            )

            # Create 10 captcha links
            captcha_links = []
            for i in range(1, 11):
                # Generate unique captcha code
                raw_code = f"{session_id}_{i}_{timestamp}"
                captcha_code = hashlib.sha256(raw_code.encode()).hexdigest()[:16]

                cursor.execute(
                    "INSERT INTO captcha_links (session_id, link_number, captcha_code) VALUES (?, ?, ?)",
                    (session_id, i, captcha_code)
                )

                captcha_links.append({
                    'number': i,
                    'code': captcha_code
                })

            conn.commit()
            return session_id, captcha_links
        except Exception as e:
            logger.error(f"Error creating captcha session: {e}")
            conn.rollback()
            return None, None
        finally:
            conn.close()

def get_active_captcha_session(user_id):
    """Get user's active captcha session if any"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """SELECT cs.session_id, cs.captchas_completed, cs.total_captchas, cs.reward_per_captcha
                   FROM captcha_sessions cs 
                   WHERE cs.user_id = ? AND cs.session_completed = 0 
                   ORDER BY cs.created_at DESC LIMIT 1""",
                (user_id,)
            )
            session = cursor.fetchone()

            if not session:
                return None

            session_id, completed, total, reward = session

            # Get remaining captcha links
            cursor.execute(
                """SELECT link_number, captcha_code FROM captcha_links 
                   WHERE session_id = ? AND completed = 0 
                   ORDER BY link_number""",
                (session_id,)
            )
            remaining_links = cursor.fetchall()

            return {
                'session_id': session_id,
                'completed': completed,
                'total': total,
                'reward_per_captcha': reward,
                'remaining_links': remaining_links
            }
        except Exception as e:
            logger.error(f"Error getting active captcha session: {e}")
            return None
        finally:
            conn.close()

def can_generate_watch_ads(user_id):
    """Check if user can generate a new watch ads link (1-hour cooldown)"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # First check if user has an unused watch ads link
            cursor.execute(
                "SELECT ad_code FROM watch_ads WHERE user_id = ? AND reward_claimed = 0 ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
            unused_link = cursor.fetchone()

            if unused_link:
                return False  # User has an unused watch ads link

            # Check 1-hour cooldown from last claimed watch ads
            cursor.execute(
                "SELECT claimed_at FROM watch_ads WHERE user_id = ? AND reward_claimed = 1 ORDER BY claimed_at DESC LIMIT 1",
                (user_id,)
            )
            result = cursor.fetchone()

            if not result:
                return True  # No previous claimed watch ads

            last_claimed = datetime.fromisoformat(result[0])
            time_since_last = datetime.now() - last_claimed
            return time_since_last.total_seconds() >= 3600  # 1 hour
        except:
            return True
        finally:
            conn.close()

def create_watch_ads_code(user_id):
    """Create a unique watch ads code for user"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # Generate unique code using user_id and timestamp
            timestamp = str(int(time.time()))
            raw_code = f"{user_id}_{timestamp}_ads_{hashlib.md5(str(user_id + int(timestamp)).encode()).hexdigest()[:8]}"
            ad_code = hashlib.sha256(raw_code.encode()).hexdigest()[:16]

            # Store in database
            cursor.execute(
                "INSERT INTO watch_ads (user_id, ad_code) VALUES (?, ?)",
                (user_id, ad_code)
            )
            conn.commit()
            return ad_code
        except Exception as e:
            logger.error(f"Error creating watch ads code: {e}")
            return None
        finally:
            conn.close()

def get_watch_ads_reward_amount():
    """Get watch ads reward amount from settings database"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'watch_ads_reward_amount'")
        result = cursor.fetchone()

        if result:
            amount = float(result[0])
            logger.info(f"Retrieved watch ads reward amount from database: {amount}")
            return amount
        else:
            logger.warning("Watch ads reward amount not found in settings, using default")
            return 0.0532
    except Exception as e:
        logger.error(f"Error getting watch ads reward amount from settings: {e}")
        return 0.0532
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_watch_ads_url_from_settings():
    """Get watch ads page URL from settings database"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM settings WHERE key = 'watch_ads_page_url'")
        result = cursor.fetchone()

        if result:
            return result[0]
        else:
            return "https://example.com"
    except Exception as e:
        logger.error(f"Error getting watch ads URL from settings: {e}")
        return "https://example.com"
    finally:
        try:
            conn.close()
        except:
            pass

def calculate_time_until_next_watch_ads(user_id):
    """Calculate time until next watch ads can be generated"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT claimed_at FROM watch_ads WHERE user_id = ? AND reward_claimed = 1 ORDER BY claimed_at DESC LIMIT 1",
                (user_id,)
            )
            result = cursor.fetchone()

            if not result:
                return "Available now!"

            last_claimed_time = datetime.fromisoformat(result[0])
            next_claim_time = last_claimed_time + timedelta(hours=1)
            time_remaining = next_claim_time - datetime.now()

            if time_remaining.total_seconds() <= 0:
                return "Available now!"

            # Format time as HH:MM:SS
            total_seconds = int(time_remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}H {minutes}M {seconds}s"
        except:
            return "Available now!"
        finally:
            conn.close()

def send_notification_to_user(user_id, message):
    """Send notification message to user"""
    try:
        import requests
        
        bot_token = TOKEN
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error sending notification to user {user_id}: {e}")
        return False

def check_and_send_notifications():
    """Check all users for available tasks and send notifications"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all active users with their notification preferences
        cursor.execute("""
            SELECT u.user_id, u.first_name, u.last_reward_claimed,
                   COALESCE(n.daily_reward, 1) as daily_notif,
                   COALESCE(n.shortlink, 1) as shortlink_notif,
                   COALESCE(n.captcha, 1) as captcha_notif,
                   COALESCE(n.watch_ads, 1) as ads_notif
            FROM users u
            LEFT JOIN user_notifications n ON u.user_id = n.user_id
            WHERE u.is_banned = 0
        """)
        
        users = cursor.fetchall()
        conn.close()
        
        for user in users:
            user_id, first_name, last_reward_claimed, daily_notif, shortlink_notif, captcha_notif, ads_notif = user
            
            notifications = []
            
            # Check daily reward
            if daily_notif and can_claim_daily_reward(last_reward_claimed):
                notifications.append("🎁 Daily Reward is ready!")
            
            # Check shortlink
            if shortlink_notif and can_generate_shortlink(user_id):
                notifications.append("🔗 New Shortlink is available!")
            
            # Check captcha
            if captcha_notif and can_generate_captcha_session(user_id):
                notifications.append("🛡️ New Captcha Session is available!")
            
            # Check watch ads
            if ads_notif and can_generate_watch_ads(user_id):
                notifications.append("👁️ New Watch Ads is available!")
            
            # Send notification if there are any available tasks
            if notifications:
                message = f"🔔 *Task Notifications*\n\nHi {first_name}!\n\n" + "\n".join(notifications)
                message += f"\n\nOpen the bot to claim your rewards!"
                send_notification_to_user(user_id, message)
                
    except Exception as e:
        logger.error(f"Error in notification scheduler: {e}")

def complete_captcha_link(captcha_code, ip_address=None, user_agent=None):
    """Complete a captcha link and award reward if valid"""
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            # Check if captcha code exists and not completed
            cursor.execute(
                """SELECT cl.session_id, cl.link_number, cl.completed, cs.user_id, cs.reward_per_captcha
                   FROM captcha_links cl
                   JOIN captcha_sessions cs ON cl.session_id = cs.session_id
                   WHERE cl.captcha_code = ?""",
                (captcha_code,)
            )
            result = cursor.fetchone()

            if not result:
                return {"success": False, "title": "Invalid Link", "message": "This captcha link is invalid or expired."}

            session_id, link_number, completed, user_id, reward_amount = result

            if completed:
                return {"success": False, "title": "Already Completed", "message": "You have already completed this captcha."}

            # Mark captcha as completed
            cursor.execute(
                "UPDATE captcha_links SET completed = 1, completed_at = ?, ip_address = ?, user_agent = ? WHERE captcha_code = ?",
                (datetime.now().isoformat(), ip_address, user_agent, captcha_code)
            )

            # Update session progress
            cursor.execute(
                "UPDATE captcha_sessions SET captchas_completed = captchas_completed + 1, last_captcha_at = ? WHERE session_id = ?",
                (datetime.now().isoformat(), session_id)
            )

            # Add reward to user balance
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (reward_amount, user_id)
            )

            # Log transaction
            cursor.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                (user_id, 'captcha_reward', reward_amount, f'Captcha {link_number}/10 completed')
            )

            # Check if session is completed (all 10 captchas done)
            cursor.execute(
                "SELECT captchas_completed FROM captcha_sessions WHERE session_id = ?",
                (session_id,)
            )
            completed_count = cursor.fetchone()[0]

            if completed_count >= 10:
                cursor.execute(
                    "UPDATE captcha_sessions SET session_completed = 1 WHERE session_id = ?",
                    (session_id,)
                )

            conn.commit()
            return {
                "success": True, 
                "amount": reward_amount,
                "captcha_number": link_number,
                "completed_count": completed_count,
                "total_captchas": 10,
                "session_completed": completed_count >= 10
            }

        except Exception as e:
            logger.error(f"Error completing captcha: {e}")
            conn.rollback()
            return {"success": False, "title": "Error", "message": "Unable to process captcha. Please try again."}
        finally:
            conn.close()

def generate_shortlink_from_code(click_code):
    """Generate a shortened URL from existing click code"""
    try:
        # Get reward URL from settings
        reward_url = get_reward_url_from_settings()

        # Create full tracking URL pointing to the reward page
        tracking_url = f"{reward_url}?code={click_code}"

        # URL encode the tracking URL for the API
        import urllib.parse
        encoded_url = urllib.parse.quote(tracking_url, safe='')

        # Use the correct Oii.io API endpoint with JSON response
        api_url = f"https://oii.io/api?api={OII_IO_API_KEY}&url={encoded_url}"

        response = requests.get(api_url, timeout=15)

        if response.status_code == 200:
            try:
                # Parse JSON response
                result = response.json()

                if result.get('status') == 'success':
                    shortened_url = result.get('shortenedUrl')
                    if shortened_url:
                        return shortened_url
                    else:
                        return tracking_url
                else:
                    return tracking_url

            except ValueError:
                return tracking_url
            except Exception:
                return tracking_url
        else:
            return tracking_url

    except Exception:
        return None

def generate_shortlink(user_id):
    """Generate a shortened URL using Oii.io API"""
    try:
        # Create tracking code
        click_code = db.create_shortlink_code(user_id)
        if not click_code:
            logger.error("Failed to create tracking code")
            return None

        # Get reward URL from settings
        reward_url = get_reward_url_from_settings()

        # Create full tracking URL pointing to the reward page
        tracking_url = f"{reward_url}?code={click_code}"
        logger.info(f"Created tracking URL: {tracking_url}")

        # URL encode the tracking URL for the API
        import urllib.parse
        encoded_url = urllib.parse.quote(tracking_url, safe='')

        # Use the correct Oii.io API endpoint with JSON response
        api_url = f"https://oii.io/api?api={OII_IO_API_KEY}&url={encoded_url}"

        logger.info(f"Calling Oii.io API: {api_url}")
        response = requests.get(api_url, timeout=15)

        logger.info(f"API Response Status: {response.status_code}")
        logger.info(f"API Response Text: {response.text}")

        if response.status_code == 200:
            try:
                # Parse JSON response
                result = response.json()
                logger.info(f"API JSON Response: {result}")

                if result.get('status') == 'success':
                    shortened_url = result.get('shortenedUrl')
                    if shortened_url:
                        logger.info(f"Successfully shortened URL: {shortened_url}")
                        return shortened_url
                    else:
                        logger.error("API returned success but no shortened URL")
                        return tracking_url
                else:
                    error_message = result.get('message', 'Unknown error')
                    logger.error(f"API returned error status: {error_message}")
                    return tracking_url

            except ValueError as json_error:
                logger.error(f"Failed to parse JSON response: {json_error}")
                logger.error(f"Raw response: {response.text}")
                return tracking_url
            except Exception as e:
                logger.error(f"Unexpected error parsing API response: {e}")
                return tracking_url
        else:
            logger.error(f"API request failed with status {response.status_code}: {response.text}")
            return tracking_url

    except requests.exceptions.Timeout:
        logger.error("API request timeout")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating shortlink: {e}")
        return None

# =============================================================================
# KEYBOARD FUNCTIONS
# =============================================================================

def main_menu_keyboard(is_admin=False):
    """Main menu keyboard"""
    keyboard = [
        ["❇️ Gain ₱eso"],
        ["💰 Balance", "💸 Withdraw", "📨 Invite"],
        ["📊 History", "⚙️ Settings"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def not_joined_reply_keyboard():
    """Keyboard for users who haven't joined the channel"""
    keyboard = [["✅ Done"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def settings_keyboard():
    """Settings menu keyboard"""
    keyboard = [
        ["📱 Update GCash Number"],
        ["🔔 Notifications"],
        ["↩️ Back to Menu"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def cancel_keyboard():
    """Cancel action keyboard"""
    keyboard = [["❌ Cancel"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_withdraw_amount_keyboard():
    """Withdrawal amount selection keyboard"""
    keyboard = [
        ["Min", "Max"],
        ["❌ Cancel"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_share_button(referral_link):
    """Share button for referral link"""
    share_message = f"Join Gain Well and earn money! Use my referral link: {referral_link}"
    keyboard = [
        [InlineKeyboardButton("📢 Share", switch_inline_query=share_message)]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirmation_keyboard():
    """Confirmation keyboard for critical actions"""
    keyboard = [
        ["✅ Confirm", "❌ Cancel"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_task_menu_buttons(last_reward_claimed, user_id):
    """Task menu with dynamic daily reward, static shortlink, captcha, and watch ads buttons"""
    can_claim = can_claim_daily_reward(last_reward_claimed)

    if can_claim:
        daily_button_text = "🎁 Daily Reward"
        daily_callback = "daily_reward"
    else:
        time_until_reward = calculate_time_until_next_reward(last_reward_claimed)
        daily_button_text = f"🎁 {time_until_reward}"
        daily_callback = "daily_claimed"

    # Always show watch ads button without countdown (like shortlink)
    watch_ads_button_text = "👁️ Watch Ads"
    watch_ads_callback = "watch_ads"

    # Always show shortlink button without countdown
    shortlink_button_text = "🔗 Shortlink"
    shortlink_callback = "generate_shortlink"

    # Always show captcha button without countdown (like shortlink)
    captcha_button_text = "🛡️ Solve Captcha"
    captcha_callback = "solve_captcha"

    keyboard = [
        [InlineKeyboardButton(daily_button_text, callback_data=daily_callback)],
        [
            InlineKeyboardButton(shortlink_button_text, callback_data=shortlink_callback),
            InlineKeyboardButton(captcha_button_text, callback_data=captcha_callback)
        ],
        [InlineKeyboardButton(watch_ads_button_text, callback_data=watch_ads_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)

# =============================================================================
# BASIC HANDLERS
# =============================================================================

async def start(update: Update, context: CallbackContext):
    """Handle /start command"""
    user = update.effective_user
    referrer_id = None

    # Extract referrer ID from command arguments
    if context.args and len(context.args) > 0:
        try:
            referrer_id = int(context.args[0])
        except ValueError:
            pass

    # Add user to database
    db.add_user(user.id, user.username, user.first_name, referred_by=referrer_id)

    # Check channel membership
    if await is_user_in_channel(user.id, context):
        is_admin_user = is_admin(user.id)
        welcome_text = (
            f"👋 Welcome back, {user.first_name}!\n\n"
            f"💰 Earn GCash by completing tasks.\n"
            f"🎁 Claim daily rewards\n"
            f"👥 Invite friends for bonuses\n\n"
            f"Choose an option below:"
        )
        await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(is_admin_user))
    else:
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())

async def check_balance(update: Update, context: CallbackContext):
    """Show user balance and account summary"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    if user_data:
        balance = user_data[3]  # balance field
        referrals = user_data[4]  # referrals field
        gcash_number = user_data[8]  # gcash_number field

        gcash_status = "✅ Set" if gcash_number else "❌ Not set"

        await update.message.reply_text(
            f"💰 *Your Account Summary*\n\n"
            f"Balance: {format_currency(balance)}\n"
            f"Referrals: {referrals} friends\n"
            f"GCash Number: {gcash_status}\n\n"
            f"Minimum withdrawal: {format_currency(MINIMUM_WITHDRAWAL)}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")

async def invite_friends(update: Update, context: CallbackContext):
    """Show referral information and link"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")
        return

    referral_link = f"https://t.me/{BOT_USERNAME.replace('@', '')}?start={user_id}"
    referrals = user_data[4]  # referrals field

    message = (
        f"📱 *Invite Friends & Earn*\n\n"
        f"Share your referral link with friends!\n"
        f"You earn 10% of all your referrals' earnings.\n\n"
        f"Your Referrals: {referrals}\n\n"
        f"Your Referral Link:\n`{referral_link}`\n\n"
        f"Copy the link above and share it with your friends!"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=get_share_button(referral_link)
    )

async def check_history(update: Update, context: CallbackContext):
    """Show user withdrawal transaction history"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    # Get withdrawal history - show only 2 most recent
    withdrawals = db.get_user_withdrawals(user_id, limit=2)

    if not withdrawals:
        await update.message.reply_text("📊 You don't have any withdrawal history yet.")
        return

    message = "📊 *Recent Withdrawals*\n\n"

    for withdrawal in withdrawals:
        withdrawal_id, amount, gcash_number, status, timestamp = withdrawal

        # Format timestamp
        try:
            trans_time = datetime.fromisoformat(timestamp).strftime("%m/%d %H:%M")
        except:
            trans_time = "Unknown"

        # Format status with emoji
        if status == "pending":
            status_emoji = "⏳ Pending"
        elif status == "approved":
            status_emoji = "✅ Success"
        elif status == "rejected":
            status_emoji = "❌ Rejected"
        else:
            status_emoji = f"📋 {status.title()}"

        message += f"💸 **Withdrawal**\n"
        message += f"Amount: {format_currency(amount)}\n"
        message += f"GCash: {format_gcash_number(gcash_number)}\n"
        message += f"Status: {status_emoji}\n"
        message += f"Date: {trans_time}\n\n"

    # Check if user has more withdrawals
    all_withdrawals = db.get_user_withdrawals(user_id, limit=100)
    has_more = len(all_withdrawals) > 2

    keyboard = []
    if has_more:
        keyboard.append([InlineKeyboardButton("📋 View More", callback_data="view_more_history")])

    if keyboard:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

async def done_button(update: Update, context: CallbackContext):
    """Handle 'Done' button after user claims to have joined channel"""
    user_id = update.effective_user.id

    if await is_user_in_channel(user_id, context):
        is_admin_user = is_admin(user_id)
        welcome_text = (
            f"✅ Great! You've joined the channel.\n\n"
            f"💰 Now you can start earning GCash!\n"
            f"Choose an option below:"
        )
        await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(is_admin_user))
    else:
        message = f"❌ You haven't joined the channel yet.\nPlease join {CHANNEL_USERNAME} first, then click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())

# =============================================================================
# TASK HANDLERS
# =============================================================================

async def gain_peso(update: Update, context: CallbackContext):
    """Show earning tasks menu"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")
        return

    last_reward_claimed = user_data[7]  # last_reward_claimed field

    message = (
        "Choose an option below to gain your ₱eso 👇🏻"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=get_task_menu_buttons(last_reward_claimed, user_id)
    )

async def handle_daily_reward(update: Update, context: CallbackContext):
    """Handle daily reward claim"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("⚠️ Account error. Please use /start to register.")
        return

    if check_user_banned(user_data):
        await query.edit_message_text("🚫 You have been banned from using this bot.")
        return

    last_reward_claimed = user_data[7]  # last_reward_claimed field

    if can_claim_daily_reward(last_reward_claimed):
        # Give daily reward
        success = db.update_user_balance(
            user_id, 
            DAILY_REWARD_AMOUNT, 
            "daily_reward", 
            "Daily reward claimed"
        )

        if success:
            db.update_last_reward_claimed(user_id)

            # Get updated balance
            updated_user_data = db.get_user(user_id)
            new_balance = updated_user_data[3] if updated_user_data else 0

            keyboard = [[InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]]

            await query.edit_message_text(
                f"🎁 *Daily Reward Claimed!*\n\n"
                f"You received: {format_currency(DAILY_REWARD_AMOUNT)}\n"
                f"New Balance: {format_currency(new_balance)}\n\n"
                f"Come back tomorrow for another reward!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text("❌ Error claiming reward. Please try again later.")
    else:
        time_until_next = calculate_time_until_next_reward(last_reward_claimed)

        await query.edit_message_text(
            f"⏰ You've already claimed your daily reward!\n\n"
            f"Next reward available in: {time_until_next}"
        )

async def handle_daily_claimed(update: Update, context: CallbackContext):
    """Handle when user tries to claim already claimed daily reward"""
    query = update.callback_query
    await query.answer("You've already claimed your daily reward today!", show_alert=True)

async def handle_generate_shortlink(update: Update, context: CallbackContext):
    """Handle shortlink generation request"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Check if user is in channel
    if not await is_user_in_channel(user_id, context):
        await query.edit_message_text(
            f"You must join this channel first!\n{CHANNEL_USERNAME}\n\nAfter joining, try again."
        )
        return

    # Check if user is banned
    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await query.edit_message_text("🚫 You have been banned from using this bot.")
        return

    # Check if user has an unused shortlink first
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT click_code FROM shortlink_clicks WHERE user_id = ? AND reward_claimed = 0 ORDER BY click_timestamp DESC LIMIT 1",
                (user_id,)
            )
            unused_link = cursor.fetchone()

            if unused_link:
                # User has an unused shortlink, regenerate the shortened URL
                click_code = unused_link[0]
                tracking_url = f"https://example.com?code={click_code}"

                # Try to get the existing shortened URL or create new one
                shortlink = generate_shortlink_from_code(click_code)

                if shortlink:
                    keyboard = [
                        [InlineKeyboardButton("🔗 Open Shortlink", url=shortlink)],
                        [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
                    ]

                    # Get current reward amount
                    reward_amount = get_shortlink_reward_amount()

                    message = (
                        f"🎯 *Your Saved Shortlink!*\n\n"
                        f"💰 Reward: {format_currency(reward_amount)}\n\n"
                        f"📋 *Instructions:*\n"
                        f"1. Click the 'Open Shortlink' button below\n"
                        f"2. Complete the action on the website\n"
                        f"3. Earn {format_currency(reward_amount)} instantly!\n\n"
                        f"🔗 Your Link: `{shortlink}`\n\n"
                        f"⚠️ *Note:* This is your saved link - use it before generating a new one!"
                    )

                    await query.edit_message_text(
                        message,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return
        except Exception as e:
            logger.error(f"Error checking unused shortlinks: {e}")
        finally:
            conn.close()

    # Check shortlink cooldown for new generation
    if not can_generate_shortlink(user_id):
        # Calculate time until next reward
        last_used_time = None
        with db.lock:
            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT click_timestamp FROM shortlink_clicks WHERE user_id = ? AND reward_claimed = 1 ORDER BY click_timestamp DESC LIMIT 1",
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    last_used_time = datetime.fromisoformat(result[0])
            finally:
                conn.close()
        time_until_next = "❌ No shortlink available"
        if last_used_time:
            next_available_time = last_used_time + timedelta(hours=24)
            time_remaining = next_available_time - datetime.now()
            days, seconds = time_remaining.days, time_remaining.seconds
            hours = days * 24 + seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            time_until_next = f"❌ No shortlink available, please try again after {hours}H {minutes}M {seconds}S."

        await query.edit_message_text(
            time_until_next,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )
        return

    # Show loading message
    await query.edit_message_text("🔄 Generating your unique shortlink...")

    # Generate new shortlink
    shortlink = generate_shortlink(user_id)

    if shortlink:
        keyboard = [
            [InlineKeyboardButton("🔗 Open Shortlink", url=shortlink)],
            [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
        ]

        # Get current reward amount
        reward_amount = get_shortlink_reward_amount()

        message = (
            f"🎯 *Your Shortlink is Ready!*\n\n"
            f"💰 Reward: {format_currency(reward_amount)}\n\n"
            f"📋 *Instructions:*\n"
            f"1. Click the 'Open Shortlink' button below\n"
            f"2. Complete the action on the website\n"
            f"3. Earn {format_currency(reward_amount)} instantly!\n\n"
            f"🔗 Your Link: `{shortlink}`\n\n"
            f"⚠️ *Note:* Each link can only be used once!\n"
            f"⏰ Next shortlink available in 24 hours."
        )

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            "❌ Unable to generate shortlink at the moment.\n\n"
            "This could be due to:\n"
            "• API service temporarily unavailable\n"
            "• Network connectivity issues\n"
            "• Service maintenance\n\n"
            "Please try again in a few minutes.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="generate_shortlink")],
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )

async def handle_back_to_tasks(update: Update, context: CallbackContext):
    """Handle back to tasks button"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("⚠️ Account error. Please use /start to register.")
        return

    last_reward_claimed = user_data[7]

    message = (
        "Choose an option below to gain your ₱eso 👇🏻"
    )

    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=get_task_menu_buttons(last_reward_claimed, user_id)
    )

async def handle_view_more_history(update: Update, context: CallbackContext):
    """Handle view more history button"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("⚠️ Account error. Please use /start to register.")
        return

    # Get all withdrawal history
    withdrawals = db.get_user_withdrawals(user_id, limit=100)

    if not withdrawals:
        await query.edit_message_text("📊 You don't have any withdrawal history yet.")
        return

    message = "📊 *Complete Withdrawal History*\n\n"

    for withdrawal in withdrawals:
        withdrawal_id, amount, gcash_number, status, timestamp = withdrawal

        # Format timestamp
        try:
            trans_time = datetime.fromisoformat(timestamp).strftime("%m/%d %H:%M")
        except:
            trans_time = "Unknown"

        # Format status with emoji
        if status == "pending":
            status_emoji = "⏳ Pending"
        elif status == "approved":
            status_emoji = "✅ Success"
        elif status == "rejected":
            status_emoji = "❌ Rejected"
        else:
            status_emoji = f"📋 {status.title()}"

        message += f"💸 **Withdrawal**\n"
        message += f"Amount: {format_currency(amount)}\n"
        message += f"GCash: {format_gcash_number(gcash_number)}\n"
        message += f"Status: {status_emoji}\n"
        message += f"Date: {trans_time}\n\n"

    keyboard = [[InlineKeyboardButton("📋 View Less", callback_data="view_less_history")]]

    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_view_less_history(update: Update, context: CallbackContext):
    """Handle view less history button"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("⚠️ Account error. Please use /start to register.")
        return

    # Get only 2 most recent withdrawals
    withdrawals = db.get_user_withdrawals(user_id, limit=2)

    if not withdrawals:
        await query.edit_message_text("📊 You don't have any withdrawal history yet.")
        return

    message = "📊 *Recent Withdrawals*\n\n"

    for withdrawal in withdrawals:
        withdrawal_id, amount, gcash_number, status, timestamp = withdrawal

        # Format timestamp
        try:
            trans_time = datetime.fromisoformat(timestamp).strftime("%m/%d %H:%M")
        except:
            trans_time = "Unknown"

        # Format status with emoji
        if status == "pending":
            status_emoji = "⏳ Pending"
        elif status == "approved":
            status_emoji = "✅ Success"
        elif status == "rejected":
            status_emoji = "❌ Rejected"
        else:
            status_emoji = f"📋 {status.title()}"

        message += f"💸 **Withdrawal**\n"
        message += f"Amount: {format_currency(amount)}\n"
        message += f"GCash: {format_gcash_number(gcash_number)}\n"
        message += f"Status: {status_emoji}\n"
        message += f"Date: {trans_time}\n\n"

    # Check if user has more withdrawals
    all_withdrawals = db.get_user_withdrawals(user_id, limit=100)
    has_more = len(all_withdrawals) > 2

    keyboard = []
    if has_more:
        keyboard.append([InlineKeyboardButton("📋 View More", callback_data="view_more_history")])

    if keyboard:
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text(message, parse_mode='Markdown')

async def handle_solve_captcha(update: Update, context: CallbackContext):
    """Handle captcha solving request"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Check if user is in channel
    if not await is_user_in_channel(user_id, context):
        await query.edit_message_text(
            f"You must join this channel first!\n{CHANNEL_USERNAME}\n\nAfter joining, try again."
        )
        return

    # Check if user is banned
    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await query.edit_message_text("🚫 You have been banned from using this bot.")
        return

    # Check if user has an active captcha session
    active_session = get_active_captcha_session(user_id)

    if active_session:
        # User has an active session, show progress
        session_data = active_session
        completed = session_data['completed']
        total = session_data['total']
        reward_per_captcha = session_data['reward_per_captcha']
        remaining_links = session_data['remaining_links']

        if completed >= total:
            # Session is completed but not marked as such (edge case)
            await query.edit_message_text(
                "✅ All captchas completed!\n\n"
                "Wait 24 hours for your next captcha session.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
                ])
            )
            return

        # Generate direct captcha links (no shortening needed)
        captcha_links = []

        for link_number, captcha_code in remaining_links[:3]:  # Show max 3 links at a time
            # Get captcha URL from settings
            captcha_base_url = get_captcha_url_from_settings()
            captcha_url = f"{captcha_base_url}?captcha={captcha_code}"

            captcha_links.append({
                'number': link_number,
                'url': captcha_url
            })

        # Create keyboard with captcha links
        keyboard = []
        for link in captcha_links:
            keyboard.append([InlineKeyboardButton(f"🛡️ Captcha {link['number']}", url=link['url'])])

        keyboard.append([InlineKeyboardButton("🔄 Refresh Progress", callback_data="solve_captcha")])
        keyboard.append([InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")])

        message = (
            f"🛡️ *Captcha Session Active*\n\n"
            f"💰 Reward per captcha: {format_currency(reward_per_captcha)}\n"
            f"📊 Progress: {completed}/{total} completed\n"
            f"💵 Total earned: {format_currency(completed * reward_per_captcha)}\n\n"
            f"📋 *Instructions:*\n"
            f"1. Click on a captcha link below\n"
            f"2. Complete the captcha challenge\n"
            f"3. Return here to see your progress\n\n"
            f"⚠️ Complete all 10 captchas to finish this session!"
        )

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Check captcha cooldown for new session
    if not can_generate_captcha_session(user_id):
        # Calculate time until next captcha session
        last_completed_time = None
        with db.lock:
            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT last_captcha_at FROM captcha_sessions WHERE user_id = ? AND session_completed = 1 ORDER BY last_captcha_at DESC LIMIT 1",
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    last_completed_time = datetime.fromisoformat(result[0])
            finally:
                conn.close()
        
        time_until_next = "❌ No captcha session available"
        if last_completed_time:
            next_available_time = last_completed_time + timedelta(hours=24)
            time_remaining = next_available_time - datetime.now()
            days, seconds = time_remaining.days, time_remaining.seconds
            hours = days * 24 + seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            time_until_next = f"❌ No captcha session available, please try again after {hours}H {minutes}M {seconds}S."

        await query.edit_message_text(
            time_until_next,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )
        return

    # Show loading message
    await query.edit_message_text("🔄 Creating your captcha session...")

    # Create new captcha session
    session_id, captcha_links = create_captcha_session(user_id)

    if session_id and captcha_links:
        # Generate direct captcha URLs for first 3 captchas
        captcha_reward = get_captcha_reward_amount()

        keyboard = []
        for i, link_data in enumerate(captcha_links[:3]):  # Show first 3 links
            # Get captcha URL from settings
            captcha_base_url = get_captcha_url_from_settings()
            captcha_url = f"{captcha_base_url}?captcha={link_data['code']}"

            keyboard.append([InlineKeyboardButton(f"🛡️ Captcha {link_data['number']}", url=captcha_url)])

        keyboard.append([InlineKeyboardButton("🔄 Refresh Progress", callback_data="solve_captcha")])
        keyboard.append([InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")])

        message = (
            f"🛡️ *Captcha Session Created!*\n\n"
            f"💰 Reward per captcha: {format_currency(captcha_reward)}\n"
            f"📊 Total captchas: 10\n"
            f"💵 Total potential earnings: {format_currency(captcha_reward * 10)}\n\n"
            f"📋 *Instructions:*\n"
            f"1. Click on a captcha link below\n"
            f"2. Complete the captcha challenge\n"
            f"3. Return here for the next captcha\n\n"
            f"⚠️ *Note:* Complete all 10 to finish the session!\n"
            f"⏰ Next session available in 24 hours after completion."
        )

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            "❌ Unable to create captcha session at the moment.\n\n"
            "Please try again in a few minutes.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="solve_captcha")],
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )

async def handle_toggle_notification(update: Update, context: CallbackContext):
    """Handle notification preference toggle"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    callback_data = query.data

    # Parse callback data: toggle_notif_{type}_{new_value}
    parts = callback_data.split('_')
    if len(parts) < 3:
        await query.answer("Invalid request", show_alert=True)
        return

    # Handle different notification types properly
    if parts[2] == "daily":
        notification_type = "daily_reward"
        new_value = int(parts[4]) if len(parts) > 4 else int(parts[3])
    elif parts[2] == "shortlink":
        notification_type = "shortlink"
        new_value = int(parts[3])
    elif parts[2] == "captcha":
        notification_type = "captcha"
        new_value = int(parts[3])
    elif parts[2] == "watch":
        notification_type = "watch_ads"
        new_value = int(parts[4]) if len(parts) > 4 else int(parts[3])
    else:
        await query.answer("Invalid notification type", show_alert=True)
        return

    # Update notification preference
    success = db.update_user_notification(user_id, notification_type, bool(new_value))

    if success:
        # Get updated preferences
        daily_notif, shortlink_notif, captcha_notif, ads_notif = db.get_user_notifications(user_id)

        # Update the message with new button states
        message = "🔔 *Notification Settings*\n\nUse the buttons below to turn on/off the desired notifications 👇"

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'✅' if daily_notif else '❎'} Daily Reward", 
                    callback_data=f"toggle_notif_daily_reward_{1-daily_notif}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if shortlink_notif else '❎'} Shortlink", 
                    callback_data=f"toggle_notif_shortlink_{1-shortlink_notif}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if captcha_notif else '❎'} Captcha", 
                    callback_data=f"toggle_notif_captcha_{1-captcha_notif}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if ads_notif else '❎'} Ads", 
                    callback_data=f"toggle_notif_watch_ads_{1-ads_notif}"
                )
            ]
        ]

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.answer("Error updating notification preference", show_alert=True)

async def handle_back_to_settings(update: Update, context: CallbackContext):
    """Handle back to settings button"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("⚠️ Account error. Please use /start to register.")
        return

    gcash_number = user_data[8]  # gcash_number field
    gcash_status = f"📱 Current: {format_gcash_number(gcash_number)}" if gcash_number else "📱 Not set"

    message = (
        f"⚙️ *Settings Menu*\n\n"
        f"GCash Number: {gcash_status}\n\n"
        f"Choose an option below:"
    )

    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=settings_keyboard()
    )

async def handle_watch_ads(update: Update, context: CallbackContext):
    """Handle watch ads request"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Check if user is in channel
    if not await is_user_in_channel(user_id, context):
        await query.edit_message_text(
            f"You must join this channel first!\n{CHANNEL_USERNAME}\n\nAfter joining, try again."
        )
        return

    # Check if user is banned
    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await query.edit_message_text("🚫 You have been banned from using this bot.")
        return

    # Check if user has an unused watch ads link first
    with db.lock:
        conn = db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT ad_code FROM watch_ads WHERE user_id = ? AND reward_claimed = 0 ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
            unused_link = cursor.fetchone()

            if unused_link:
                # User has an unused watch ads link
                ad_code = unused_link[0]
                watch_ads_url = f"{get_watch_ads_url_from_settings()}?ad={ad_code}"

                keyboard = [
                    [InlineKeyboardButton("👁️ Watch Ads", url=watch_ads_url)],
                    [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
                ]

                reward_amount = get_watch_ads_reward_amount()

                message = (
                    f"👁️ *Your Saved Watch Ads Link!*\n\n"
                    f"💰 Reward: {format_currency(reward_amount)}\n\n"
                    f"📋 *Instructions:*\n"
                    f"1. Click the 'Watch Ads' button below\n"
                    f"2. Watch the advertisement completely\n"
                    f"3. Earn {format_currency(reward_amount)} instantly!\n\n"
                    f"⚠️ *Note:* This is your saved link - use it before generating a new one!"
                )

                await query.edit_message_text(
                    message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
        except Exception as e:
            logger.error(f"Error checking unused watch ads: {e}")
        finally:
            conn.close()

    # Check watch ads cooldown for new generation
    if not can_generate_watch_ads(user_id):
        # Calculate time until next watch ads
        last_claimed_time = None
        with db.lock:
            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT claimed_at FROM watch_ads WHERE user_id = ? AND reward_claimed = 1 ORDER BY claimed_at DESC LIMIT 1",
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    last_claimed_time = datetime.fromisoformat(result[0])
            finally:
                conn.close()
        
        time_until_next = "❌ No watch ads available"
        if last_claimed_time:
            next_available_time = last_claimed_time + timedelta(hours=1)
            time_remaining = next_available_time - datetime.now()
            total_seconds = int(time_remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_until_next = f"❌ No watch ads available, please try again after {hours}H {minutes}M {seconds}S."

        await query.edit_message_text(
            time_until_next,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )
        return

    # Show loading message
    await query.edit_message_text("🔄 Preparing your watch ads link...")

    # Generate new watch ads link
    ad_code = create_watch_ads_code(user_id)

    if ad_code:
        watch_ads_url = f"{get_watch_ads_url_from_settings()}?ad={ad_code}"
        
        keyboard = [
            [InlineKeyboardButton("👁️ Watch Ads", url=watch_ads_url)],
            [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
        ]

        reward_amount = get_watch_ads_reward_amount()

        message = (
            f"👁️ *Your Watch Ads Link is Ready!*\n\n"
            f"💰 Reward: {format_currency(reward_amount)}\n\n"
            f"📋 *Instructions:*\n"
            f"1. Click the 'Watch Ads' button below\n"
            f"2. Watch the advertisement completely\n"
            f"3. Earn {format_currency(reward_amount)} instantly!\n\n"
            f"⚠️ *Note:* Each link can only be used once!\n"
            f"⏰ Next watch ads available in 1 hour."
        )

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            "❌ Unable to generate watch ads link at the moment.\n\n"
            "Please try again in a few minutes.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="watch_ads")],
                [InlineKeyboardButton("↩️ Back to Tasks", callback_data="back_to_tasks")]
            ])
        )

# =============================================================================
# WALLET HANDLERS
# =============================================================================

async def settings_menu(update: Update, context: CallbackContext):
    """Show settings menu"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")
        return

    gcash_number = user_data[8]  # gcash_number field
    gcash_status = f"📱 Current: {format_gcash_number(gcash_number)}" if gcash_number else "📱 Not set"

    message = (
        f"⚙️ *Settings Menu*\n\n"
        f"GCash Number: {gcash_status}\n\n"
        f"Choose an option below:"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=settings_keyboard()
    )

async def update_gcash_start(update: Update, context: CallbackContext):
    """Start GCash number update process"""
    message = (
        "📱 *Update GCash Number*\n\n"
        "Please enter your GCash number (11 digits starting with 09):\n\n"
        "Example: 09123456789"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=cancel_keyboard()
    )

    return GCASH_NUMBER

async def update_gcash_number(update: Update, context: CallbackContext):
    """Handle GCash number input"""
    gcash_number = update.message.text.strip()

    if gcash_number == "❌ Cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=settings_keyboard())
        return ConversationHandler.END

    if not validate_gcash_number(gcash_number):
        await update.message.reply_text(
            "❌ Invalid GCash number format!\n\n"
            "Please enter a valid 11-digit number starting with 09.\n"
            "Example: 09123456789",
            reply_markup=cancel_keyboard()
        )
        return GCASH_NUMBER

    # Clean the number (remove any formatting)
    clean_number = gcash_number.replace(" ", "").replace("-", "")
    user_id = update.effective_user.id

    if db.update_gcash_number(user_id, clean_number):
        await update.message.reply_text(
            f"✅ GCash number updated successfully!\n\n"
            f"New number: {format_gcash_number(clean_number)}",
            reply_markup=settings_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Error updating GCash number. Please try again.",
            reply_markup=settings_keyboard()
        )

    return ConversationHandler.END

async def notifications_menu(update: Update, context: CallbackContext):
    """Show notifications settings menu"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")
        return

    # Get current notification preferences
    daily_notif, shortlink_notif, captcha_notif, ads_notif = db.get_user_notifications(user_id)

    message = "🔔 *Notification Settings*\n\nUse the buttons below to turn on/off the desired notifications 👇"

    # Create inline keyboard with current status
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✅' if daily_notif else '❎'} Daily Reward", 
                callback_data=f"toggle_notif_daily_reward_{1-daily_notif}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if shortlink_notif else '❎'} Shortlink", 
                callback_data=f"toggle_notif_shortlink_{1-shortlink_notif}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if captcha_notif else '❎'} Captcha", 
                callback_data=f"toggle_notif_captcha_{1-captcha_notif}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if ads_notif else '❎'} Ads", 
                callback_data=f"toggle_notif_watch_ads_{1-ads_notif}"
            )
        ]
    ]

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def back_to_menu(update: Update, context: CallbackContext):
    """Return to main menu"""
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)

    await update.message.reply_text(
        "↩️ Returned to main menu.",
        reply_markup=main_menu_keyboard(is_admin_user)
    )

async def withdraw_start(update: Update, context: CallbackContext):
    """Start withdrawal process"""
    user_id = update.effective_user.id

    if not await is_user_in_channel(user_id, context):
        message = f"You must join this channel to use this bot👇🏻\n{CHANNEL_USERNAME}\nAfter joining, click '✅ Done'."
        await update.message.reply_text(message, reply_markup=not_joined_reply_keyboard())
        return ConversationHandler.END

    user_data = db.get_user(user_id)
    if check_user_banned(user_data):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return ConversationHandler.END

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please use /start to register.")
        return ConversationHandler.END

    balance = user_data[3]  # balance field
    gcash_number = user_data[8]  # gcash_number field

    if not gcash_number:
        await update.message.reply_text(
            "❌ You need to set your GCash number first!\n\n"
            "Go to ⚙️ Settings → 📱 Update GCash Number"
        )
        return ConversationHandler.END

    if balance < MINIMUM_WITHDRAWAL:
        await update.message.reply_text(
            f"❌ Insufficient balance!\n\n"
            f"Your balance: {format_currency(balance)}\n"
            f"Minimum withdrawal: {format_currency(MINIMUM_WITHDRAWAL)}"
        )
        return ConversationHandler.END

    message = (
        f"💸 *Withdrawal Request*\n\n"
        f"Current Balance: {format_currency(balance)}\n"
        f"GCash Number: {format_gcash_number(gcash_number)}\n"
        f"Minimum: {format_currency(MINIMUM_WITHDRAWAL)}\n\n"
        f"Enter withdrawal amount or use shortcuts:"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=get_withdraw_amount_keyboard()
    )

    return WITHDRAW_AMOUNT

async def withdraw_amount_input(update: Update, context: CallbackContext):
    """Handle withdrawal amount input"""
    amount_text = update.message.text.strip()

    if amount_text == "❌ Cancel":
        user_id = update.effective_user.id
        is_admin_user = is_admin(user_id)
        await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=main_menu_keyboard(is_admin_user))
        return ConversationHandler.END

    user_id = update.effective_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await update.message.reply_text("⚠️ Account error. Please restart the process.")
        return ConversationHandler.END

    balance = user_data[3]  # balance field
    amount = parse_amount(amount_text, balance)

    is_valid, error_message = is_valid_withdrawal_amount(amount, balance, MINIMUM_WITHDRAWAL)

    if not is_valid:
        await update.message.reply_text(
            f"❌ {error_message}\n\n"
            f"Please enter a valid amount:",
            reply_markup=get_withdraw_amount_keyboard()
        )
        return WITHDRAW_AMOUNT

    # Store amount in context for confirmation
    context.user_data['withdrawal_amount'] = amount

    gcash_number = user_data[8]  # gcash_number field
    new_balance = balance - amount

    message = (
        f"💸 *Confirm Withdrawal*\n\n"
        f"Amount: {format_currency(amount)}\n"
        f"To: {format_gcash_number(gcash_number)}\n"
        f"Remaining Balance: {format_currency(new_balance)}\n\n"
        f"⚠️ This action cannot be undone.\n"
        f"Please confirm your withdrawal:"
    )

    await update.message.reply_text(
        message,
        parse_mode='Markdown',
        reply_markup=get_confirmation_keyboard()
    )

    return WITHDRAW_CONFIRM

async def withdraw_confirm(update: Update, context: CallbackContext):
    """Handle withdrawal confirmation"""
    confirmation = update.message.text.strip().upper()

    if confirmation in ["❌ CANCEL", "CANCEL", "❌ Cancel"]:
        user_id = update.effective_user.id
        is_admin_user = is_admin(user_id)
        await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=main_menu_keyboard(is_admin_user))
        return ConversationHandler.END

    if confirmation not in ["CONFIRM", "✅ CONFIRM", "✅ Confirm", "CONFIRM"]:
        await update.message.reply_text(
            "❌ Invalid confirmation.\n\n"
            "Please use the buttons below to confirm or cancel:",
            reply_markup=get_confirmation_keyboard()
        )
        return WITHDRAW_CONFIRM

    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    amount = context.user_data.get('withdrawal_amount')

    if not user_data or not amount:
        await update.message.reply_text("⚠️ Error processing withdrawal. Please try again.")
        return ConversationHandler.END

    gcash_number = user_data[8]  # gcash_number field

    # Create withdrawal request
    withdrawal_id = db.create_withdrawal_request(user_id, amount, gcash_number)

    if withdrawal_id:
        # Notify user
        message = (
            f"✅ *Withdrawal Request Submitted*\n\n"
            f"Request ID: #{withdrawal_id}\n"
            f"Amount: {format_currency(amount)}\n"
            f"GCash: {format_gcash_number(gcash_number)}\n\n"
            f"⏳ Your request is being processed.\n"
            f"You'll be notified when it's approved."
        )

        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(False)
        )

        # Withdrawal notifications are now handled via web admin interface

    else:
        await update.message.reply_text(
            "❌ Error processing withdrawal request. Please try again later.",
            reply_markup=main_menu_keyboard(False)
        )

    return ConversationHandler.END

async def cancel_operation(update: Update, context: CallbackContext):
    """Cancel any ongoing operation"""
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)

    await update.message.reply_text(
        "❌ Operation cancelled.",
        reply_markup=main_menu_keyboard(is_admin_user)
    )
    return ConversationHandler.END

# =============================================================================
# UNKNOWN HANDLERS
# =============================================================================

async def handle_unknown(update: Update, context: CallbackContext):
    """Handle unknown commands"""
    await update.message.reply_text(
        "❓ Unknown command. Please use the menu buttons or /start to begin."
    )

# =============================================================================
# MAIN BOT SETUP
# =============================================================================

def main():
    """Start the bot"""
    # Create the Application and pass it your bot's token
    application = Application.builder().token(TOKEN).build()

    # Initialize notification scheduler
    scheduler = BackgroundScheduler()
    # Check for notifications every 30 minutes
    scheduler.add_job(
        func=check_and_send_notifications,
        trigger="interval",
        minutes=30,
        id='notification_checker'
    )
    scheduler.start()

    # Basic command handlers
    application.add_handler(CommandHandler("start", start))

    # Conversation handler for GCash number update
    gcash_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📱 Update GCash Number$'), update_gcash_start)],
        states={
            GCASH_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_gcash_number)],
        },
        fallbacks=[MessageHandler(filters.Regex('^❌ Cancel$'), cancel_operation)]
    )

    # Conversation handler for withdrawals
    withdrawal_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💸 Withdraw$'), withdraw_start)],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount_input)],
            WITHDRAW_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_confirm)],
        },
        fallbacks=[MessageHandler(filters.Regex('^❌ Cancel$'), cancel_operation)]
    )

    # Add conversation handlers
    application.add_handler(gcash_conv_handler)
    application.add_handler(withdrawal_conv_handler)

    # Main menu message handlers
    application.add_handler(MessageHandler(filters.Regex('^❇️ Gain ₱eso$'), gain_peso))
    application.add_handler(MessageHandler(filters.Regex('^💰 Balance$'), check_balance))
    application.add_handler(MessageHandler(filters.Regex('^📨 Invite$'), invite_friends))
    application.add_handler(MessageHandler(filters.Regex('^📊 History$'), check_history))
    application.add_handler(MessageHandler(filters.Regex('^⚙️ Settings$'), settings_menu))
    application.add_handler(MessageHandler(filters.Regex('^✅ Done$'), done_button))

    # Settings menu handlers
    application.add_handler(MessageHandler(filters.Regex('^🔔 Notifications$'), notifications_menu))
    application.add_handler(MessageHandler(filters.Regex('^↩️ Back to Menu$'), back_to_menu))

    # Callback query handlers for inline buttons
    application.add_handler(CallbackQueryHandler(handle_daily_reward, pattern='^daily_reward$'))
    application.add_handler(CallbackQueryHandler(handle_daily_claimed, pattern='daily_claimed$'))
    application.add_handler(CallbackQueryHandler(handle_generate_shortlink, pattern='generate_shortlink$'))
    application.add_handler(CallbackQueryHandler(handle_back_to_tasks, pattern='back_to_tasks$'))
    application.add_handler(CallbackQueryHandler(handle_view_more_history, pattern='view_more_history$'))
    application.add_handler(CallbackQueryHandler(handle_view_less_history, pattern='view_less_history$'))
    application.add_handler(CallbackQueryHandler(handle_solve_captcha, pattern='solve_captcha$'))
    application.add_handler(CallbackQueryHandler(handle_watch_ads, pattern='watch_ads$'))
    application.add_handler(CallbackQueryHandler(handle_toggle_notification, pattern='^toggle_notif_'))
    application.add_handler(CallbackQueryHandler(handle_back_to_settings, pattern='^back_to_settings$'))

    # Unknown message handler (should be last)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # Error handler
    async def error_handler(update, context):
        """Log errors caused by updates"""
        logger.warning(f'Update {update} caused error {context.error}')

    application.add_error_handler(error_handler)

    # Start the bot
    logger.info("Starting GainWell Bot...")

    # Start polling for updates
    application.run_polling()

if __name__ == '__main__':
    main()
