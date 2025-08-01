import keyboard

import threading

import time 

import RPi.GPIO as GPIO

# Setup
GPIO.setmode(GPIO.BCM)

# Motor 1 pins
left_motor_pins = [17, 18, 27, 22]
# Motor 2 pins
right_motor_pins = [5, 6, 13, 19]

for pin in left_motor_pins + right_motor_pins:
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

#def forward(steps):
 #   move_motor(left_motor_pins, steps, direction=1)
  #  move_motor(right_motor_pins, steps, direction=1)

#def backward(steps):
 #   move_motor(left_motor_pins, steps, direction=-1)
  #  move_motor(right_motor_pins, steps, direction=-1)

def forward(steps):
    left_thread = threading.Thread(target=move_motor, args=(left_motor_pins, steps, 0.001, 1))
    right_thread = threading.Thread(target=move_motor, args=(right_motor_pins, steps, 0.001, 1))
    left_thread.start()
    right_thread.start()
    left_thread.join()
    right_thread.join()

def backward(steps):
    left_thread = threading.Thread(target=move_motor, args=(left_motor_pins, steps, 0.001, -1))
    right_thread = threading.Thread(target=move_motor, args=(right_motor_pins, steps, 0.001, -1))
    left_thread.start()
    right_thread.start()
    left_thread.join()
    right_thread.join()


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
    
    print("forward")
    forward(512)
    print("backward")
    backward(512)
    
    print("did it work?")


finally:
    GPIO.cleanup()

def drive():
    print("Control the rover with WASD keys. Press 'q' to quit.")
    try:
        while True:
            if keyboard.is_pressed('w'):
                forward(512)
            elif keyboard.is_pressed('s'):
                backward(512)
            elif keyboard.is_pressed('a'):
                turn_left(512)
            elif keyboard.is_pressed('d'):
                turn_right(512)
            elif keyboard.is_pressed('q'):
                print("Quitting...")
                break
            else:
                stop()  # Stop motors if no key is pressed
            time.sleep(0.1)  # Add small delay to reduce CPU usage

    finally: 
        GPIO.cleanup

    

