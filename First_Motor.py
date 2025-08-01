import time
import RPi.GPIO as GPIO

motor_pins = [17, 18, 27, 22]

GPIO.setmode(GPIO.BCM)
GPIO.setup(motor_pins, GPIO.OUT)

step_sequence = [
    [1, 0, 0, 1],
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1]
    ]

def step_motor(steps, delay=0.001):
    if steps > 0:
        sequence = step_sequence
    else: 
        sequence = step_sequence[::-1]
        
    for _ in range(abs(steps)):
        for step in sequence:
            for pin in range(4):
                GPIO.output(motor_pins[pin], step[pin])
                time.sleep(delay)
                
try:
    while True:
        step_motor(512)
        time.sleep(1)
        step_motor(-512)
        time.sleep(1)
                        
except KeyboardInterrupt:
    GPIO.cleanup()
