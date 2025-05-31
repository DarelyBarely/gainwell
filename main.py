import subprocess
import sys
import os
import time
import signal

def kill_existing_processes():
    """Kill any existing bot or web processes"""
    try:
        # Kill any existing Python processes that might be running the bot or web server
        os.system("pkill -f 'gainwell.py'")
        os.system("pkill -f 'admin_web.py'")
        time.sleep(2)  # Give processes time to terminate
    except Exception as e:
        print(f"Note: {e}")

def run_script(script_name, port=None):
    """Run a Python script in a separate process."""
    env = os.environ.copy()
    if port:
        env['PORT'] = str(port)
    return subprocess.Popen([sys.executable, os.path.join('gainwellbot', script_name)], env=env)

if __name__ == "__main__":
    print("Initializing GainWell Bot system...")

    # Clean up any existing processes first
    print("Cleaning up existing processes...")
    kill_existing_processes()

    print("Starting GainWell Bot and Admin Web Interface...")

    # Start the Admin Web Interface first (with port 6076)
    print("Starting Admin Web Interface on port 6076...")
    web_process = run_script("admin_web.py", 6076)

    # Wait a moment for the web server to start
    time.sleep(3)

    # Start the Telegram bot
    print("Starting Telegram bot...")
    bot_process = run_script("gainwell.py")

    print("\n" + "="*50)
    print("🎉 GainWell Bot System Started Successfully!")
    print("="*50)
    print(f"📱 Telegram Bot: Active")
    print(f"🌐 Web Admin: http://0.0.0.0:6076/@dminpanel")
    print(f"🎁 Reward Page: Available at /reward.html")
    print(f"🔗 Your App URL: https://{os.getenv('REPL_SLUG', 'your-app')}-{os.getenv('REPL_OWNER', 'user')}.replit.app")
    print("="*50)

    def signal_handler(signum, frame):
        print("\n\nShutting down GainWell Bot system...")
        try:
            bot_process.terminate()
            web_process.terminate()
            bot_process.wait(timeout=5)
            web_process.wait(timeout=5)
        except:
            bot_process.kill()
            web_process.kill()
        print("System shutdown complete.")
        sys.exit(0)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Keep the main process alive and monitor subprocesses
        while True:
            time.sleep(10)

            # Check if processes are still running
            if bot_process.poll() is not None:
                print("⚠️ Telegram bot stopped unexpectedly. Restarting...")
                bot_process = run_script("gainwell.py")

            if web_process.poll() is not None:
                print("⚠️ Web server stopped unexpectedly. Restarting...")
                web_process = run_script("admin_web.py", 6076)

    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)