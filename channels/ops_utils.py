import time
import os
import signal

class OpsManager:
    """Manages operational controls like kill switch and user cool-down."""
    
    def __init__(self):
        self.muted_users = {}  # {user_id: mute_until_timestamp}
        self.cool_down_period = 60  # seconds
        
    def kill_switch(self):
        """Immediately terminate the bot process."""
        print("!!! KILL SWITCH ACTIVATED !!!")
        os.kill(os.getpid(), signal.SIGTERM)
        
    def mute_user(self, user_id, duration=300):
        """Mute a user for a specified duration (default 5 minutes)."""
        print(f"!!! ADMIN ACTION: Muting user {user_id} for {duration}s !!!")
        self.muted_users[user_id] = time.time() + duration
        
    def is_user_muted(self, user_id):
        """Check if a user is currently muted."""
        if user_id in self.muted_users:
            if time.time() < self.muted_users[user_id]:
                return True
            else:
                del self.muted_users[user_id]
        return False

_ops = OpsManager()

def activate_kill_switch():
    _ops.kill_switch()

def mute_user(user_id, duration=300):
    _ops.mute_user(user_id, duration)

def is_user_muted(user_id):
    return _ops.is_user_muted(user_id)
