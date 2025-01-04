"""
This work is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License.
To view a copy of this license, visit http://creativecommons.org/licenses/by-nc/4.0/.

You are free to:
- Share: copy and redistribute the material in any medium or format
- Adapt: remix, transform, and build upon the material

Under the following terms:
- Attribution: You must give appropriate credit, provide a link to the license, and indicate if changes were made. You may do so in any reasonable manner, but not in any way that suggests the licensor endorses you or your use.
- NonCommercial: You may not use the material for commercial purposes.

No additional restrictions: You may not apply legal terms or technological measures that legally restrict others from doing anything the license permits.
"""

import logging
import sys
import toml
import random
import time
import threading
from PIL import Image, ImageDraw
from luma.core.interface.serial import i2c, spi
import luma.oled.device as oled
import luma.lcd.device as lcd

# Global variable to track and pass on to functions
current_bg_color = "black"
current_eye_color = "white"
current_curious = False

# Global variables for x/y offset for look based animations
current_offset_x = 0
current_offset_y = 0

# Global variables for eyelid heights face changes
current_face = "default"
eyelid_top_inner_left_height = 0
eyelid_top_outer_left_height = 0
eyelid_bottom_left_height = 0
eyelid_top_inner_right_height = 0
eyelid_top_outer_right_height = 0
eyelid_bottom_right_height = 0

# Initialize global variables for eye heights close/open/blink
current_closed = None
current_eye_height_left = 0
current_eye_height_right = 0

# Servo limits
servo_limit_x = 45
servo_limit_y = 45

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Default configuration for the OLED screen
DEFAULT_SCREEN_CONFIG = {
    "screen": {
        "type": "oled",
        "driver": "ssd1306",
        "width": 128,
        "height": 64,
        "rotate": 0,
        "interface": "i2c",
        "i2c": {
            "address": "0x3c",
            "i2c_port": 1,
        },
    }
}

# Default rendering parameters
DEFAULT_RENDER_CONFIG = {
    "render": {
        "fps": 30,  # Default refresh rate
    },
    "eye": {
        "distance": 10,  # Default distance between eyes
        "left": {
            "width": 32,
            "height": 32,
            "roundness": 8,
        },
        "right": {
            "width": 32,
            "height": 32,
            "roundness": 8,
        },
    },
}

def load_config(file_path, default_config):
    """
    Load configuration from a TOML file. If the file is missing, use the default configuration.
    :param file_path: Path to the TOML file
    :param default_config: Default configuration dictionary
    :return: Loaded configuration dictionary
    """
    try:
        with open(file_path, "r") as f:
            logging.info(f"Loading configuration from {file_path}...")
            config = toml.load(f)
            logging.info(f"Configuration loaded successfully from {file_path}.")
            return {**default_config, **config}  # Merge defaults with loaded config
    except FileNotFoundError:
        logging.warning(f"{file_path} not found. Using default configuration.")
        return default_config
    except Exception as e:
        logging.error(f"Error reading configuration from {file_path}: {e}")
        sys.exit(1)

# def validate_screen_config(config):
    # """
    # Validate the screen configuration to ensure required fields are present.
    # :param config: Screen configuration dictionary
    # """
    # try:
        # screen = config["screen"]
        # required_fields = ["type", "driver", "width", "height", "interface"]

        # for field in required_fields:
            # if field not in screen:
                # raise ValueError(f"Missing required field: '{field}' in screen configuration.")

        # if screen["interface"] == "i2c" and "i2c" not in screen:
            # raise ValueError("Missing 'i2c' section for I2C interface.")
        # if screen["interface"] == "spi" and "spi" not in screen:
            # raise ValueError("Missing 'spi' section for SPI interface.")
    # except KeyError as e:
        # logging.error(f"Configuration validation error: Missing key {e}")
        # sys.exit(1)
    # except ValueError as e:
        # logging.error(f"Configuration validation error: {e}")
        # sys.exit(1)

def get_device(config):
    try:
        screen = config["screen"]

        # Initialize the interface
        if screen["interface"] == "spi":
            serial = spi(
                port=screen["spi"].get("spi_port"),
                device=screen["spi"].get("spi_device"),
                gpio_DC=screen["gpio"].get("gpio_data_command"),
                gpio_RST=screen["gpio"].get("gpio_reset"),
                gpio_backlight=screen["gpio"].get("gpio_backlight"),
                gpio_CS=screen["gpio"].get("gpio_chip_select"),
                bus_speed_hz=screen["spi"].get("spi_bus_speed"),
            )
        elif screen["interface"] == "i2c":
            serial = i2c(port=screen["i2c"].get("i2c_port"), address=screen["i2c"].get("address"))
        else:
            raise ValueError(f"Unsupported interface type: {screen['interface']}")

        # Dynamically load the driver
        driver_name = screen["driver"]
        driver_module = getattr(oled, driver_name, None) or getattr(lcd, driver_name, None)

        if driver_module is None:
            raise ValueError(f"Unsupported driver: {driver_name}")

        # Initialize the device
        device = driver_module(serial, width=screen["width"], height=screen["height"], rotate=screen.get("rotate", 0), mode=screen.get("mode", "1"))

        # Turn on the backlight if gpio_backlight is defined
        if "gpio" in screen and "gpio_backlight" in screen["gpio"]:
            device.backlight(True)  # Set to False to turn on the backlight

        logging.info(f"Initialized {screen['type']} screen with driver {driver_name}.")
        return device

    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        raise

    except Exception as e:
        logging.error(f"Error initializing device: {e}")
        raise

def draw_eyes(device, config):
    """
    Draws the eyes on the OLED display based on the current state and offsets.
    This function runs in a loop and updates the display at the configured frame rate.

    :param device: The display device.
    :param config: Configuration dictionary.
    """
    global current_bg_color, current_eye_color, current_face, current_curious, current_closed, current_offset_x, current_offset_y
    global eyelid_top_inner_left_height, eyelid_top_outer_left_height, eyelid_bottom_left_height
    global eyelid_top_inner_right_height, eyelid_top_outer_right_height, eyelid_bottom_right_height
    global current_eye_width_left, current_eye_width_right, current_eye_height_left, current_eye_height_right
        
    # Ensure eyes are open by default if current_closed is None and closed if set it when loading        
    if current_closed is None:
        current_eye_height_left = config["eye"]["left"]["height"]
        current_eye_height_right = config["eye"]["right"]["height"]

    while True:
        # Default black background and white eye color when using a monochrome screen
        if device.mode == "1":  # Monochrome OLED
            bg_color = "black"
            eye_color = "white"
        else:
            bg_color = current_bg_color
            eye_color = current_eye_color

        # Dynamically create an image based on the device mode
        image = Image.new(device.mode, (device.width, device.height), bg_color)
        draw = ImageDraw.Draw(image)

        # Eye parameters
        left_eye = config["eye"]["left"]
        right_eye = config["eye"]["right"]
        distance = config["eye"]["distance"]
        # Base dimensions for eyes
        eye_width_left = left_eye["width"]
        eye_width_right = right_eye["width"]
        eye_height_left = current_eye_height_left if current_eye_height_left else left_eye["height"]
        eye_height_right = current_eye_height_right if current_eye_height_right else right_eye["height"]

        # Get movement constraints
        min_x_offset, max_x_offset, min_y_offset, max_y_offset = get_constraints(config, device)

        # Apply curious effect dynamically
        if current_curious:
            max_increase = 0.4  # Max increase by 40%
            scale_factor = max_increase / (config["screen"]["width"] // 2)
            if current_offset_x < 0:  # Moving left
                eye_width_left += int(scale_factor * abs(current_offset_x) * left_eye["width"])
                eye_width_right -= int(scale_factor * abs(current_offset_x) * right_eye["width"])
                eye_height_left += int(scale_factor * abs(current_offset_x) * eye_height_left)
                eye_height_right -= int(scale_factor * abs(current_offset_x) * eye_height_right)
            elif current_offset_x > 0:  # Moving right
                eye_height_left -= int(scale_factor * abs(current_offset_x) * eye_height_left)
                eye_height_right += int(scale_factor * abs(current_offset_x) * eye_height_right)
                eye_width_left -= int(scale_factor * abs(current_offset_x) * left_eye["width"])
                eye_width_right += int(scale_factor * abs(current_offset_x) * right_eye["width"])

        # Clamp sizes to ensure no negative or unrealistic dimensions
        eye_height_left = max(2, eye_height_left)
        eye_height_right = max(2, eye_height_right)
        eye_width_left = max(2, eye_width_left)
        eye_width_right = max(2, eye_width_right)

        # Roundness of the rectangle
        roundness_left = left_eye["roundness"]
        roundness_right = right_eye["roundness"]
        # Calculate eye positions coords: x0,y0 (top left corner) x1,y1 (bottom right corner)
        left_eye_coords = (
            device.width // 2 - eye_width_left - distance // 2 + current_offset_x,
            device.height // 2 - eye_height_left // 2 + current_offset_y,
            device.width // 2 - distance // 2 + current_offset_x,
            device.height // 2 + eye_height_left // 2 + current_offset_y,
        )
        right_eye_coords = (
            device.width // 2 + distance // 2 + current_offset_x,
            device.height // 2 - eye_height_right // 2 + current_offset_y,
            device.width // 2 + eye_width_right + distance // 2 + current_offset_x,
            device.height // 2 + eye_height_right // 2 + current_offset_y,
        )

        # Draw the eyes draw.rounded_rectangle: width could be added for outline thickness
        draw.rounded_rectangle(left_eye_coords, radius=roundness_left, outline=eye_color, fill=eye_color)
        draw.rounded_rectangle(right_eye_coords, radius=roundness_right, outline=eye_color, fill=eye_color)

        # Draw top eyelids draw.polygon: outline and width could be added for outline thickness
        if eyelid_top_inner_left_height or eyelid_top_outer_left_height > 0:
            draw.polygon([
                (left_eye_coords[0], left_eye_coords[1]),
                (left_eye_coords[0], left_eye_coords[1] + (eyelid_top_outer_left_height * eye_height_left // left_eye["height"])),
                (left_eye_coords[2], left_eye_coords[1] + (eyelid_top_inner_left_height * eye_height_left // left_eye["height"])),
                (left_eye_coords[2], left_eye_coords[1]),
            ], fill=bg_color)
        if eyelid_top_inner_right_height or eyelid_top_outer_right_height > 0:
            draw.polygon([
                (right_eye_coords[0], right_eye_coords[1]),
                (right_eye_coords[0], right_eye_coords[1] + (eyelid_top_inner_right_height * eye_height_left // left_eye["height"])),
                (right_eye_coords[2], right_eye_coords[1] + (eyelid_top_outer_right_height * eye_height_right // right_eye["height"])),
                (right_eye_coords[2], right_eye_coords[1]),
            ], fill=bg_color)
        # Draw bottom eyelids
        if eyelid_bottom_left_height > 0:
            draw.rounded_rectangle(
                (
                    left_eye_coords[0],
                    left_eye_coords[3] - (eyelid_bottom_left_height * eye_height_left // left_eye["height"]),
                    left_eye_coords[2],
                    left_eye_coords[3],
                ),
                radius=roundness_left,
                outline=bg_color,
                fill=bg_color,
            )
        if eyelid_bottom_right_height > 0:
            draw.rounded_rectangle(
                (
                    right_eye_coords[0],
                    right_eye_coords[3] - (eyelid_bottom_right_height * eye_height_right // right_eye["height"]),
                    right_eye_coords[2],
                    right_eye_coords[3],
                ),
                radius=roundness_right,
                outline=bg_color,
                fill=bg_color,
            )
        # Display the image
        device.display(image)

def change_face(device, config, new_face=None):
    global current_face, current_closed
    global eyelid_top_inner_left_height, eyelid_top_outer_left_height, eyelid_bottom_left_height
    global eyelid_top_inner_right_height, eyelid_top_outer_right_height, eyelid_bottom_right_height
    global current_eye_width_left, current_eye_width_right, current_eye_height_left, current_eye_height_right

    if new_face is None:
        new_face = current_face

    previous_face = current_face
    current_face = new_face  # Update global face state

    # Determine target eyelid positions based on the new face
    if new_face == "happy":
        target_eyelid_heights = {
            "top_inner_left": 0,
            "top_outer_left": 0,
            "bottom_left": config["eye"]["left"]["height"] // 2,
            "top_inner_right": 0,
            "top_outer_right": 0,
            "bottom_right": config["eye"]["right"]["height"] // 2,
        }
    elif new_face == "angry":
        target_eyelid_heights = {
            "top_inner_left": config["eye"]["left"]["height"] // 2,
            "top_outer_left": 0,
            "bottom_left": 0,
            "top_inner_right": config["eye"]["right"]["height"] // 2,
            "top_outer_right": 0,
            "bottom_right": 0,
        }
    elif new_face == "tired":
        target_eyelid_heights = {
            "top_inner_left": 0,
            "top_outer_left": config["eye"]["left"]["height"] // 2,
            "bottom_left": 0,
            "top_inner_right": 0,
            "top_outer_right": config["eye"]["right"]["height"] // 2,
            "bottom_right": 0,
        }
    else:
        target_eyelid_heights = {
            "top_inner_left": 0,
            "top_outer_left": 0,
            "bottom_left": 0,
            "top_inner_right": 0,
            "top_outer_right": 0,
            "bottom_right": 0,
        }

    # Adjust eyelids dynamically
    adjustment_speed = 2  # Pixels per frame
    current_eyelid_positions = {
        "top_inner_left": eyelid_top_inner_left_height,
        "top_outer_left": eyelid_top_outer_left_height,
        "bottom_left": eyelid_bottom_left_height,
        "top_inner_right": eyelid_top_inner_right_height,
        "top_outer_right": eyelid_top_outer_right_height,
        "bottom_right": eyelid_bottom_right_height,
    }

    while any(
        current_eyelid_positions[key] != target_eyelid_heights[key]
        for key in target_eyelid_heights
    ):
        for key in current_eyelid_positions:
            if current_eyelid_positions[key] < target_eyelid_heights[key]:
                current_eyelid_positions[key] = min(
                    current_eyelid_positions[key] + adjustment_speed,
                    target_eyelid_heights[key],
                )
            elif current_eyelid_positions[key] > target_eyelid_heights[key]:
                current_eyelid_positions[key] = max(
                    current_eyelid_positions[key] - adjustment_speed,
                    target_eyelid_heights[key],
                )

        # Update global eyelid heights
        eyelid_top_inner_left_height = current_eyelid_positions["top_inner_left"]
        eyelid_top_outer_left_height = current_eyelid_positions["top_outer_left"]
        eyelid_bottom_left_height = current_eyelid_positions["bottom_left"]
        eyelid_top_inner_right_height = current_eyelid_positions["top_inner_right"]
        eyelid_top_outer_right_height = current_eyelid_positions["top_outer_right"]
        eyelid_bottom_right_height = current_eyelid_positions["bottom_right"]

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate
        
def curious_mode(device, config, curious):
    global current_curious
    # Close eyes before changing the curious mode
    close_eyes(device, config, eye="both", speed="medium")
    # Set the curious mode state
    current_curious = curious
    # Open eyes after changing the curious mode
    open_eyes(device, config, eye="both", speed="medium")

def get_constraints(config, device):
    # Eye parameters
    left_eye = config["eye"]["left"]
    right_eye = config["eye"]["right"]
    distance = config["eye"]["distance"]

    # Base dimensions for eyes
    eye_width_left = left_eye["width"]
    eye_width_right = right_eye["width"]
    eye_height_left = left_eye["height"]
    eye_height_right = right_eye["height"]

    # Apply curious effect dynamically
    if current_curious:
        max_increase = 0.2  # Max increase by 40%
        eye_width_left = int(eye_width_left * (1 + max_increase))
        eye_width_right = int(eye_width_right * (1 + max_increase))
        eye_height_left = int(eye_height_left * (1 + max_increase))
        eye_height_right = int(eye_height_right * (1 + max_increase))

    # Calculate movement constraints
    min_x_offset = -(device.width // 2 - eye_width_left - distance // 2)
    max_x_offset = device.width // 2 - eye_width_right - distance // 2
    min_y_offset = -(device.height // 2 - eye_height_left // 2)
    max_y_offset = device.height // 2 - eye_height_right // 2

    return min_x_offset, max_x_offset, min_y_offset, max_y_offset

def look(device, config, direction=None, speed="medium", target_offset_x=None, target_offset_y=None):
    global current_offset_x, current_offset_y

    # Get movement constraints
    min_x_offset, max_x_offset, min_y_offset, max_y_offset = get_constraints(config, device)

    # Determine target offsets based on direction
    if direction == "L":
        target_offset_x = min_x_offset
        target_offset_y = 0
    elif direction == "R":
        target_offset_x = max_x_offset
        target_offset_y = 0
    elif direction == "T":
        target_offset_x = 0
        target_offset_y = min_y_offset
    elif direction == "B":
        target_offset_x = 0
        target_offset_y = max_y_offset
    elif direction == "TL":
        target_offset_x = min_x_offset
        target_offset_y = min_y_offset
    elif direction == "TR":
        target_offset_x = max_x_offset
        target_offset_y = min_y_offset
    elif direction == "BL":
        target_offset_x = min_x_offset
        target_offset_y = max_y_offset
    elif direction == "BR":
        target_offset_x = max_x_offset
        target_offset_y = max_y_offset
    elif direction == "C":
        target_offset_x = 0
        target_offset_y = 0
    else:
        # Parse custom x-y coordinates from direction string
        try:
            target_offset_x, target_offset_y = map(int, direction.split(","))
        except ValueError:
            logging.error(f"Invalid direction format: {direction}")
            return

    # Ensure target offsets are within constraints
    if target_offset_x is not None:
        target_offset_x = max(min_x_offset, min(max_x_offset, target_offset_x))
    if target_offset_y is not None:
        target_offset_y = max(min_y_offset, min(max_y_offset, target_offset_y))

    # Adjust offsets dynamically
    speed_map = {"slow": 1, "medium": 2, "fast": 5}
    adjustment_speed = speed_map.get(speed, 2)  # Default to medium speed
    current_offsets = {
        "x": current_offset_x,
        "y": current_offset_y,
    }

    while current_offsets["x"] != target_offset_x or current_offsets["y"] != target_offset_y:
        if current_offsets["x"] < target_offset_x:
            current_offsets["x"] = min(current_offsets["x"] + adjustment_speed, target_offset_x)
        elif current_offsets["x"] > target_offset_x:
            current_offsets["x"] = max(current_offsets["x"] - adjustment_speed, target_offset_x)

        if current_offsets["y"] < target_offset_y:
            current_offsets["y"] = min(current_offsets["y"] + adjustment_speed, target_offset_y)
        elif current_offsets["y"] > target_offset_y:
            current_offsets["y"] = max(current_offsets["y"] - adjustment_speed, target_offset_y)

        # Update global offsets
        current_offset_x = current_offsets["x"]
        current_offset_y = current_offsets["y"]

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate

def shake_eyes(device, config, direction="random", speed="fast"):
    global current_offset_x, current_offset_y
    """
    Shake the eyes horizontally, vertically, or randomly by calling the look function.
    :param device: The display device
    :param config: Configuration dictionary
    :param direction: Direction of shaking ("h" for horizontal, "v" for vertical, "random" for random)
    :param speed: Speed of shaking ("fast", "medium", "slow")
    """
    # Get movement constraints
    min_x_offset, max_x_offset, min_y_offset, max_y_offset = get_constraints(config, device)
    
    # Calculate shake limits
    shake_limit_x = (max_x_offset - min_x_offset) // 3
    shake_limit_y = (max_y_offset - min_y_offset) // 6

    if direction == "h":
        look(device, config, direction=f"{-shake_limit_x},{current_offset_y}", speed=speed)
        look(device, config, direction=f"{shake_limit_x},{current_offset_y}", speed=speed)
        look(device, config, direction=f"{-shake_limit_x},{current_offset_y}", speed=speed)
        look(device, config, direction=f"{shake_limit_x},{current_offset_y}", speed=speed)
        look(device, config, direction=f"0,0", speed=speed)
    elif direction == "v":
        look(device, config, direction=f"{current_offset_x},{-shake_limit_y}", speed=speed)
        look(device, config, direction=f"{current_offset_x},{shake_limit_y}", speed=speed)
        look(device, config, direction=f"{current_offset_x},{-shake_limit_y}", speed=speed)
        look(device, config, direction=f"{current_offset_x},{shake_limit_y}", speed=speed)
        look(device, config, direction=f"0,0", speed=speed)
    else:  # Random direction within the shake limit
        for _ in range(10):  # Shake for 10 random directions
            random_x = random.randint(-shake_limit_x, shake_limit_x)
            random_y = random.randint(-shake_limit_y, shake_limit_y)
            look(device, config, direction=f"{random_x},{random_y}", speed=speed)

def close_eyes(device, config, eye=None, speed="medium"):
    global current_closed, current_eye_height_left, current_eye_height_right

    # Default blink heights to original values if None
    left_eye_height_orig = config["eye"]["left"]["height"]
    right_eye_height_orig = config["eye"]["right"]["height"]
    if current_eye_height_left is None:
        current_eye_height_left = left_eye_height_orig
    if current_eye_height_right is None:
        current_eye_height_right = right_eye_height_orig

    # Define the speed of animation in pixels per frame
    movement_speed = {"fast": 4, "medium": 2, "slow": 1}.get(speed, 2)
    while True:
        if eye in ["both", "left"]:
            current_eye_height_left = max(1, current_eye_height_left - movement_speed)
        if eye in ["both", "right"]:
            current_eye_height_right = max(1, current_eye_height_right - movement_speed)

        # Break when the specified eye(s) are fully closed
        if eye == "both" and current_eye_height_left <= 1 and current_eye_height_right <= 1:
            current_closed = "both"
            break
        elif eye == "left" and current_eye_height_left <= 1:
            current_closed = "left"
            break
        elif eye == "right" and current_eye_height_right <= 1:
            current_closed = "right"
            break

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate

    # Ensure the larger eye waits for the smaller one to reach minimum height
    if eye == "both":
        while current_eye_height_left > 1 or current_eye_height_right > 1:
            if current_eye_height_left > 1:
                current_eye_height_left = max(1, current_eye_height_left - movement_speed)
            if current_eye_height_right > 1:
                current_eye_height_right = max(1, current_eye_height_right - movement_speed)
            time.sleep(1 / config["render"]["fps"])  # Control the frame rate
        
def open_eyes(device, config, eye=None, speed="medium"):
    global current_closed, current_eye_height_left, current_eye_height_right

    if not current_closed:  # If eyes are already open, skip animation
        logging.warning("Eyes are already open. Skipping animation.")
        return

    # Default blink heights based on current_closed state
    left_eye_height_orig = config["eye"]["left"]["height"]
    right_eye_height_orig = config["eye"]["right"]["height"]

    # Ensure blink heights are initialized to their closed state
    if current_closed == "both":
        current_eye_height_left = 1
        current_eye_height_right = 1
    elif current_closed == "left":
        current_eye_height_left = 1
        current_eye_height_right = right_eye_height_orig
    elif current_closed == "right":
        current_eye_height_left = left_eye_height_orig
        current_eye_height_right = 1
    else:
        # If eyes are already open, no need for animation
        logging.info("Eyes are already open. Skipping opening animation.")
        return

    # Define the speed of animation in pixels per frame
    movement_speed = {"fast": 4, "medium": 2, "slow": 1}.get(speed, 2)

    while True:
        if eye in ["both", "left"]:
            current_eye_height_left = min(left_eye_height_orig, current_eye_height_left + movement_speed)
        if eye in ["both", "right"]:
            current_eye_height_right = min(right_eye_height_orig, current_eye_height_right + movement_speed)

        # Break when the specified eye(s) are fully open
        if eye == "both" and current_eye_height_left >= left_eye_height_orig and current_eye_height_right >= right_eye_height_orig:
            current_closed = None
            break
        elif eye == "left" and current_eye_height_left >= left_eye_height_orig:
            current_closed = "right" if current_closed == "both" else None
            break
        elif eye == "right" and current_eye_height_right >= right_eye_height_orig:
            current_closed = "left" if current_closed == "both" else None
            break

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate

    # Ensure the smaller eye waits for the larger one to reach original height
    if eye == "both":
        while current_eye_height_left < left_eye_height_orig or current_eye_height_right < right_eye_height_orig:
            if current_eye_height_left < left_eye_height_orig:
                current_eye_height_left = min(left_eye_height_orig, current_eye_height_left + movement_speed)
            if current_eye_height_right < right_eye_height_orig:
                current_eye_height_right = min(right_eye_height_orig, current_eye_height_right + movement_speed)
            time.sleep(1 / config["render"]["fps"])  # Control the frame rate
        
def blink_eyes(device, config, eye="both", speed="fast"):
    close_eyes(device, config, eye=eye, speed=speed)
    open_eyes(device, config, eye=eye, speed=speed)
        
def pantilt(device, config):
    """
    Controls the PanTilt HAT to move the display physically based on the current eye offsets.

    :param device: The display device.
    :param config: Configuration dictionary.
    """
    import pantilthat
    global current_offset_x, current_offset_y

    # Get movement constraints
    min_x_offset, max_x_offset, min_y_offset, max_y_offset = get_constraints(config, device)

    # Initialize lists to store the last 4 offset values
    offset_x_values = [0, 0, 0, 0, 0]
    offset_y_values = [0, 0, 0, 0, 0]

    # Initialize previous servo positions
    prev_servo_x = None
    prev_servo_y = None

    while True:
        # Update the lists with the current offsets
        offset_x_values.append(current_offset_x)
        offset_y_values.append(current_offset_y)
        if len(offset_x_values) > 5:
            offset_x_values.pop(0)
        if len(offset_y_values) > 5:
            offset_y_values.pop(0)

        # Calculate the moving average of the last 4 offset values
        avg_offset_x = sum(offset_x_values) / len(offset_x_values)
        avg_offset_y = sum(offset_y_values) / len(offset_y_values)

        # Calculate proportional servo target values based on the average offsets
        servo_x = int((avg_offset_x - min_x_offset) / (max_x_offset - min_x_offset) * 2 * servo_limit_x - servo_limit_x)
        servo_y = int((avg_offset_y - min_y_offset) / (max_y_offset - min_y_offset) * 2 * servo_limit_y - servo_limit_y)

        # Clamp the servo values to the limits
        servo_x = max(-servo_limit_x, min(servo_limit_x, servo_x))
        servo_y = max(-servo_limit_y, min(servo_limit_y, servo_y))

        # Check if the servo positions have changed
        if servo_x != prev_servo_x or servo_y != prev_servo_y:
            # Move the servos
            pantilthat.pan(servo_x)
            pantilthat.tilt(servo_y)
            prev_servo_x = servo_x
            prev_servo_y = servo_y
        else:
            # Turn off the servos if there is no change
            pantilthat.servo_enable(1, False)
            pantilthat.servo_enable(2, False)

        # Control the update rate
        time.sleep(0.5 / config["render"]["fps"])

def idle(device, config):
    """
    Idle function to render the eyes and add random behaviors such as blinking, looking around, and changing faces.

    :param device: The display device.
    :param config: Configuration dictionary.
    """
    global current_offset_x, current_offset_y

    # Get movement constraints
    min_x_offset, max_x_offset, min_y_offset, max_y_offset = get_constraints(config, device)

    # Define possible speeds
    speeds = ["slow", "medium", "fast"]

    # Define possible faces
    faces = ["happy", "angry", "tired", "curious"]

    def blink():
        """
        Blinks the eyes at random intervals with random speeds.
        """
        while True:
            blink_interval = random.uniform(3, 5)
            blink_speed = random.choice(speeds)
            time.sleep(blink_interval)
            blink_eyes(device, config, eye="both", speed=blink_speed)

    def look_around():
        """
        Moves the eyes to random positions at random intervals with random speeds.
        """
        while True:
            look_interval = random.uniform(5, 10)
            random_x = random.randint(min_x_offset, max_x_offset)
            random_y = random.randint(min_y_offset, max_y_offset)
            look_speed = random.choice(speeds)
            time.sleep(look_interval)
            look(device, config, direction=f"{random_x},{random_y}", speed=look_speed)

    def change_face_randomly():
        """
        Changes the face to a random expression at random intervals.
        """
        while True:
            face_change_interval = random.uniform(15, 30)
            new_face = random.choice(faces)
            time.sleep(face_change_interval)
            change_face(device, config, new_face=new_face)
    # Start the threads
    threading.Thread(target=blink).start()
    threading.Thread(target=look_around).start()
    threading.Thread(target=change_face_randomly).start()

def start_closed(device, config):
    global current_closed
    current_closed="both"
    close_eyes(device, config, eye="both", speed="slow")
    # time.sleep(1)
    # Start the draw_eyes loop in a separate thread with initial state closed
    threading.Thread(target=draw_eyes, args=(device, config)).start()

def wake_up(device, config, eye="both"):
    """
    Performs the wake-up animation sequence, starting with closed eyes and transitioning to open eyes with a tired face.

    :param device: The display device.
    :param config: Configuration dictionary.
    :param eye: Which eye to animate ("left", "right", "both").
    """
    global current_closed
    current_closed="both"
    # Change face to tired
    change_face(device, config, new_face="tired")
    # Wait for a moment
    time.sleep(1)
    # Open eyes at medium speed
    open_eyes(device, config, eye=eye, speed="slow")
    # Wait for a moment
    time.sleep(1)
    # Blink eyes slowly
    blink_eyes(device, config, eye=eye, speed="medium")
    # Change face to default
    change_face(device, config, new_face="default")

def main():
    """
    Main function to load configurations, initialize the display device, and start the necessary threads and animations.
    """
    # Load screen and render configurations
    screen_config = load_config("screenconfig.toml", DEFAULT_SCREEN_CONFIG)
    render_config = load_config("eyeconfig.toml", DEFAULT_RENDER_CONFIG)
    # Merge configurations
    config = {**screen_config, **render_config}
    # Initialize the display device
    device = get_device(config)
    # Verify device initialization
    logging.info(f"Device initialized: {device}")
    # Check if pantilt is enabled
    if config.get("pantilt", {}).get("enabled", False):
        # Start the pantilt function in a separate thread
        threading.Thread(target=pantilt, args=(device, config)).start()
    # Start the draw_eyes loop in a separate thread with initial state closed
    # threading.Thread(target=draw_eyes, args=(device, config)).start()
    # Start the idle function
    logging.info(f"Starting the wakeup animation")
    start_closed(device, config)
    wake_up(device, config)
    time.sleep(2)
    curious_mode(device, config, curious=True)
    logging.info(f"Starting the idle animation")
    idle(device, config)
    time.sleep(10)
    shake_eyes(device, config, direction="h")
    time.sleep(10)
    shake_eyes(device, config, direction="v")
    time.sleep(10)
    shake_eyes(device, config)

if __name__ == "__main__":
    main()
    