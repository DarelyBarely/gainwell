#!/usr/bin/env python3
"""
GainWell Bot Web Admin Interface
"""

import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('WEB_ADMIN_SECRET', 'your-secret-key-change-this')

# Configuration
DATABASE_NAME = 'bot_users.db'
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this!

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
    init_database(conn)
    return conn

def init_database(conn):
    """Initialize database tables if they don't exist"""
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
        VALUES ('captcha_reward_amount', '0.0671')
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('watch_ads_reward_amount', '0.0532')
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('base_url', 'https://example.com')
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('reward_page_url', 'https://example.com/reward.html')
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('captcha_page_url', 'https://example.com/captcha.html')
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('watch_ads_page_url', 'https://example.com/watch_ads.html')
    ''')
    
    conn.commit()

def format_currency(amount):
    """Format currency"""
    if amount == 0:
        return "₱0"
    elif amount == int(amount):
        return f"₱{int(amount)}"
    else:
        return f"₱{amount:.4f}".rstrip('0').rstrip('.')

def format_datetime(timestamp_str):
    """Format datetime string"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return timestamp_str

@app.route('/')
def main_page():
    """Main landing page"""
    return render_template('main.html')

@app.route('/reward.html')
def reward_page():
    """Serve the reward claiming page"""
    return send_from_directory('..', 'reward.html')

@app.route('/captcha.html')
def captcha_page():
    """Serve the captcha solving page"""
    return send_from_directory('..', 'captcha.html')

@app.route('/watch_ads.html')
def watch_ads_page():
    """Serve the watch ads page"""
    return send_from_directory('..', 'watch_ads.html')

@app.route('/@dminpanel')
def dashboard():
    """Admin dashboard"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(balance) FROM users")
    total_balance_result = cursor.fetchone()[0]
    total_balance = total_balance_result if total_balance_result else 0
    
    cursor.execute("SELECT SUM(referrals) FROM users")
    total_referrals_result = cursor.fetchone()[0]
    total_referrals = total_referrals_result if total_referrals_result else 0
    
    cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
    pending_withdrawals = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount) FROM withdrawals WHERE status = 'pending'")
    pending_amount_result = cursor.fetchone()[0]
    pending_amount = pending_amount_result if pending_amount_result else 0
    
    conn.close()
    
    stats = {
        'total_users': total_users,
        'active_users': active_users,
        'banned_users': banned_users,
        'total_balance': format_currency(total_balance),
        'total_referrals': total_referrals,
        'pending_withdrawals': pending_withdrawals,
        'pending_amount': format_currency(pending_amount)
    }
    
    return render_template('dashboard.html', stats=stats)

@app.route('/users')
def users():
    """User management page"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get users with pagination
    cursor.execute("""
        SELECT user_id, username, first_name, balance, referrals, created_at, is_banned
        FROM users 
        ORDER BY created_at DESC 
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    
    users_data = cursor.fetchall()
    
    # Get total count for pagination
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    conn.close()
    
    # Format users data
    users_list = []
    for user in users_data:
        users_list.append({
            'user_id': user[0],
            'username': user[1] or 'No username',
            'first_name': user[2] or 'Unknown',
            'balance': format_currency(user[3]),
            'referrals': user[4],
            'created_at': format_datetime(user[5]) if user[5] else 'Unknown',
            'is_banned': bool(user[6]),
            'status': '🚫 Banned' if user[6] else '✅ Active'
        })
    
    # Calculate pagination info
    total_pages = (total_users + per_page - 1) // per_page
    
    return render_template('users.html', 
                         users=users_list, 
                         page=page, 
                         total_pages=total_pages,
                         total_users=total_users)

@app.route('/withdrawals')
def withdrawals():
    """Withdrawal management page"""
    status_filter = request.args.get('status', 'pending')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get withdrawals
    cursor.execute("""
        SELECT w.id, w.user_id, u.username, u.first_name, w.amount, w.gcash_number, 
               w.status, w.timestamp, w.admin_note, w.completed_at
        FROM withdrawals w
        JOIN users u ON w.user_id = u.user_id
        WHERE w.status = ?
        ORDER BY w.timestamp DESC
    """, (status_filter,))
    
    withdrawals_data = cursor.fetchall()
    conn.close()
    
    # Format withdrawals data
    withdrawals_list = []
    for w in withdrawals_data:
        withdrawals_list.append({
            'id': w[0],
            'user_id': w[1],
            'username': w[2] or 'No username',
            'first_name': w[3] or 'Unknown',
            'amount': format_currency(w[4]),
            'gcash_number': w[5],
            'status': w[6],
            'timestamp': format_datetime(w[7]) if w[7] else 'Unknown',
            'admin_note': w[8] or '',
            'completed_at': format_datetime(w[9]) if w[9] else ''
        })
    
    return render_template('withdrawals.html', 
                         withdrawals=withdrawals_list,
                         current_status=status_filter)

@app.route('/add_balance', methods=['GET', 'POST'])
def add_balance():
    """Add balance to user"""
    if request.method == 'POST':
        search_term = request.form.get('search_term', '').strip()
        amount = request.form.get('amount')
        
        try:
            amount = float(amount)
            
            if amount <= 0:
                flash('Amount must be positive', 'error')
                return redirect(url_for('add_balance'))
            
            conn = get_db()
            cursor = conn.cursor()
            
            # Search for user by ID, username, or name
            user = None
            user_id = None
            
            # Try to find by user ID first
            if search_term.isdigit():
                cursor.execute("SELECT user_id, first_name, username FROM users WHERE user_id = ?", (int(search_term),))
                user = cursor.fetchone()
                if user:
                    user_id = user[0]
            
            # If not found by ID, search by username (with or without @)
            if not user:
                username_search = search_term.replace('@', '')
                cursor.execute("SELECT user_id, first_name, username FROM users WHERE username = ?", (username_search,))
                user = cursor.fetchone()
                if user:
                    user_id = user[0]
            
            # If still not found, search by first name
            if not user:
                cursor.execute("SELECT user_id, first_name, username FROM users WHERE first_name LIKE ?", (f'%{search_term}%',))
                user = cursor.fetchone()
                if user:
                    user_id = user[0]
            
            if not user:
                flash(f'User "{search_term}" not found', 'error')
                conn.close()
                return redirect(url_for('add_balance'))
            
            # Add balance
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            
            # Log transaction
            cursor.execute("""
                INSERT INTO transactions (user_id, type, amount, description)
                VALUES (?, ?, ?, ?)
            """, (user_id, 'admin_bonus', amount, f'Balance added by admin via web interface'))
            
            conn.commit()
            conn.close()
            
            user_name = user[1] or 'Unknown'
            username = user[2] or 'no_username'
            flash(f'Successfully added {format_currency(amount)} to {user_name} (@{username})', 'success')
            
        except ValueError:
            flash('Invalid amount format', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        
        return redirect(url_for('add_balance'))
    
    return render_template('add_balance.html')

@app.route('/broadcast', methods=['GET', 'POST'])
def broadcast():
    """Send broadcast message to all users"""
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        
        if not message:
            flash('Message cannot be empty', 'error')
            return redirect(url_for('broadcast'))
        
        try:
            import requests
            import os
            
            # Get bot token (same as main bot)
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            if not bot_token:
                flash('Bot token not found. Please check environment configuration.', 'error')
                return redirect(url_for('broadcast'))
            
            # Get all active users from database
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
            users = cursor.fetchall()
            conn.close()
            
            if not users:
                flash('No active users found to send message to.', 'warning')
                return redirect(url_for('broadcast'))
            
            # Send message to all users
            success_count = 0
            failed_count = 0
            
            for user in users:
                user_id = user[0]
                try:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    data = {
                        'chat_id': user_id,
                        'text': f"📢 Broadcast Message\n\n{message}"
                    }
                    response = requests.post(url, data=data, timeout=10)
                    
                    if response.status_code == 200:
                        success_count += 1
                    else:
                        failed_count += 1
                        
                except Exception:
                    failed_count += 1
            
            if success_count > 0:
                flash(f'✅ Broadcast sent successfully to {success_count} users. {failed_count} failed.', 'success')
            else:
                flash(f'❌ Failed to send broadcast to all users. {failed_count} failed.', 'error')
            
        except Exception as e:
            flash(f'Error sending broadcast: {str(e)}', 'error')
        
        return redirect(url_for('broadcast'))
    
    return render_template('broadcast.html')

@app.route('/api/approve_withdrawal/<int:withdrawal_id>')
def approve_withdrawal(withdrawal_id):
    """Approve withdrawal via API"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get withdrawal details first
        cursor.execute("""
            SELECT w.user_id, w.amount, w.gcash_number, w.status, u.first_name, u.username
            FROM withdrawals w
            JOIN users u ON w.user_id = u.user_id
            WHERE w.id = ?
        """, (withdrawal_id,))
        withdrawal = cursor.fetchone()
        
        if not withdrawal:
            return jsonify({'success': False, 'message': 'Withdrawal not found'})
        
        if withdrawal[3] != 'pending':
            return jsonify({'success': False, 'message': 'Withdrawal already processed'})
        
        cursor.execute("""
            UPDATE withdrawals 
            SET status = 'approved', admin_note = ?, completed_at = ?
            WHERE id = ?
        """, ('Approved via web interface', datetime.now().isoformat(), withdrawal_id))
        
        conn.commit()
        conn.close()
        
        # Send notification to user via Telegram
        try:
            import requests
            
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            user_id = withdrawal[0]
            amount = withdrawal[1]
            gcash_number = withdrawal[2]
            
            message = f"✅ Withdrawal Approved!\n\n" \
                     f"Amount: ₱{amount:,.2f}\n" \
                     f"GCash: {gcash_number}\n" \
                     f"Your funds have been processed successfully!"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': user_id,
                'text': message
            }
            requests.post(url, data=data, timeout=10)
        except Exception:
            pass  # Don't fail if notification fails
        
        return jsonify({'success': True, 'message': f'Withdrawal #{withdrawal_id} approved'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/reject_withdrawal/<int:withdrawal_id>')
def reject_withdrawal(withdrawal_id):
    """Reject withdrawal via API"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get withdrawal details
        cursor.execute("SELECT user_id, amount FROM withdrawals WHERE id = ?", (withdrawal_id,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': 'Withdrawal not found'})
        
        user_id, amount = result
        
        # Refund balance
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        
        # Update withdrawal status
        cursor.execute("""
            UPDATE withdrawals 
            SET status = 'rejected', admin_note = ?, completed_at = ?
            WHERE id = ?
        """, ('Rejected via web interface', datetime.now().isoformat(), withdrawal_id))
        
        # Log refund transaction
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES (?, ?, ?, ?)
        """, (user_id, 'withdrawal_refund', amount, 'Withdrawal rejected - refund'))
        
        conn.commit()
        conn.close()
        
        # Send notification to user about rejection
        try:
            import requests
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            
            message = f"❌ Withdrawal Rejected\n\n" \
                     f"Amount: ₱{amount:,.2f}\n" \
                     f"Your funds have been refunded to your balance.\n" \
                     f"Please contact support if you have questions."
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': user_id,
                'text': message
            }
            requests.post(url, data=data, timeout=10)
        except Exception:
            pass  # Don't fail if notification fails
        
        return jsonify({'success': True, 'message': f'Withdrawal #{withdrawal_id} rejected and refunded'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/ban_user/<int:user_id>')
def ban_user(user_id):
    """Ban user via API"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'User {user_id} banned'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/unban_user/<int:user_id>')
def unban_user(user_id):
    """Unban user via API"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'User {user_id} unbanned'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings management page"""
    if request.method == 'POST':
        try:
            # Get form data
            new_reward = request.form.get('shortlink_reward')
            new_base_url = request.form.get('base_url')
            new_captcha_reward = request.form.get('captcha_reward')
            new_watch_ads_reward = request.form.get('watch_ads_reward')
            
            if not new_reward:
                flash('Shortlink reward amount is required', 'error')
                return redirect(url_for('settings'))
            
            if not new_base_url:
                flash('Base URL is required', 'error')
                return redirect(url_for('settings'))
            
            if not new_captcha_reward:
                flash('Captcha reward amount is required', 'error')
                return redirect(url_for('settings'))
            
            if not new_watch_ads_reward:
                flash('Watch ads reward amount is required', 'error')
                return redirect(url_for('settings'))
            
            try:
                reward_amount = float(new_reward)
                captcha_reward_amount = float(new_captcha_reward)
                watch_ads_reward_amount = float(new_watch_ads_reward)
                
                if reward_amount < 0:
                    flash('Shortlink reward amount must be positive', 'error')
                    return redirect(url_for('settings'))
                
                if captcha_reward_amount < 0:
                    flash('Captcha reward amount must be positive', 'error')
                    return redirect(url_for('settings'))
                
                if watch_ads_reward_amount < 0:
                    flash('Watch ads reward amount must be positive', 'error')
                    return redirect(url_for('settings'))
                
                # Validate base URL format
                if not new_base_url.startswith(('http://', 'https://')):
                    flash('Base URL must start with http:// or https://', 'error')
                    return redirect(url_for('settings'))
                
                # Remove trailing slash if present
                new_base_url = new_base_url.rstrip('/')
                
                # Update the settings in database
                conn = get_db()
                cursor = conn.cursor()
                
                # Create settings table if it doesn't exist
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                # Insert or update the shortlink reward amount
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('shortlink_reward_amount', ?)
                ''', (str(reward_amount),))
                
                # Insert or update the captcha reward amount
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('captcha_reward_amount', ?)
                ''', (str(captcha_reward_amount),))
                
                # Insert or update the watch ads reward amount
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('watch_ads_reward_amount', ?)
                ''', (str(watch_ads_reward_amount),))
                
                # Insert or update the base URL
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('base_url', ?)
                ''', (new_base_url,))
                
                # Update individual page URLs based on base URL for backward compatibility
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('reward_page_url', ?)
                ''', (f"{new_base_url}/reward.html",))
                
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('captcha_page_url', ?)
                ''', (f"{new_base_url}/captcha.html",))
                
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value) 
                    VALUES ('watch_ads_page_url', ?)
                ''', (f"{new_base_url}/watch_ads.html",))
                
                conn.commit()
                conn.close()
                
                # Clear any potential caching by forcing a fresh database read
                try:
                    test_conn = get_db()
                    test_cursor = test_conn.cursor()
                    test_cursor.execute("SELECT value FROM settings WHERE key = 'shortlink_reward_amount'")
                    verify_result = test_cursor.fetchone()
                    test_conn.close()
                except:
                    pass
                
                flash(f'Settings updated successfully! Base URL: {new_base_url} | Rewards - Shortlink: {format_currency(reward_amount)}, Captcha: {format_currency(captcha_reward_amount)}, Watch Ads: {format_currency(watch_ads_reward_amount)}', 'success')
                
            except ValueError:
                flash('Invalid reward amount format', 'error')
                
        except Exception as e:
            flash(f'Error updating settings: {str(e)}', 'error')
        
        return redirect(url_for('settings'))
    
    # GET request - show current settings
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current shortlink reward amount
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'shortlink_reward_amount'")
        result = cursor.fetchone()
        current_reward = float(result[0]) if result else 0.0724  # Default value
    except:
        current_reward = 0.0724  # Default value
    
    # Get current captcha reward amount
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'captcha_reward_amount'")
        result = cursor.fetchone()
        current_captcha_reward = float(result[0]) if result else 0.0671  # Default value
    except:
        current_captcha_reward = 0.0671  # Default value
    
    # Get current watch ads reward amount
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'watch_ads_reward_amount'")
        result = cursor.fetchone()
        current_watch_ads_reward = float(result[0]) if result else 0.0532  # Default value
    except:
        current_watch_ads_reward = 0.0532  # Default value
    
    # Get current base URL
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'base_url'")
        result = cursor.fetchone()
        current_base_url = result[0] if result else "https://example.com"
    except:
        current_base_url = "https://example.com"
    
    conn.close()
    
    return render_template('settings.html', 
                         current_reward=current_reward, 
                         current_captcha_reward=current_captcha_reward, 
                         current_watch_ads_reward=current_watch_ads_reward,
                         current_base_url=current_base_url)

@app.route('/api/claim-shortlink-reward', methods=['POST'])
def claim_shortlink_reward():
    """Handle shortlink reward claiming from the reward page"""
    try:
        data = request.get_json()
        
        if not data or 'code' not in data:
            return jsonify({
                'success': False, 
                'title': 'Invalid Request', 
                'message': 'No reward code provided'
            })
        
        code = data['code']
        ip_address = data.get('ip_address', '')
        user_agent = data.get('user_agent', '')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if code exists and not claimed
        cursor.execute(
            "SELECT user_id, reward_claimed FROM shortlink_clicks WHERE click_code = ?",
            (code,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Invalid Link', 
                'message': 'This reward link is invalid or expired.'
            })
        
        user_id, reward_claimed = result
        
        if reward_claimed:
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Already Claimed', 
                'message': 'You have already claimed this reward.'
            })
        
        # Mark as claimed and update tracking info
        cursor.execute(
            "UPDATE shortlink_clicks SET reward_claimed = 1, ip_address = ?, user_agent = ? WHERE click_code = ?",
            (ip_address, user_agent, code)
        )
        
        # Get shortlink reward amount from settings
        cursor.execute("SELECT value FROM settings WHERE key = 'shortlink_reward_amount'")
        reward_result = cursor.fetchone()
        SHORTLINK_REWARD_AMOUNT = float(reward_result[0]) if reward_result else 0.0724
        
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (SHORTLINK_REWARD_AMOUNT, user_id)
        )
        
        # Log transaction
        cursor.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
            (user_id, 'shortlink_reward', SHORTLINK_REWARD_AMOUNT, 'Shortlink click reward')
        )
        
        conn.commit()
        conn.close()
        
        # Send notification to user via Telegram
        try:
            import requests
            
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            
            message = f"🎉 Shortlink Reward Claimed!\n\n" \
                     f"You earned: ₱{SHORTLINK_REWARD_AMOUNT:.2f}\n" \
                     f"Check your balance in the bot!"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': user_id,
                'text': message
            }
            requests.post(url, data=data, timeout=5)
        except Exception:
            pass  # Don't fail if notification fails
        
        return jsonify({
            'success': True, 
            'amount': SHORTLINK_REWARD_AMOUNT
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'title': 'Error', 
            'message': 'Unable to process reward. Please try again.'
        })

@app.route('/api/claim-watch-ads-reward', methods=['POST'])
def claim_watch_ads_reward():
    """Handle watch ads reward claiming from the ads page"""
    try:
        data = request.get_json()
        
        if not data or 'ad' not in data:
            return jsonify({
                'success': False, 
                'title': 'Invalid Request', 
                'message': 'No ad code provided'
            })
        
        ad_code = data['ad']
        ip_address = data.get('ip_address', '')
        user_agent = data.get('user_agent', '')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if ad code exists and not claimed
        cursor.execute(
            "SELECT user_id, reward_claimed FROM watch_ads WHERE ad_code = ?",
            (ad_code,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Invalid Link', 
                'message': 'This watch ads link is invalid or expired.'
            })
        
        user_id, reward_claimed = result
        
        if reward_claimed:
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Already Claimed', 
                'message': 'You have already claimed this reward.'
            })
        
        # Mark as claimed and update tracking info
        cursor.execute(
            "UPDATE watch_ads SET reward_claimed = 1, claimed_at = ?, ip_address = ?, user_agent = ? WHERE ad_code = ?",
            (datetime.now().isoformat(), ip_address, user_agent, ad_code)
        )
        
        # Get watch ads reward amount from settings
        cursor.execute("SELECT value FROM settings WHERE key = 'watch_ads_reward_amount'")
        reward_result = cursor.fetchone()
        WATCH_ADS_REWARD_AMOUNT = float(reward_result[0]) if reward_result else 0.0532
        
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (WATCH_ADS_REWARD_AMOUNT, user_id)
        )
        
        # Log transaction
        cursor.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
            (user_id, 'watch_ads_reward', WATCH_ADS_REWARD_AMOUNT, 'Watch ads reward')
        )
        
        conn.commit()
        conn.close()
        
        # Send notification to user via Telegram
        try:
            import requests
            
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            
            message = f"👁️ Watch Ads Reward Claimed!\n\n" \
                     f"You earned: ₱{WATCH_ADS_REWARD_AMOUNT:.2f}\n" \
                     f"Check your balance in the bot!"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': user_id,
                'text': message
            }
            requests.post(url, data=data, timeout=5)
        except Exception:
            pass  # Don't fail if notification fails
        
        return jsonify({
            'success': True, 
            'amount': WATCH_ADS_REWARD_AMOUNT
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'title': 'Error', 
            'message': 'Unable to process reward. Please try again.'
        })

@app.route('/api/claim-captcha-reward', methods=['POST'])
def claim_captcha_reward():
    """Handle captcha reward claiming from the reward page"""
    try:
        data = request.get_json()
        
        if not data or 'captcha' not in data:
            return jsonify({
                'success': False, 
                'title': 'Invalid Request', 
                'message': 'No captcha code provided'
            })
        
        captcha_code = data['captcha']
        ip_address = data.get('ip_address', '')
        user_agent = data.get('user_agent', '')
        
        conn = get_db()
        cursor = conn.cursor()
        
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
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Invalid Captcha', 
                'message': 'This captcha link is invalid or expired.'
            })
        
        session_id, link_number, completed, user_id, reward_amount = result
        
        if completed:
            conn.close()
            return jsonify({
                'success': False, 
                'title': 'Already Completed', 
                'message': 'You have already completed this captcha.'
            })
        
        # Mark captcha as completed
        cursor.execute(
            "UPDATE captcha_links SET completed = 1, completed_at = ?, ip_address = ?, user_agent = ? WHERE captcha_code = ?",
            (format_datetime(datetime.now().isoformat()), ip_address, user_agent, captcha_code)
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
        conn.close()
        
        # Send notification to user via Telegram
        try:
            import requests
            
            bot_token = '7776843072:AAG9LrfoUaes6ruNOrM56iNbxNTVZV-mVTM'
            
            if completed_count >= 10:
                message = f"🎉 Captcha Session Completed!\n\n" \
                         f"You completed captcha {link_number}/10\n" \
                         f"This session earned: ₱{reward_amount * 10:.2f}\n" \
                         f"Next session available in 24 hours!"
            else:
                message = f"🛡️ Captcha Completed!\n\n" \
                         f"You completed captcha {link_number}/10\n" \
                         f"You earned: ₱{reward_amount:.2f}\n" \
                         f"Progress: {completed_count}/10"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            notification_data = {
                'chat_id': user_id,
                'text': message
            }
            requests.post(url, data=notification_data, timeout=5)
        except Exception:
            pass  # Don't fail if notification fails
        
        return jsonify({
            'success': True, 
            'amount': reward_amount,
            'captcha_number': link_number,
            'completed_count': completed_count,
            'total_captchas': 10,
            'session_completed': completed_count >= 10
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'title': 'Error', 
            'message': 'Unable to process captcha. Please try again.'
        })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 6076))
    print(f"Starting web server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)