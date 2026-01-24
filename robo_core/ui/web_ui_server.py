"""
Flask web server with WebSocket support for robot state visualization.
Serves a minimal web-based UI that shows robot state with simple text labels.
"""
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import threading
import webbrowser
import time
import logging
import queue

# Minimal HTML template for robot state - just text labels
ROBOT_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Johnny Robot Status</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Courier New', monospace;
            background: #000000;
            color: #ffffff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        
        .container {
            text-align: center;
            padding: 40px;
        }
        
        .robot-name {
            font-size: 24px;
            margin-bottom: 40px;
            color: #888888;
        }
        
        .state-label {
            font-size: 48px;
            font-weight: bold;
            margin-bottom: 20px;
        }
        
        .state-listening {
            color: #0099ff;
        }
        
        .state-talking {
            color: #00ff00;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="robot-name">JOHNNY</div>
        <div class="state-label" id="stateLabel">LISTENING</div>
    </div>
    
    <script>
        const socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });
        
        const stateLabel = document.getElementById('stateLabel');
        
        function updateState(state) {
            // Simple mapping: talking vs listening
            if (state === 'talking') {
                stateLabel.textContent = 'TALKING';
                stateLabel.className = 'state-label state-talking';
            } else {
                // All other states (ready, listening, thinking) -> LISTENING
                stateLabel.textContent = 'LISTENING';
                stateLabel.className = 'state-label state-listening';
            }
        }
        
        // Listen for state updates from server
        socket.on('state_update', function(data) {
            updateState(data.state);
        });
        
        // Handle connection
        socket.on('connect', function() {
            console.log('Connected to robot state server');
            socket.emit('get_state');
        });
        
        // Receive current state
        socket.on('current_state', function(data) {
            updateState(data.state);
        });
        
        // Handle disconnection
        socket.on('disconnect', function() {
            console.log('Disconnected from robot state server');
        });
    </script>
</body>
</html>
"""

class WebUIServer:
    """Flask server with WebSocket support for robot state UI."""
    
    def __init__(self, state_manager, port=5000, auto_open=True):
        """
        Initialize web UI server.
        
        Args:
            state_manager: RobotStateManager instance
            port: Port to run server on (default: 5000)
            auto_open: Automatically open browser (default: True)
        """
        self.state_manager = state_manager
        self.port = port
        self.auto_open = auto_open
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'robot-secret-key'
        
        # Suppress Flask and Socket.IO logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        self.socketio = SocketIO(
            self.app, 
            cors_allowed_origins="*",
            logger=False,
            engineio_logger=False,
            async_mode='threading',
            ping_timeout=60,
            ping_interval=25
        )
        
        # Setup routes
        self.app.add_url_rule('/', 'index', self.index)
        
        # Setup WebSocket events
        self.socketio.on_event('connect', self.handle_connect)
        self.socketio.on_event('get_state', self.handle_get_state)
        
        self.server_thread = None
        self.running = False
        self.state_queue = queue.Queue()
        self.emit_thread = None
    
    def index(self):
        """Serve the robot UI HTML page."""
        return render_template_string(ROBOT_UI_HTML)
    
    def handle_connect(self, *args):
        """Handle client connection."""
        try:
            state_info = self.state_manager.get_state_info()
            self.socketio.emit('current_state', state_info)
        except Exception as e:
            pass
    
    def handle_get_state(self, *args):
        """Handle WebSocket request for current state."""
        try:
            state_info = self.state_manager.get_state_info()
            self.socketio.emit('current_state', state_info)
        except Exception as e:
            pass
    
    def _emit_worker(self):
        """Background worker thread to emit state updates safely."""
        while self.running:
            try:
                state_value = self.state_queue.get(timeout=1.0)
                if self.socketio and self.running:
                    try:
                        with self.socketio.server.app.app_context():
                            self.socketio.emit('state_update', {'state': state_value}, namespace='/')
                    except (RuntimeError, AssertionError) as e:
                        if "start_response" not in str(e):
                            pass
                    except Exception:
                        pass
                self.state_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass
    
    def emit_state_update(self, state):
        """Emit state update to all connected clients (thread-safe)."""
        if self.running:
            try:
                self.state_queue.put_nowait(state.value)
            except queue.Full:
                pass
            except Exception:
                pass
    
    def start(self):
        """Start the Flask server in a background thread."""
        if self.running:
            return
        
        def run_server():
            self.running = True
            import logging
            log = logging.getLogger('werkzeug')
            log.setLevel(logging.CRITICAL)
            
            import sys
            
            class SuppressWSGIErrors:
                def __init__(self, original):
                    self.original = original
                def write(self, s):
                    msg = str(s)
                    if "write() before start_response" not in msg and "AssertionError" not in msg:
                        self.original.write(s)
                def flush(self):
                    self.original.flush()
            
            original_stderr = sys.stderr
            sys.stderr = SuppressWSGIErrors(original_stderr)
            
            try:
                self.emit_thread = threading.Thread(target=self._emit_worker, daemon=True)
                self.emit_thread.start()
                
                self.socketio.run(
                    self.app,
                    host='127.0.0.1',
                    port=self.port,
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True,
                    log_output=False
                )
            finally:
                sys.stderr = original_stderr
        
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        time.sleep(1)
        
        if self.auto_open:
            try:
                webbrowser.open(f'http://127.0.0.1:{self.port}')
            except Exception as e:
                print(f"Could not open browser automatically: {e}")
                print(f"Please open http://127.0.0.1:{self.port} in your browser")
        
        print(f"Robot web UI started at http://127.0.0.1:{self.port}")
    
    def stop(self):
        """Stop the Flask server."""
        self.running = False
