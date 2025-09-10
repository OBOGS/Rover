from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import RPi.GPIO as GPIO
import threading
import time
import json

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

# --- Motor Control Functions ---
def move_motor(pins, step_count, delay=0.001, direction=1):
    for _ in range(abs(step_count)):
        for step in range(8)[::direction]:
            for pin in range(4):
                GPIO.output(pins[pin], step_sequence[step][pin])
            time.sleep(delay)

def threaded_move(pins, steps, direction):
    return threading.Thread(target=move_motor, args=(pins, abs(steps), 0.001, direction))

def move_rover(left_steps, right_steps):
    threads = []
    
    if left_steps != 0:
        left_direction = -1 if left_steps > 0 else 1
        left_thread = threaded_move(left_motor_pins, abs(left_steps), left_direction)
        threads.append(left_thread)
        left_thread.start()
    
    if right_steps != 0:
        right_direction = 1 if right_steps > 0 else -1
        right_thread = threaded_move(right_motor_pins, abs(right_steps), right_direction)
        threads.append(right_thread)
        right_thread.start()
    
    for thread in threads:
        thread.join()

def stop_motors():
    """Stop all motors immediately"""
    global current_threads
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
    <title>Xbox Rover Control</title>
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
            max-width: 800px;
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
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
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
        .joystick-display {
            width: 150px;
            height: 150px;
            border: 2px solid rgba(255,255,255,0.5);
            border-radius: 50%;
            position: relative;
            margin: 10px auto;
            background: rgba(255,255,255,0.1);
        }
        .joystick-dot {
            width: 20px;
            height: 20px;
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
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-top: 10px;
        }
        .manual-btn {
            padding: 15px;
            background: rgba(255,255,255,0.2);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 16px;
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
        }
        .drive-mode {
            text-align: center;
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎮 Xbox Rover Control</h1>
        
        <div id="status" class="status disconnected">
            Xbox Controller: Not Connected
        </div>
        
        <div class="drive-mode" id="driveMode">
            Drive Mode: Tank Drive
        </div>
        
        <div class="controls">
            <div class="control-section">
                <h3>Left Stick</h3>
                <div class="joystick-display">
                    <div class="joystick-dot" id="leftStick"></div>
                </div>
                <div>X: <span id="leftX">0.00</span></div>
                <div>Y: <span id="leftY">0.00</span></div>
            </div>
            
            <div class="control-section">
                <h3>Right Stick</h3>
                <div class="joystick-display">
                    <div class="joystick-dot" id="rightStick"></div>
                </div>
                <div>X: <span id="rightX">0.00</span></div>
                <div>Y: <span id="rightY">0.00</span></div>
            </div>
        </div>
        
        <div class="control-section">
            <h3>Manual Controls</h3>
            <div class="button-grid">
                <button class="manual-btn" onclick="sendCommand('forward')">⬆️ Forward</button>
                <button class="manual-btn" onclick="sendCommand('backward')">⬇️ Backward</button>
                <button class="manual-btn" onclick="sendCommand('left')">⬅️ Left</button>
                <button class="manual-btn" onclick="sendCommand('right')">➡️ Right</button>
                <button class="manual-btn" onclick="sendCommand('stop')" style="background: rgba(239, 68, 68, 0.5);">🛑 Stop</button>
            </div>
        </div>
        
        <div class="info">
            <h3>Instructions:</h3>
            <ul>
                <li><strong>Tank Drive (Default):</strong> Left stick = left motor, Right stick = right motor</li>
                <li><strong>Arcade Drive:</strong> Hold Left Trigger + Left stick for forward/back and turning</li>
                <li><strong>A Button:</strong> Emergency Stop</li>
                <li><strong>B Button:</strong> Forward</li>
                <li><strong>X Button:</strong> Backward</li>
                <li><strong>D-pad:</strong> Precise movements</li>
            </ul>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <script>
        const socket = io();
        let gamepad = null;
        let animationId = null;
        
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
            const displayX = x * 65; // Scale to joystick display size
            const displayY = -y * 65; // Invert Y axis for display
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
                
                // Only send data at controlled intervals
                if (currentTime - lastSendTime >= SEND_INTERVAL) {
                    // Safe button reading
                    const getButton = (index) => {
                        return gamepad.buttons[index] ? gamepad.buttons[index].pressed : false;
                    };
                    
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
        
        // Socket events
        socket.on('connect', () => {
            console.log('Connected to server');
        });
        
        socket.on('rover_status', (data) => {
            console.log('Rover status:', data);
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

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    try:
        print("Starting Xbox Rover Control Server...")
        print("Connect to http://[PI_IP_ADDRESS]:5000 from your laptop")
        print("Make sure your Xbox controller is connected to the laptop!")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        stop_motors()
        GPIO.cleanup()
