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

# Enhanced HTML template with retro animations
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
            overflow: hidden;
        }
        
        .container {
            text-align: center;
            padding: 40px;
            position: relative;
        }
        
        .robot-name {
            font-size: 24px;
            margin-bottom: 20px;
            color: #888888;
            letter-spacing: 3px;
            text-shadow: 0 0 10px #888888;
        }
        
        .state-label {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 40px;
            letter-spacing: 2px;
            transition: all 0.3s ease;
        }
        
        .animation-container {
            position: relative;
            width: 400px;
            height: 200px;
            margin: 0 auto;
        }
        
        /* Listening Mode - Retro Signal Animation */
        .listening-signal {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 200px;
            height: 200px;
            border: 2px solid #0099ff;
            border-radius: 50%;
            opacity: 0;
            transition: opacity 0.5s ease;
        }
        
        .listening-signal.active {
            opacity: 1;
            animation: radarSweep 2s linear infinite;
        }
        
        .listening-signal::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 120px;
            height: 120px;
            border: 1px solid #0099ff;
            border-radius: 50%;
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        .listening-signal::after {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(0deg);
            width: 90px;
            height: 2px;
            background: linear-gradient(to right, transparent, #0099ff, transparent);
            animation: sweep 2s linear infinite;
            transform-origin: 0 50%;
        }
        
        .crosshairs {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 200px;
            height: 200px;
            opacity: 0.6;
        }
        
        .crosshairs::before,
        .crosshairs::after {
            content: '';
            position: absolute;
            background: #0099ff;
            opacity: 0.3;
        }
        
        .crosshairs::before {
            top: 50%;
            left: 0;
            width: 100%;
            height: 1px;
            transform: translateY(-50%);
        }
        
        .crosshairs::after {
            top: 0;
            left: 50%;
            width: 1px;
            height: 100%;
            transform: translateX(-50%);
        }
        
        /* Talking Mode - Retro Soundwave Animation */
        .soundwave-container {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            opacity: 0;
            transition: opacity 0.5s ease;
        }
        
        .soundwave-container.active {
            opacity: 1;
        }
        
        .soundwave-bar {
            width: 6px;
            background: #00ff00;
            border-radius: 3px;
            animation: soundwave 0.8s ease-in-out infinite;
            box-shadow: 0 0 10px #00ff00;
        }
        
        .soundwave-bar:nth-child(1) { height: 20px; animation-delay: 0s; }
        .soundwave-bar:nth-child(2) { height: 40px; animation-delay: 0.1s; }
        .soundwave-bar:nth-child(3) { height: 60px; animation-delay: 0.2s; }
        .soundwave-bar:nth-child(4) { height: 80px; animation-delay: 0.3s; }
        .soundwave-bar:nth-child(5) { height: 100px; animation-delay: 0.4s; }
        .soundwave-bar:nth-child(6) { height: 120px; animation-delay: 0.5s; }
        .soundwave-bar:nth-child(7) { height: 100px; animation-delay: 0.6s; }
        .soundwave-bar:nth-child(8) { height: 80px; animation-delay: 0.7s; }
        .soundwave-bar:nth-child(9) { height: 60px; animation-delay: 0.8s; }
        .soundwave-bar:nth-child(10) { height: 40px; animation-delay: 0.9s; }
        .soundwave-bar:nth-child(11) { height: 20px; animation-delay: 1s; }
        
        .spectrogram-line {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(to right, 
                transparent, 
                #00ff00 20%, 
                #ffff00 40%, 
                #ff8800 60%, 
                #ff0000 80%, 
                transparent
            );
            animation: spectrogram 1.5s linear infinite;
        }
        
        /* State-specific styling */
        .state-listening {
            color: #0099ff;
            text-shadow: 0 0 20px #0099ff;
        }
        
        .state-talking {
            color: #00ff00;
            text-shadow: 0 0 20px #00ff00;
        }
        
        /* Keyframe animations */
        @keyframes radarSweep {
            0% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
            50% { transform: translate(-50%, -50%) scale(1.1); opacity: 0.7; }
            100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
        }
        
        @keyframes pulse {
            0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.8; }
            50% { transform: translate(-50%, -50%) scale(1.2); opacity: 0.4; }
        }
        
        @keyframes sweep {
            0% { transform: translate(-50%, -50%) rotate(0deg); opacity: 1; }
            90% { transform: translate(-50%, -50%) rotate(360deg); opacity: 1; }
            100% { transform: translate(-50%, -50%) rotate(360deg); opacity: 0; }
        }
        
        @keyframes soundwave {
            0%, 100% { transform: scaleY(0.3); opacity: 0.8; }
            50% { transform: scaleY(1); opacity: 1; }
        }
        
        @keyframes spectrogram {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        
        /* Glitch effect for transitions */
        .transition-glitch {
            animation: glitch 0.1s ease-in-out;
        }
        
        @keyframes glitch {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-1px); }
            75% { transform: translateX(1px); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="robot-name">JOHNNY</div>
        <div class="state-label" id="stateLabel">LISTENING</div>
        
        <div class="animation-container">
            <!-- Listening Animation -->
            <div class="listening-signal active" id="listeningSignal">
                <div class="crosshairs"></div>
            </div>
            
            <!-- Talking Animation -->
            <div class="soundwave-container" id="soundwaveContainer">
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="soundwave-bar"></div>
                <div class="spectrogram-line"></div>
            </div>
        </div>
    </div>
    
    <script>
        const socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });
        
        const stateLabel = document.getElementById('stateLabel');
        const listeningSignal = document.getElementById('listeningSignal');
        const soundwaveContainer = document.getElementById('soundwaveContainer');
        
        function updateState(state) {
            // Add brief glitch effect during transition
            stateLabel.classList.add('transition-glitch');
            setTimeout(() => stateLabel.classList.remove('transition-glitch'), 100);
            
            if (state === 'talking') {
                // Switch to talking mode
                stateLabel.textContent = 'TALKING';
                stateLabel.className = 'state-label state-talking';
                
                // Show soundwave, hide listening signal
                listeningSignal.classList.remove('active');
                soundwaveContainer.classList.add('active');
                
            } else {
                // All other states (ready, listening, thinking) -> LISTENING
                stateLabel.textContent = 'LISTENING';
                stateLabel.className = 'state-label state-listening';
                
                // Show listening signal, hide soundwave
                listeningSignal.classList.add('active');
                soundwaveContainer.classList.remove('active');
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
            // Default to listening state when disconnected
            updateState('listening');
        });
        
        // Initialize with listening state
        updateState('listening');
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
