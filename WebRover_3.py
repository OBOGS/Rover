from flask import Flask, render_template_string, Response
from flask_socketio import SocketIO, emit
import RPi.GPIO as GPIO
import threading
import time
import json
import cv2
import base64
import io
from PIL import Image

# --- Constants ---
full_turn_steps = 128
DEADZONE = 0.2
MAX_SPEED_STEPS = 200

# --- GPIO SETUP ---
GPIO.setmode(GPIO.BCM)
left_motor_pins = [17, 18, 27, 22]
right_motor_pins = [5, 6, 13, 19]

for pin in left_motor_pins + right_motor_pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, False)

step_sequence = [
    [1, 0, 0, 1],
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1]
]

# --- Global thread management ---
current_threads = []
thread_stop_flags = []

# --- Camera Setup ---
camera = None
camera_active = False
camera_thread = None
camera_stop_flag = {'stop': False}

def initialize_camera():
    """Initialize the USB camera"""
    global camera
    try:
        # Try different camera indices (0, 1, 2) in case multiple cameras
        for i in range(3):
            test_camera = cv2.VideoCapture(i)
            if test_camera.isOpened():
                # Set camera properties for better performance
                test_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                test_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                test_camera.set(cv2.CAP_PROP_FPS, 15)  # Lower FPS for better network performance
                test_camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer for lower latency
                camera = test_camera
                print(f"Camera initialized on index {i}")
                return True
            test_camera.release()
        
        print("No camera found")
        return False
    except Exception as e:
        print(f"Error initializing camera: {e}")
        return False

def camera_stream():
    """Camera streaming function that runs in a separate thread"""
    global camera, camera_active, camera_stop_flag
    
    while not camera_stop_flag['stop']:
        try:
            if camera and camera.isOpened():
                ret, frame = camera.read()
                if ret:
                    # Resize frame for better network performance
                    frame = cv2.resize(frame, (480, 360))
                    
                    # Convert frame to JPEG
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    
                    # Convert to base64 for web transmission
                    frame_base64 = base64.b64encode(buffer).decode('utf-8')
                    
                    # Emit frame to all connected clients
                    socketio.emit('camera_frame', {'image': frame_base64})
                    
                    # Control frame rate
                    time.sleep(1/15)  # ~15 FPS
                else:
                    time.sleep(0.1)
            else:
                time.sleep(1)  # Wait if camera not available
        except Exception as e:
            print(f"Camera stream error: {e}")
            time.sleep(1)

def start_camera():
    """Start the camera stream"""
    global camera_active, camera_thread, camera_stop_flag
    
    if not camera_active and initialize_camera():
        camera_stop_flag['stop'] = False
        camera_thread = threading.Thread(target=camera_stream)
        camera_thread.daemon = True
        camera_thread.start()
        camera_active = True
        print("Camera stream started")
        return True
    return False

def stop_camera():
    """Stop the camera stream"""
    global camera, camera_active, camera_thread, camera_stop_flag
    
    camera_stop_flag['stop'] = True
    camera_active = False
    
    if camera_thread and camera_thread.is_alive():
        camera_thread.join(timeout=2.0)
    
    if camera:
        camera.release()
        camera = None
    
    print("Camera stream stopped")

def stop_all_threads():
    """Stop all running motor threads"""
    global current_threads, thread_stop_flags
    
    # Set all stop flags
    for flag in thread_stop_flags:
        flag['stop'] = True
    
    # Wait for all threads to finish
    for thread in current_threads:
        if thread.is_alive():
            thread.join(timeout=1.0)
    
    # Clear the lists
    current_threads.clear()
    thread_stop_flags.clear()

# --- Motor Control Functions ---
def move_motor(pins, step_count, delay=0.001, direction=1, stop_flag=None):
    """Move a single motor with stop flag support"""
    for _ in range(abs(step_count)):
        # Check stop flag
        if stop_flag and stop_flag.get('stop', False):
            break
            
        for step in range(8)[::direction]:
            # Check stop flag again for faster response
            if stop_flag and stop_flag.get('stop', False):
                break
                
            for pin in range(4):
                GPIO.output(pins[pin], step_sequence[step][pin])
            time.sleep(delay)
    
    # Turn off all pins when done
    for pin in pins:
        GPIO.output(pin, False)

def threaded_move(pins, steps, direction, stop_flag):
    """Create a thread for motor movement with stop flag"""
    return threading.Thread(target=move_motor, args=(pins, abs(steps), 0.001, direction, stop_flag))

def move_rover(left_steps, right_steps):
    """Move the rover with both motors"""
    global current_threads, thread_stop_flags
    
    # Stop any existing movement
    stop_all_threads()
    
    threads = []
    
    if left_steps != 0:
        left_direction = -1 if left_steps > 0 else 1
        left_stop_flag = {'stop': False}
        thread_stop_flags.append(left_stop_flag)
        left_thread = threaded_move(left_motor_pins, abs(left_steps), left_direction, left_stop_flag)
        threads.append(left_thread)
        current_threads.append(left_thread)
        left_thread.start()
    
    if right_steps != 0:
        right_direction = 1 if right_steps > 0 else -1
        right_stop_flag = {'stop': False}
        thread_stop_flags.append(right_stop_flag)
        right_thread = threaded_move(right_motor_pins, abs(right_steps), right_direction, right_stop_flag)
        threads.append(right_thread)
        current_threads.append(right_thread)
        right_thread.start()

def stop_motors():
    """Stop all motors immediately"""
    stop_all_threads()
    for pin in left_motor_pins + right_motor_pins:
        GPIO.output(pin, 0)

def apply_deadzone(value, deadzone=DEADZONE):
    if abs(value) < deadzone:
        return 0
    if value > 0:
        return (value - deadzone) / (1 - deadzone)
    else:
        return (value + deadzone) / (1 - deadzone)

# --- Flask App Setup ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Xbox Rover Control with Camera</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255,255,255,0.1);
            padding: 30px;
            border-radius: 15px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .status {
            background: rgba(255,255,255,0.2);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
            font-size: 1.2em;
        }
        .connected { background: rgba(34, 197, 94, 0.3); }
        .disconnected { background: rgba(239, 68, 68, 0.3); }
        
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .camera-section {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        
        .camera-container {
            position: relative;
            background: #000;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
            min-height: 300px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        #cameraFeed {
            max-width: 100%;
            max-height: 400px;
            border-radius: 10px;
            display: none;
        }
        
        .camera-placeholder {
            color: rgba(255,255,255,0.6);
            font-size: 1.1em;
        }
        
        .camera-controls {
            margin-top: 15px;
        }
        
        .camera-btn {
            padding: 10px 20px;
            margin: 5px;
            background: rgba(34, 197, 94, 0.3);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .camera-btn:hover {
            background: rgba(34, 197, 94, 0.5);
            transform: translateY(-2px);
        }
        
        .camera-btn.stop {
            background: rgba(239, 68, 68, 0.3);
        }
        
        .camera-btn.stop:hover {
            background: rgba(239, 68, 68, 0.5);
        }
        
        .controls {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }
        .control-section {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 10px;
        }
        .control-section h3 {
            margin-top: 0;
            border-bottom: 2px solid rgba(255,255,255,0.3);
            padding-bottom: 10px;
        }
        
        .joystick-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .joystick-display {
            width: 120px;
            height: 120px;
            border: 2px solid rgba(255,255,255,0.5);
            border-radius: 50%;
            position: relative;
            margin: 10px auto;
            background: rgba(255,255,255,0.1);
        }
        .joystick-dot {
            width: 16px;
            height: 16px;
            background: #fff;
            border-radius: 50%;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            transition: all 0.1s ease;
        }
        .button-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 10px;
        }
        .manual-btn {
            padding: 12px;
            background: rgba(255,255,255,0.2);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .manual-btn:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }
        .manual-btn:active {
            transform: translateY(0);
            background: rgba(255,255,255,0.4);
        }
        .info {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
            grid-column: 1 / -1;
        }
        .drive-mode {
            text-align: center;
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        @media (max-width: 768px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
            .joystick-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎮 Xbox Rover Control with 📹 Camera</h1>
        
        <div id="status" class="status disconnected">
            Xbox Controller: Not Connected
        </div>
        
        <div class="drive-mode" id="driveMode">
            Drive Mode: Tank Drive
        </div>
        
        <div class="main-grid">
            <div class="camera-section">
                <h3>🔴 Live Camera Feed</h3>
                <div class="camera-container">
                    <img id="cameraFeed" alt="Camera Feed">
                    <div id="cameraPlaceholder" class="camera-placeholder">
                        📹 Camera Not Active<br>
                        <small>Click "Start Camera" to begin streaming</small>
                    </div>
                </div>
                <div class="camera-controls">
                    <button class="camera-btn" onclick="startCamera()">▶️ Start Camera</button>
                    <button class="camera-btn stop" onclick="stopCamera()">⏹️ Stop Camera</button>
                </div>
                <div style="margin-top: 15px; font-size: 0.9em; opacity: 0.8;">
                    <div>Camera Status: <span id="cameraStatus">Stopped</span></div>
                </div>
            </div>
            
            <div class="controls">
                <div class="control-section">
                    <h3>Joysticks</h3>
                    <div class="joystick-grid">
                        <div>
                            <strong>Left Stick</strong>
                            <div class="joystick-display">
                                <div class="joystick-dot" id="leftStick"></div>
                            </div>
                            <div style="font-size: 0.8em;">
                                X: <span id="leftX">0.00</span><br>
                                Y: <span id="leftY">0.00</span>
                            </div>
                        </div>
                        
                        <div>
                            <strong>Right Stick</strong>
                            <div class="joystick-display">
                                <div class="joystick-dot" id="rightStick"></div>
                            </div>
                            <div style="font-size: 0.8em;">
                                X: <span id="rightX">0.00</span><br>
                                Y: <span id="rightY">0.00</span>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="control-section">
                    <h3>Manual Controls</h3>
                    <div class="button-grid">
                        <button class="manual-btn" onclick="sendCommand('forward')">⬆️ Forward</button>
                        <button class="manual-btn" onclick="sendCommand('backward')">⬇️ Backward</button>
                        <button class="manual-btn" onclick="sendCommand('stop')" style="background: rgba(239, 68, 68, 0.5);">🛑 Stop</button>
                        <button class="manual-btn" onclick="sendCommand('left')">⬅️ Left</button>
                        <button class="manual-btn" onclick="sendCommand('right')">➡️ Right</button>
                        <div></div> <!-- Empty cell for grid alignment -->
                    </div>
                </div>
            </div>
        </div>
        
        <div class="info">
            <h3>Instructions:</h3>
            <ul>
                <li><strong>Camera:</strong> Click "Start Camera" to begin live video streaming from the rover</li>
                <li><strong>Tank Drive (Default):</strong> Left stick = left motor, Right stick = right motor</li>
                <li><strong>Arcade Drive:</strong> Hold Left Trigger + Left stick for forward/back and turning</li>
                <li><strong>A Button:</strong> Emergency Stop</li>
                <li><strong>B Button:</strong> Forward</li>
                <li><strong>X Button:</strong> Backward</li>
                <li><strong>D-pad:</strong> Precise movements</li>
                <li><strong>Y Button:</strong> Toggle Camera On/Off</li>
            </ul>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <script>
        const socket = io();
        let gamepad = null;
        let animationId = null;
        let lastSendTime = 0;
        const SEND_INTERVAL = 50; // Send data every 50ms (20 FPS)
        let cameraActive = false;
        let lastYButtonState = false;
        
        // Gamepad connection
        window.addEventListener("gamepadconnected", (e) => {
            console.log("Gamepad connected:", e.gamepad);
            gamepad = e.gamepad;
            updateStatus(true);
            startGamepadLoop();
        });
        
        window.addEventListener("gamepaddisconnected", (e) => {
            console.log("Gamepad disconnected");
            gamepad = null;
            updateStatus(false);
            if (animationId) {
                cancelAnimationFrame(animationId);
            }
        });
        
        function updateStatus(connected) {
            const status = document.getElementById('status');
            if (connected) {
                status.textContent = `Xbox Controller: Connected (${gamepad.id})`;
                status.className = 'status connected';
            } else {
                status.textContent = 'Xbox Controller: Not Connected';
                status.className = 'status disconnected';
            }
        }
        
        function updateJoystickDisplay(stickId, x, y) {
            const stick = document.getElementById(stickId);
            const displayX = x * 52; // Scale to joystick display size
            const displayY = -y * 52; // Invert Y axis for display
            stick.style.transform = `translate(calc(-50% + ${displayX}px), calc(-50% + ${displayY}px))`;
        }
        
        function startGamepadLoop() {
            function gamepadLoop() {
                if (!gamepad) return;
                
                const currentTime = Date.now();
                
                // Get fresh gamepad state
                const gamepads = navigator.getGamepads();
                gamepad = gamepads[gamepad.index];
                
                if (!gamepad) return;
                
                // Read joysticks with safe defaults
                const leftX = gamepad.axes[0] || 0;
                const leftY = gamepad.axes[1] || 0;
                const rightX = gamepad.axes[2] || 0;
                const rightY = gamepad.axes[3] || 0;
                
                // Try different trigger mappings (varies by controller/browser)
                let leftTrigger = 0;
                if (gamepad.axes[6] !== undefined) {
                    leftTrigger = gamepad.axes[6];
                } else if (gamepad.axes[4] !== undefined) {
                    leftTrigger = gamepad.axes[4];
                } else if (gamepad.buttons[6] !== undefined) {
                    leftTrigger = gamepad.buttons[6].value;
                }
                
                // Update display every frame
                document.getElementById('leftX').textContent = leftX.toFixed(2);
                document.getElementById('leftY').textContent = leftY.toFixed(2);
                document.getElementById('rightX').textContent = rightX.toFixed(2);
                document.getElementById('rightY').textContent = rightY.toFixed(2);
                
                updateJoystickDisplay('leftStick', leftX, leftY);
                updateJoystickDisplay('rightStick', rightX, rightY);
                
                // Update drive mode
                const driveMode = leftTrigger > 0.5 ? 'Arcade Drive' : 'Tank Drive';
                document.getElementById('driveMode').textContent = `Drive Mode: ${driveMode}`;
                
                // Handle Y button for camera toggle
                const getButton = (index) => {
                    return gamepad.buttons[index] ? gamepad.buttons[index].pressed : false;
                };
                
                const yButtonPressed = getButton(3); // Y button
                if (yButtonPressed && !lastYButtonState) {
                    // Y button just pressed
                    if (cameraActive) {
                        stopCamera();
                    } else {
                        startCamera();
                    }
                }
                lastYButtonState = yButtonPressed;
                
                // Only send data at controlled intervals
                if (currentTime - lastSendTime >= SEND_INTERVAL) {
                    // Send controller data to server
                    socket.emit('controller_data', {
                        leftX: leftX,
                        leftY: -leftY, // Invert Y axis
                        rightX: rightX,
                        rightY: -rightY, // Invert Y axis
                        leftTrigger: leftTrigger,
                        buttons: {
                            A: getButton(0),
                            B: getButton(1),
                            X: getButton(2),
                            Y: getButton(3)
                        },
                        dpad: {
                            up: getButton(12),
                            down: getButton(13),
                            left: getButton(14),
                            right: getButton(15)
                        }
                    });
                    
                    lastSendTime = currentTime;
                }
                
                animationId = requestAnimationFrame(gamepadLoop);
            }
            gamepadLoop();
        }
        
        function sendCommand(command) {
            socket.emit('manual_command', { command: command });
        }
        
        function startCamera() {
            socket.emit('camera_command', { action: 'start' });
        }
        
        function stopCamera() {
            socket.emit('camera_command', { action: 'stop' });
        }
        
        // Socket events
        socket.on('connect', () => {
            console.log('Connected to server');
        });
        
        socket.on('rover_status', (data) => {
            console.log('Rover status:', data);
        });
        
        socket.on('camera_frame', (data) => {
            const img = document.getElementById('cameraFeed');
            const placeholder = document.getElementById('cameraPlaceholder');
            
            if (data.image) {
                img.src = 'data:image/jpeg;base64,' + data.image;
                img.style.display = 'block';
                placeholder.style.display = 'none';
                
                if (!cameraActive) {
                    cameraActive = true;
                    document.getElementById('cameraStatus').textContent = 'Active';
                }
            }
        });
        
        socket.on('camera_status', (data) => {
            const statusElement = document.getElementById('cameraStatus');
            const placeholder = document.getElementById('cameraPlaceholder');
            const img = document.getElementById('cameraFeed');
            
            if (data.status === 'started') {
                cameraActive = true;
                statusElement.textContent = 'Starting...';
            } else if (data.status === 'stopped') {
                cameraActive = false;
                statusElement.textContent = 'Stopped';
                img.style.display = 'none';
                placeholder.style.display = 'block';
            } else if (data.status === 'error') {
                cameraActive = false;
                statusElement.textContent = 'Error: ' + (data.message || 'Unknown error');
                img.style.display = 'none';
                placeholder.style.display = 'block';
                placeholder.innerHTML = '❌ Camera Error<br><small>' + (data.message || 'Check camera connection') + '</small>';
            }
        });
        
        // Initial gamepad check
        const gamepads = navigator.getGamepads();
        for (let i = 0; i < gamepads.length; i++) {
            if (gamepads[i]) {
                gamepad = gamepads[i];
                updateStatus(true);
                startGamepadLoop();
                break;
            }
        }
    </script>
</body>
</html>
"""

# --- WebSocket Event Handlers ---
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('rover_status', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    stop_motors()

@socketio.on('controller_data')
def handle_controller_data(data):
    try:
        # Button actions
        if data['buttons']['A']:  # Emergency stop
            stop_motors()
            return
        
        if data['buttons']['B']:  # Forward
            move_rover(full_turn_steps, full_turn_steps)
            return
            
        if data['buttons']['X']:  # Backward
            move_rover(-full_turn_steps, -full_turn_steps)
            return
        
        # D-pad actions
        if data['dpad']['up']:
            move_rover(full_turn_steps//4, full_turn_steps//4)
            return
        elif data['dpad']['down']:
            move_rover(-full_turn_steps//4, -full_turn_steps//4)
            return
        elif data['dpad']['left']:
            move_rover(-full_turn_steps//4, full_turn_steps//4)
            return
        elif data['dpad']['right']:
            move_rover(full_turn_steps//4, -full_turn_steps//4)
            return
        
        # Joystick control
        left_x = data['leftX']
        left_y = data['leftY']
        right_x = data['rightX']
        right_y = data['rightY']
        left_trigger = data['leftTrigger']
        
        # Determine drive mode
        if left_trigger > 0.5:  # Arcade drive
            forward = apply_deadzone(left_y)
            turn = apply_deadzone(left_x)
            
            left_power = forward + turn
            right_power = forward - turn
            
            max_power = max(abs(left_power), abs(right_power))
            if max_power > 1.0:
                left_power /= max_power
                right_power /= max_power
            
            left_steps = int(left_power * MAX_SPEED_STEPS)
            right_steps = int(right_power * MAX_SPEED_STEPS)
        else:  # Tank drive
            left_y = apply_deadzone(left_y)
            right_y = apply_deadzone(right_y)
            
            left_steps = int(left_y * MAX_SPEED_STEPS)
            right_steps = int(right_y * MAX_SPEED_STEPS)
        
        # Move rover if there's significant input
        if abs(left_steps) > 5 or abs(right_steps) > 5:
            move_rover(left_steps, right_steps)
            
    except Exception as e:
        print(f"Error processing controller data: {e}")

@socketio.on('manual_command')
def handle_manual_command(data):
    command = data['command']
    
    if command == 'forward':
        move_rover(full_turn_steps, full_turn_steps)
    elif command == 'backward':
        move_rover(-full_turn_steps, -full_turn_steps)
    elif command == 'left':
        move_rover(-full_turn_steps, full_turn_steps)
    elif command == 'right':
        move_rover(full_turn_steps, -full_turn_steps)
    elif command == 'stop':
        stop_motors()

@socketio.on('camera_command')
def handle_camera_command(data):
    action = data['action']
    
    if action == 'start':
        if start_camera():
            emit('camera_status', {'status': 'started'})
        else:
            emit('camera_status', {'status': 'error', 'message': 'Failed to initialize camera'})
    elif action == 'stop':
        stop_camera()
        emit('camera_status', {'status': 'stopped'})

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    try:
        print("Starting Xbox Rover Control Server with Camera...")
        print("Connect to http://[PI_IP_ADDRESS]:5000 from your laptop")
        print("Make sure your Xbox controller is connected to the laptop!")
        print("USB Camera will be auto-detected when you start streaming")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        stop_motors()
        stop_camera()
        GPIO.cleanup()