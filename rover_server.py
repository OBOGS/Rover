#!/usr/bin/env python3
"""
Mars Rover Control System - Backend Server (Tank Drive + USB Camera)
This runs on your Raspberry Pi 4

NEW FEATURES:
- Tank drive: Left stick controls left motor, right stick controls right motor
- USB camera support with MJPEG streaming
- Variable speed control based on joystick position
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
import threading

# Web framework and WebSocket support
from aiohttp import web
import aiohttp_cors

# Raspberry Pi GPIO control
try:
    import RPi.GPIO as GPIO
except ImportError:
    print("WARNING: RPi.GPIO not available. Running in simulation mode.")
    GPIO = None

# USB Camera support
try:
    import cv2
except ImportError:
    print("WARNING: opencv-python not available. Camera disabled.")
    cv2 = None

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StepperMotor:
    """
    Controls a single 28BYJ-48 stepper motor with variable speed
    
    NEW: Added speed control for tank drive
    """
    
    STEP_SEQUENCE = [
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
        [1, 0, 0, 1]
    ]
    
    def __init__(self, pins: List[int], name: str = "Motor"):
        self.pins = pins
        self.name = name
        self.current_step = 0
        self.is_running = False
        self.current_speed = 0.0  # -1.0 to 1.0
        self.motor_task = None
        self.setup_gpio()
    
    def setup_gpio(self):
        """Configure GPIO pins for output"""
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            for pin in self.pins:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
    
    def step(self, direction: int = 1):
        """Move motor one step"""
        self.current_step = (self.current_step + direction) % len(self.STEP_SEQUENCE)
        step_pattern = self.STEP_SEQUENCE[self.current_step]
        
        if GPIO:
            for pin, value in zip(self.pins, step_pattern):
                GPIO.output(pin, value)
    
    async def run_at_speed(self, speed: float):
        """
        Run motor continuously at specified speed
        
        Args:
            speed: -1.0 (full reverse) to 1.0 (full forward), 0.0 = stop
        
        LEARNING POINT: Tank drive needs independent motor control
        Each motor runs at its own speed based on joystick position
        """
        self.current_speed = speed
        self.is_running = True
        
        # Calculate delay based on speed (faster = shorter delay)
        # Base delay of 3ms at full speed
        if abs(speed) < 0.1:  # Deadzone
            self.stop()
            return
        
        base_delay = 0.001
        delay = base_delay / abs(speed)
        direction = 1 if speed > 0 else -1
        
        logger.debug(f"{self.name} running at speed {speed:.2f} (delay: {delay:.4f}s)")
        
        while self.is_running and abs(self.current_speed) > 0.1:
            self.step(direction)
            await asyncio.sleep(delay)
    
    def stop(self):
        """Stop motor and turn off all coils"""
        self.is_running = False
        self.current_speed = 0.0
        if GPIO:
            for pin in self.pins:
                GPIO.output(pin, GPIO.LOW)


class RoverMotorController:
    """
    Tank Drive Controller - Independent control of each motor
    
    LEARNING POINT: Tank drive gives you precise control
    - Push both sticks forward = straight ahead
    - Left stick forward, right stick back = spin right
    - Different speeds on each side = curved turns
    """
    
    def __init__(self, left_pins: List[int], right_pins: List[int]):
        self.left_motor = StepperMotor(left_pins, "Left Motor")
        self.right_motor = StepperMotor(right_pins, "Right Motor")
        self.left_task: Optional[asyncio.Task] = None
        self.right_task: Optional[asyncio.Task] = None
    
    def set_tank_drive(self, left_speed: float, right_speed: float):
        """
        Set speeds for tank drive control
        
        Args:
            left_speed: -1.0 to 1.0 for left motor
            right_speed: -1.0 to 1.0 for right motor
        
        LEARNING POINT: This is called continuously as joysticks move
        We cancel old tasks and start new ones at updated speeds
        """
        # Cancel existing tasks
        if self.left_task and not self.left_task.done():
            self.left_task.cancel()
        if self.right_task and not self.right_task.done():
            self.right_task.cancel()
        
        # Start new tasks at specified speeds
        self.left_task = asyncio.create_task(self.left_motor.run_at_speed(left_speed))
        self.right_task = asyncio.create_task(self.right_motor.run_at_speed(right_speed))
    
    async def move_forward(self, speed: float = 0.003):
        """Move rover forward - both motors same direction (for button control)"""
        self.set_tank_drive(1.0, 1.0)
    
    async def move_backward(self, speed: float = 0.003):
        """Move rover backward (for button control)"""
        self.set_tank_drive(-1.0, -1.0)
    
    async def turn_left(self, speed: float = 0.003):
        """Turn left (for button control)"""
        self.set_tank_drive(-0.5, 0.5)
    
    async def turn_right(self, speed: float = 0.003):
        """Turn right (for button control)"""
        self.set_tank_drive(0.5, -0.5)
    
    def stop(self):
        """Stop all movement"""
        self.left_motor.stop()
        self.right_motor.stop()
        
        if self.left_task and not self.left_task.done():
            self.left_task.cancel()
        if self.right_task and not self.right_task.done():
            self.right_task.cancel()
    
    def execute_command(self, command: str):
        """Execute a movement command (for button/keyboard control)"""
        self.stop()
        
        if command == "forward":
            asyncio.create_task(self.move_forward())
        elif command == "backward":
            asyncio.create_task(self.move_backward())
        elif command == "left":
            asyncio.create_task(self.turn_left())
        elif command == "right":
            asyncio.create_task(self.turn_right())
        elif command == "stop":
            pass


class RoverHealthMonitor:
    """Monitors and reports rover health statistics"""
    
    def get_health_data(self) -> Dict:
        """Return current health statistics"""
        return {
            "timestamp": datetime.now().isoformat(),
            "battery_voltage": 7.4,
            "cpu_temperature": self._get_cpu_temp(),
            "motors_enabled": True,
            "camera_active": True,
            "signal_strength": 100
        }
    
    def _get_cpu_temp(self) -> float:
        """Read CPU temperature from Raspberry Pi"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = float(f.read()) / 1000.0
                return round(temp, 1)
        except:
            return 0.0


class USBCameraStreamer:
    """
    USB Camera Streamer using OpenCV
    
    LEARNING POINT: USB cameras are simpler than Pi Camera
    - No special drivers needed
    - Works with any USB webcam
    - Uses standard V4L2 (Video4Linux2) interface
    """
    
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.camera = None
        self.is_streaming = False
        self.frame_lock = threading.Lock()
        self.current_frame = None
        self.setup_camera()
    
    def setup_camera(self):
        """
        Initialize USB camera
        
        LEARNING POINT: camera_index is which USB camera to use
        - 0 = first camera (usually /dev/video0)
        - 1 = second camera, etc.
        """
        if cv2:
            try:
                self.camera = cv2.VideoCapture(self.camera_index)
                
                # Set camera properties for better performance
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.camera.set(cv2.CAP_PROP_FPS, 30)
                
                # Test if camera works
                ret, frame = self.camera.read()
                if ret:
                    logger.info(f"USB Camera initialized successfully (index: {self.camera_index})")
                    self.is_streaming = True
                else:
                    logger.error("Camera opened but couldn't read frame")
                    self.camera = None
                    
            except Exception as e:
                logger.error(f"Camera initialization failed: {e}")
                self.camera = None
    
    def get_frame(self) -> Optional[bytes]:
        """
        Capture and return a JPEG frame
        
        LEARNING POINT: We encode frames as JPEG for efficient transmission
        Much smaller than raw image data
        """
        if self.camera and self.is_streaming:
            try:
                ret, frame = self.camera.read()
                if ret:
                    # Encode frame as JPEG
                    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ret:
                        return buffer.tobytes()
                else:
                    logger.warning("Failed to read frame from camera")
            except Exception as e:
                logger.error(f"Frame capture error: {e}")
        return None
    
    def release(self):
        """Release camera resources"""
        if self.camera:
            self.camera.release()
            logger.info("Camera released")


class RoverWebServer:
    """Main web server with tank drive and USB camera support"""
    
    def __init__(self):
        # Initialize all subsystems
        self.motor_controller = RoverMotorController(
            left_pins=[17, 18, 27, 22],
            right_pins=[5, 6, 13, 19]
        )
        self.health_monitor = RoverHealthMonitor()
        self.camera = USBCameraStreamer(camera_index=0)
        
        # Store connected WebSocket clients
        self.websockets = set()
        
        # Create web application
        self.app = web.Application()
        self.setup_routes()
        self.setup_cors()
    
    def setup_routes(self):
        """Define URL endpoints"""
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/ws', self.handle_websocket)
        self.app.router.add_get('/health', self.handle_health)
        self.app.router.add_get('/camera/stream', self.handle_camera_stream)
        self.app.router.add_static('/static', path='./static', name='static')
    
    def setup_cors(self):
        """Enable CORS for cross-origin requests"""
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        
        for route in list(self.app.router.routes()):
            cors.add(route)
    
    async def handle_index(self, request):
        """Serve the main webpage"""
        return web.FileResponse('./static/index.html')
    
    async def handle_health(self, request):
        """API endpoint for health data"""
        health_data = self.health_monitor.get_health_data()
        return web.json_response(health_data)
    
    async def handle_camera_stream(self, request):
        """
        Stream camera feed as MJPEG
        
        LEARNING POINT: MJPEG (Motion JPEG) streams individual JPEG frames
        Browser displays them continuously like a video
        This is simpler than H.264 but uses more bandwidth
        """
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
                'Cache-Control': 'no-cache',
                'Connection': 'close',
            }
        )
        
        await response.prepare(request)
        
        try:
            while True:
                frame = self.camera.get_frame()
                if frame:
                    # Send frame in MJPEG format
                    await response.write(
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
                    )
                    await asyncio.sleep(0.033)  # ~30 FPS
                else:
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Camera stream error: {e}")
        finally:
            await response.write_eof()
        
        return response
    
    async def handle_websocket(self, request):
        """Handle WebSocket connections"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.add(ws)
        logger.info(f"New WebSocket connection. Total: {len(self.websockets)}")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self.handle_websocket_message(ws, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {ws.exception()}')
        finally:
            self.websockets.discard(ws)
            logger.info(f"WebSocket disconnected. Total: {len(self.websockets)}")
        
        return ws
    
    async def handle_websocket_message(self, ws, message: str):
        """
        Process incoming WebSocket messages
        
        NEW: Handle tank_drive messages with independent motor speeds
        """
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'control':
                # Handle button/keyboard command
                command = data.get('command')
                logger.info(f"Received control command: {command}")
                self.motor_controller.execute_command(command)
                
                await ws.send_json({
                    'type': 'ack',
                    'command': command,
                    'status': 'executed'
                })
            
            elif msg_type == 'tank_drive':
                # Handle joystick tank drive
                left_speed = data.get('left_speed', 0.0)
                right_speed = data.get('right_speed', 0.0)
                
                # Clamp values to -1.0 to 1.0
                left_speed = max(-1.0, min(1.0, left_speed))
                right_speed = max(-1.0, min(1.0, right_speed))
                
                self.motor_controller.set_tank_drive(left_speed, right_speed)
                
                # Optional: Send acknowledgment (can be disabled for performance)
                # await ws.send_json({
                #     'type': 'ack',
                #     'left_speed': left_speed,
                #     'right_speed': right_speed
                # })
            
            elif msg_type == 'request_health':
                health_data = self.health_monitor.get_health_data()
                await ws.send_json({
                    'type': 'health',
                    'data': health_data
                })
        
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def broadcast_health(self):
        """Periodically broadcast health data to all connected clients"""
        while True:
            await asyncio.sleep(2)
            
            if self.websockets:
                health_data = self.health_monitor.get_health_data()
                message = json.dumps({
                    'type': 'health',
                    'data': health_data
                })
                
                for ws in self.websockets.copy():
                    try:
                        await ws.send_str(message)
                    except:
                        self.websockets.discard(ws)
    
    async def startup_tasks(self, app):
        """
        Background tasks that start when the server starts
        
        LEARNING POINT: This is called by aiohttp when the event loop is ready
        Now we can safely create async tasks
        """
        app['health_task'] = asyncio.create_task(self.broadcast_health())
        logger.info("Health monitoring started")
    
    async def cleanup_tasks(self, app):
        """Clean up background tasks on shutdown"""
        if 'health_task' in app:
            app['health_task'].cancel()
            try:
                await app['health_task']
            except asyncio.CancelledError:
                pass
    
    def run(self, host='0.0.0.0', port=8080):
        """
        Start the web server
        
        LEARNING POINT: We register startup/cleanup handlers instead of
        creating tasks directly. This ensures the event loop exists.
        """
        try:
            # Register startup and cleanup handlers
            self.app.on_startup.append(self.startup_tasks)
            self.app.on_cleanup.append(self.cleanup_tasks)
            
            logger.info(f"Starting Mars Rover server on http://{host}:{port}")
            logger.info("Tank Drive Enabled: Left stick = left motor, Right stick = right motor")
            web.run_app(self.app, host=host, port=port)
        
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up GPIO and resources"""
        logger.info("Cleaning up resources...")
        self.motor_controller.stop()
        self.camera.release()
        if GPIO:
            GPIO.cleanup()


if __name__ == '__main__':
    server = RoverWebServer()
    server.run()
