"""
Flask web server with WebSocket support for robot state visualization.
Serves a web-based UI that shows robot state with sophisticated robotic face animations.
"""
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import threading
import webbrowser
import time
import logging
import queue

# HTML template for robot UI interface with sophisticated robotic face
ROBOT_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Johnny Hugenschmidt - Robot Interface</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #2d3561 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            overflow: hidden;
            color: #ffffff;
        }
        
        .container {
            text-align: center;
            padding: 40px;
            background: rgba(15, 20, 40, 0.6);
            border-radius: 30px;
            backdrop-filter: blur(20px);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5),
                        0 0 0 1px rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .robot-name {
            color: #00d4ff;
            font-size: 2.2em;
            font-weight: 700;
            margin-bottom: 40px;
            text-shadow: 0 0 20px rgba(0, 212, 255, 0.5),
                         0 0 40px rgba(0, 212, 255, 0.3);
            letter-spacing: 2px;
        }
        
        .robot-face-container {
            width: 320px;
            height: 320px;
            margin: 0 auto 40px;
            position: relative;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .robot-face {
            width: 280px;
            height: 280px;
            position: relative;
            filter: drop-shadow(0 0 30px rgba(0, 212, 255, 0.4));
        }
        
        /* Robotic Head - Metallic with sophisticated design */
        .robot-head {
            fill: url(#metalGradient);
            stroke: #00d4ff;
            stroke-width: 2;
            filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
        }
        
        /* Eyes - Animated with glow */
        .robot-eye {
            fill: #00d4ff;
            filter: drop-shadow(0 0 10px rgba(0, 212, 255, 0.8));
            transition: all 0.3s ease;
        }
        
        .robot-eye-pupil {
            fill: #ffffff;
            transition: all 0.2s ease;
        }
        
        /* Mouth/Display Panel */
        .robot-mouth {
            fill: url(#displayGradient);
            stroke: #00d4ff;
            stroke-width: 1.5;
            opacity: 0.8;
        }
        
        /* Status Indicator Lights */
        .status-light {
            fill: #00d4ff;
            filter: drop-shadow(0 0 8px rgba(0, 212, 255, 0.6));
            opacity: 0.6;
        }
        
        /* READY State - Gentle pulsing glow */
        .state-ready .robot-eye {
            animation: readyGlow 3s ease-in-out infinite;
        }
        
        .state-ready .status-light {
            animation: readyPulse 2s ease-in-out infinite;
        }
        
        /* LISTENING State - Active scanning */
        .state-listening .robot-eye {
            animation: listeningScan 1.5s ease-in-out infinite;
            filter: drop-shadow(0 0 15px rgba(0, 212, 255, 1));
        }
        
        .state-listening .robot-eye-pupil {
            animation: listeningPupil 1.2s ease-in-out infinite;
        }
        
        .state-listening .status-light {
            animation: listeningPulse 0.8s ease-in-out infinite;
            opacity: 1;
        }
        
        .state-listening .robot-head {
            animation: listeningHead 2s ease-in-out infinite;
        }
        
        /* THINKING State - Processing animation */
        .state-thinking .robot-eye {
            animation: thinkingProcess 1s ease-in-out infinite;
            filter: drop-shadow(0 0 20px rgba(155, 89, 255, 0.9));
        }
        
        .state-thinking .robot-mouth {
            animation: thinkingMouth 1.5s ease-in-out infinite;
        }
        
        .state-thinking .status-light {
            animation: thinkingPulse 0.6s ease-in-out infinite;
            fill: #9b59ff;
        }
        
        /* TALKING State - Speaking animation */
        .state-talking .robot-mouth {
            animation: talkingMouth 0.4s ease-in-out infinite;
        }
        
        .state-talking .robot-eye {
            animation: talkingEyes 2s ease-in-out infinite;
        }
        
        .state-talking .status-light {
            animation: talkingPulse 0.5s ease-in-out infinite;
            fill: #00ff88;
        }
        
        .state-label {
            color: #00d4ff;
            font-size: 1.6em;
            font-weight: 600;
            margin-bottom: 12px;
            text-shadow: 0 0 15px rgba(0, 212, 255, 0.5);
            text-transform: uppercase;
            letter-spacing: 3px;
        }
        
        .status-text {
            color: rgba(255, 255, 255, 0.7);
            font-size: 1.1em;
            font-weight: 300;
            letter-spacing: 1px;
        }
        
        /* Animations */
        @keyframes readyGlow {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; }
        }
        
        @keyframes readyPulse {
            0%, 100% { opacity: 0.4; transform: scale(1); }
            50% { opacity: 0.8; transform: scale(1.1); }
        }
        
        @keyframes listeningScan {
            0%, 100% { transform: translateX(0); opacity: 0.8; }
            25% { transform: translateX(-3px); opacity: 1; }
            75% { transform: translateX(3px); opacity: 1; }
        }
        
        @keyframes listeningPupil {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.2); }
        }
        
        @keyframes listeningPulse {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; }
        }
        
        @keyframes listeningHead {
            0%, 100% { transform: rotate(0deg); }
            25% { transform: rotate(-2deg); }
            75% { transform: rotate(2deg); }
        }
        
        @keyframes thinkingProcess {
            0%, 100% { opacity: 0.7; transform: scale(1); }
            25% { opacity: 1; transform: scale(1.1); }
            50% { opacity: 0.9; transform: scale(1); }
            75% { opacity: 1; transform: scale(1.05); }
        }
        
        @keyframes thinkingMouth {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 0.9; }
        }
        
        @keyframes thinkingPulse {
            0%, 100% { opacity: 0.5; }
            50% { opacity: 1; }
        }
        
        @keyframes talkingMouth {
            0%, 100% { transform: scaleY(1); }
            50% { transform: scaleY(1.3); }
        }
        
        @keyframes talkingEyes {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.8; }
        }
        
        @keyframes talkingPulse {
            0%, 100% { opacity: 0.7; }
            50% { opacity: 1; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="robot-name">JOHNNY HUGENSCHMIDT</div>
        <div class="robot-face-container">
            <svg class="robot-face" viewBox="0 0 200 200" id="robotFace">
                <defs>
                    <linearGradient id="metalGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#2a3a5a;stop-opacity:1" />
                        <stop offset="50%" style="stop-color:#1a2538;stop-opacity:1" />
                        <stop offset="100%" style="stop-color:#0f141f;stop-opacity:1" />
                    </linearGradient>
                    <linearGradient id="displayGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#00d4ff;stop-opacity:0.3" />
                        <stop offset="100%" style="stop-color:#0099cc;stop-opacity:0.1" />
                    </linearGradient>
                </defs>
                
                <!-- Robotic Head -->
                <ellipse class="robot-head" cx="100" cy="100" rx="85" ry="95"/>
                
                <!-- Eyes -->
                <g class="robot-eyes">
                    <circle class="robot-eye" cx="75" cy="85" r="12"/>
                    <circle class="robot-eye-pupil" cx="75" cy="85" r="6"/>
                    <circle class="robot-eye" cx="125" cy="85" r="12"/>
                    <circle class="robot-eye-pupil" cx="125" cy="85" r="6"/>
                </g>
                
                <!-- Mouth/Display Panel -->
                <ellipse class="robot-mouth" cx="100" cy="135" rx="35" ry="15"/>
                
                <!-- Status Indicator Lights -->
                <circle class="status-light" cx="100" cy="50" r="4"/>
                <circle class="status-light" cx="85" cy="45" r="3"/>
                <circle class="status-light" cx="115" cy="45" r="3"/>
                
                <!-- Decorative Tech Lines -->
                <line x1="60" y1="70" x2="80" y2="70" stroke="#00d4ff" stroke-width="1" opacity="0.3"/>
                <line x1="120" y1="70" x2="140" y2="70" stroke="#00d4ff" stroke-width="1" opacity="0.3"/>
                <line x1="70" y1="155" x2="130" y2="155" stroke="#00d4ff" stroke-width="1" opacity="0.2"/>
            </svg>
        </div>
        <div class="state-label" id="stateLabel">READY</div>
        <div class="status-text" id="statusText">Standing by...</div>
    </div>
    
    <script>
        const socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });
        
        const stateMap = {
            'ready': {
                label: 'READY',
                status: 'Standing by...',
                class: 'state-ready'
            },
            'listening': {
                label: 'LISTENING',
                status: 'Processing audio input...',
                class: 'state-listening'
            },
            'thinking': {
                label: 'THINKING',
                status: 'Analyzing and generating response...',
                class: 'state-thinking'
            },
            'talking': {
                label: 'TALKING',
                status: 'Speaking...',
                class: 'state-talking'
            }
        };
        
        const robotFace = document.getElementById('robotFace');
        const stateLabel = document.getElementById('stateLabel');
        const statusText = document.getElementById('statusText');
        
        function updateState(state) {
            const stateInfo = stateMap[state];
            if (!stateInfo) return;
            
            // Remove all state classes
            robotFace.className = 'robot-face';
            
            // Add new state class
            robotFace.classList.add(stateInfo.class);
            
            // Update label and status
            stateLabel.textContent = stateInfo.label;
            statusText.textContent = stateInfo.status;
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
