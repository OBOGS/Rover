from flask import Flask, render_template_string, request
import RPi.GPIO as GPIO
import threading
import time

# --- GPIO and motor setup (reuse your functions from previous code) ---


# ... (copy motor functions here: move_motor, threaded_move, forward, etc.)

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
            forward(128)
        elif action == 'backward':
            backward(128)
        elif action == 'left':
            turn_left(128)
        elif action == 'right':
            turn_right(128)
        elif action == 'stop':
            stop()
    return render_template_string(HTML)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        GPIO.cleanup()
