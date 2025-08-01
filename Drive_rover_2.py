import pygame
import threading
import time
import RPi.GPIO as GPIO

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
    left = threaded_move(left_motor_pins, steps, 1)
    right = threaded_move(right_motor_pins, steps, 1)
    left.start()
    right.start()
    left.join()
    right.join()

def backward(steps):
    left = threaded_move(left_motor_pins, steps, -1)
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
    left = threaded_move(left_motor_pins, steps, 1)
    left.start()
    left.join()

def stop():
    for pin in left_motor_pins + right_motor_pins:
        GPIO.output(pin, 0)

# --- PYGAME SETUP ---
pygame.init()
screen = pygame.display.set_mode((300, 300))
pygame.display.set_caption("Rover Control")

running = True
step_size = 128  # Smaller steps for smoother control

try:
    print("Use W/A/S/D to drive. ESC to exit.")
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()

        if keys[pygame.K_w]:
            forward(step_size)
        elif keys[pygame.K_s]:
            backward(step_size)
        elif keys[pygame.K_a]:
            turn_left(step_size)
        elif keys[pygame.K_d]:
            turn_right(step_size)
        else:
            stop()

        pygame.display.flip()

finally:
    GPIO.cleanup()
    pygame.quit()
