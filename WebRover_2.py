from flask import Flask, render_template_string, request
import RPi.GPIO as GPIO
import threading
import time

full_turn_steps = 128

# --- GPIO and motor setup (reuse your functions from previous code) ---


# ... (copy motor functions here: move_motor, threaded_move, forward, etc.)

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

def move_motor(pins, step_count, delay=0.001, direction=1):
    for _ in range(step_count):
        for step in range(8)[::direction]:
            for pin in range(4):
                GPIO.output(pins[pin], step_sequence[step][pin])
            time.sleep(delay)

def threaded_move(pins, steps, direction):
    return threading.Thread(target=move_motor, args=(pins, steps, 0.001, direction))

def forward(steps):
    left = threaded_move(left_motor_pins, steps, -1)
    right = threaded_move(right_motor_pins, steps, 1)
    left.start()
    right.start()
    left.join()
    right.join()

def backward(steps):
    left = threaded_move(left_motor_pins, steps, 1)
    right = threaded_move(right_motor_pins, steps, -1)
    left.start()
    right.start()
    left.join()
    right.join()

def turn_left(steps):
    right = threaded_move(right_motor_pins, steps, 1)
    right.start()
    right.join()

def turn_right(steps):
    left = threaded_move(left_motor_pins, steps, -1)
    left.start()
    left.join()

def stop():
    for pin in left_motor_pins + right_motor_pins:
        GPIO.output(pin, 0)

# the above was copied from previous code

app = Flask(__name__)

HTML = """
<!doctype html>
<title>Rover Control</title>
<h1>Drive Rover</h1>
<form action="/" method="post">
    <button name="action" value="forward">Forward</button>
    <button name="action" value="backward">Backward</button>
    <button name="action" value="left">Left</button>
    <button name="action" value="right">Right</button>
    <button name="action" value="stop">Stop</button>
</form>
"""

@app.route('/', methods=['GET', 'POST'])
def control():
    if request.method == 'POST':
        action = request.form['action']
        if action == 'forward':
            forward(full_turn_steps)
        elif action == 'backward':
            backward(full_turn_steps)
        elif action == 'left':
            turn_left(full_turn_steps)
        elif action == 'right':
            turn_right(full_turn_steps)
        elif action == 'stop':
            stop()
    return render_template_string(HTML)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        GPIO.cleanup()
