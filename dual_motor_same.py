##insert code here##
import time 

import RPi.GPIO as GPIO

# Setup
GPIO.setmode(GPIO.BCM)

# Motor 1 pins
left_motor_pins = [17, 18, 27, 22]
# Motor 2 pins
right_motor_pins = [5, 6, 13, 19]

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

def move_motor(pins, step_count, delay=0.001, direction=1):
    for _ in range(step_count):
        for step in range(8)[::direction]:
            for pin in range(4):
                GPIO.output(pins[pin], step_sequence[step][pin])
            time.sleep(delay)

def forward(steps):
    move_motor(left_motor_pins, steps, direction=1)
    move_motor(right_motor_pins, steps, direction=1)

def backward(steps):
    move_motor(left_motor_pins, steps, direction=-1)
    move_motor(right_motor_pins, steps, direction=-1)

def turn_left(steps):
    move_motor(right_motor_pins, steps, direction=1)

def turn_right(steps):
    move_motor(left_motor_pins, steps, direction=1)

def stop():
    for pin in left_motor_pins + right_motor_pins:
        GPIO.output(pin, 0)

try:
    print("turn left")
    turn_left(512)
    time.sleep(1)
    print("turn right")
    turn_right(512)
    print("did it work?")

finally:
    GPIO.cleanup()
