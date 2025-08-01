import time
import RPi.GPIO as GPIO

# Setup
GPIO.setmode(GPIO.BCM)

# Motor 1 pins
motor1_pins = [17, 18, 27, 22]
# Motor 2 pins
motor2_pins = [5, 6, 13, 19]

for pin in motor1_pins + motor2_pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, False)

# Step sequence for 28BYJ-48
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

def move_motor(pins, steps, delay=0.001, direction=1):
    for _ in range(steps):
        for step in range(8)[::direction]:
            for pin in range(4):
                GPIO.output(pins[pin], step_sequence[step][pin])
            time.sleep(delay)

try:
    print("Spinning motors forward...")
    move_motor(motor1_pins, 512)  # 512 steps = ~1 rev
    move_motor(motor2_pins, 512)
    time.sleep(1)
    
    print("Spinning motors backward...")
    move_motor(motor1_pins, 512, direction=-1)
    move_motor(motor2_pins, 512, direction=-1)

finally:
    GPIO.cleanup()
