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

def validate_screen_config(config):
    """
    Validate the screen configuration to ensure required fields are present.
    :param config: Screen configuration dictionary
    """
    try:
        screen = config["screen"]
        required_fields = ["type", "driver", "width", "height", "interface"]

        for field in required_fields:
            if field not in screen:
                raise ValueError(f"Missing required field: '{field}' in screen configuration.")

        if screen["interface"] == "i2c" and "i2c" not in screen:
            raise ValueError("Missing 'i2c' section for I2C interface.")
        if screen["interface"] == "spi" and "spi" not in screen:
            raise ValueError("Missing 'spi' section for SPI interface.")
    except KeyError as e:
        logging.error(f"Configuration validation error: Missing key {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"Configuration validation error: {e}")
        sys.exit(1)

def get_device(config):
    """
    Create and initialize the display device based on the configuration.
    :param config: Screen configuration dictionary
    :return: Initialized display device
    """
    try:
        screen = config["screen"]
        validate_screen_config(config)

        # Create the serial interface
        serial = None  # Initialize serial variable
        if screen["interface"] == "i2c":
            i2c_address = int(screen["i2c"]["address"], 16)
            serial = i2c(port=screen["i2c"].get("i2c_port", 1), address=i2c_address)
        elif screen["interface"] == "spi":
            spi_params = screen["spi"]
            gpio_params = screen.get("gpio", {})
            serial = spi(
                port=spi_params.get("spi_port", 0),
                device=spi_params.get("spi_device", 0),
                gpio_DC=gpio_params.get("gpio_data_command"),
                gpio_RST=gpio_params.get("gpio_reset"),
                gpio_backlight=gpio_params.get("gpio_backlight"),
                bus_speed_hz=spi_params.get("spi_bus_speed", 8000000),
            )
        else:
            raise ValueError(f"Unsupported interface type: {screen['interface']}")

        # Dynamically load the driver
        driver_name = screen["driver"]
        driver_module = getattr(oled, driver_name, None) or getattr(lcd, driver_name, None)

        if driver_module is None:
            raise ValueError(f"Unsupported driver: {driver_name}")

        # Initialize the device
        device = driver_module(serial, width=screen["width"], height=screen["height"], rotate=screen.get("rotate", 0))

        logging.info(f"Initialized {screen['type']} screen with driver {driver_name}.")
        return device
        
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error initializing screen: {e}")
        sys.exit(1)

# Global variable to track and pass on to functions
current_bg_color = "black"
current_eye_color = "white"
current_face = "default"
current_curious = False
current_closed = None
current_offset_x = 0
current_offset_y = 0

# Global variables for eyelid heights
eyelid_top_inner_left_height = 0
eyelid_top_outer_left_height = 0
eyelid_bottom_left_height = 0
eyelid_top_inner_right_height = 0
eyelid_top_outer_right_height = 0
eyelid_bottom_right_height = 0

# Initialize global variables for eye heights
current_eye_height_left = 0
current_eye_height_right = 0

def draw_eyes(device, config):
    global current_bg_color, current_eye_color, current_face, current_curious, current_closed, current_offset_x, current_offset_y
    global eyelid_top_inner_left_height, eyelid_top_outer_left_height, eyelid_bottom_left_height
    global eyelid_top_inner_right_height, eyelid_top_outer_right_height, eyelid_bottom_right_height
    global current_eye_width_left, current_eye_width_right, current_eye_height_left, current_eye_height_right

    # Ensure eyes are open by default if current_closed is None
    if current_closed is None:
        current_eye_height_left = config["eye"]["left"]["height"]
        current_eye_height_right = config["eye"]["right"]["height"]

    while True:
        # logging.debug(f"draw_eyes called with face={current_face}, curious={current_curious}, closed={current_closed}, offset_x={current_offset_x}, offset_y={current_offset_y}")

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
        # logging.debug(f"Left eye coords: {left_eye_coords}, Right eye coords: {right_eye_coords}")

        # Draw the eyes draw.rounded_rectangle: width could be added for outline thickness
        draw.rounded_rectangle(left_eye_coords, radius=roundness_left, outline=eye_color, fill=eye_color)
        draw.rounded_rectangle(right_eye_coords, radius=roundness_right, outline=eye_color, fill=eye_color)

        # Draw top eyelids draw.polygon: outline and width could be added for outline thickness
        if eyelid_top_inner_left_height or eyelid_top_outer_left_height > 0:
            draw.polygon([
                (left_eye_coords[0], left_eye_coords[1]),
                (left_eye_coords[0], left_eye_coords[1] + eyelid_top_outer_left_height),
                (left_eye_coords[2], left_eye_coords[1] + eyelid_top_inner_left_height),
                (left_eye_coords[2], left_eye_coords[1]),
            ], fill=bg_color)
        if eyelid_top_inner_right_height or eyelid_top_outer_right_height > 0:
            draw.polygon([
                (right_eye_coords[0], right_eye_coords[1]),
                (right_eye_coords[0], right_eye_coords[1] + eyelid_top_inner_right_height),
                (right_eye_coords[2], right_eye_coords[1] + eyelid_top_outer_right_height),
                (right_eye_coords[2], right_eye_coords[1]),
            ], fill=bg_color)
        # Draw bottom eyelids
        if eyelid_bottom_left_height > 0:
            draw.rounded_rectangle(
                (
                    left_eye_coords[0],
                    left_eye_coords[3] - eyelid_bottom_left_height,
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
                    right_eye_coords[3] - eyelid_bottom_right_height,
                    right_eye_coords[2],
                    right_eye_coords[3],
                ),
                radius=roundness_right,
                outline=bg_color,
                fill=bg_color,
            )
        # Display the image
        device.display(image)
        # logging.info("Eyes drawn on the screen")

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate       

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
            "bottom_left": current_eye_height_left // 2,
            "top_inner_right": 0,
            "top_outer_right": 0,
            "bottom_right": current_eye_height_right // 2,
        }
    elif new_face == "angry":
        target_eyelid_heights = {
            "top_inner_left": current_eye_height_left // 2,
            "top_outer_left": 0,
            "bottom_left": 0,
            "top_inner_right": current_eye_height_right // 2,
            "top_outer_right": 0,
            "bottom_right": 0,
        }
    elif new_face == "tired":
        target_eyelid_heights = {
            "top_inner_left": 0,
            "top_outer_left": current_eye_height_left // 2,
            "bottom_left": 0,
            "top_inner_right": 0,
            "top_outer_right": current_eye_height_right // 2,
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
        
def curious_mode(device, config):
    global current_curious
    current_curious = True

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

def look(device, config, direction, speed="medium"):
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
    else:  # Center
        target_offset_x = 0
        target_offset_y = 0

    # Adjust offsets dynamically
    speed_map = {"slow": 0.5, "medium": 1, "fast": 2}
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
    movement_speed = {"fast": 4, "medium": 2, "slow": 1}.get(speed, 4)
    while True:
        if eye in ["both", "left"]:
            current_eye_height_left = max(2, current_eye_height_left - movement_speed)
        if eye in ["both", "right"]:
            current_eye_height_right = max(2, current_eye_height_right - movement_speed)

        # Break when the eyes are fully closed
        if (current_eye_height_left <= 2 and eye in ["both", "left"]) and (
            current_eye_height_right <= 2 and eye in ["both", "right"]
        ):
            current_closed = "both"  # Update state to closed
            break
        elif current_eye_height_left <= 2 and eye in ["left"]:
            current_closed = "left"  # Update state to closed
            break
        elif current_eye_height_right <= 2 and eye in ["right"]:
            current_closed = "right"  # Update state to closed
            break

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
        current_eye_height_left = 2
        current_eye_height_right = 2
    elif current_closed == "left":
        current_eye_height_left = 2
        current_eye_height_right = right_eye_height_orig
    elif current_closed == "right":
        current_eye_height_left = left_eye_height_orig
        current_eye_height_right = 2
    else:
        # If eyes are already open, no need for animation
        logging.info("Eyes are already open. Skipping opening animation.")
        return

    # Define the speed of animation in pixels per frame
    movement_speed = {"fast": 4, "medium": 2, "slow": 1}.get(speed, 4)

    while True:
        if eye in ["both", "left"]:
            current_eye_height_left = min(left_eye_height_orig, current_eye_height_left + movement_speed)
        if eye in ["both", "right"]:
            current_eye_height_right = min(right_eye_height_orig, current_eye_height_right + movement_speed)

        # Break when the eyes are fully open
        if (current_eye_height_left >= left_eye_height_orig and eye in ["both", "left"]) and (
            current_eye_height_right >= right_eye_height_orig and eye in ["both", "right"]
        ):
            current_closed = None  # Update state to open
            break
        elif current_eye_height_left >= left_eye_height_orig and eye in ["both", "left"]:
            current_closed = "right" if current_closed == "both" else None  # Only right remains closed
            break
        elif current_eye_height_right >= right_eye_height_orig and eye in ["both", "right"]:
            current_closed = "left" if current_closed == "both" else None  # Only left remains closed
            break

        time.sleep(1 / config["render"]["fps"])  # Control the frame rate
        
def blink_eyes(device, config, eye="both", speed="fast"):
    close_eyes(device, config, eye=eye, speed=speed)
    open_eyes(device, config, eye=eye, speed=speed)
        
def main():
    # Load screen and render configurations
    screen_config = load_config("screenconfig.toml", DEFAULT_SCREEN_CONFIG)
    render_config = load_config("eyeconfig.toml", DEFAULT_RENDER_CONFIG)

    # Merge configurations
    config = {**screen_config, **render_config}

    # Initialize the display device
    device = get_device(config)

    # Verify device initialization
    logging.info(f"Device initialized: {device}")

    # Start the draw_eyes loop in a separate thread
    threading.Thread(target=draw_eyes, args=(device, config)).start()
    change_face(device, config)
    time.sleep(2)

    # Test blinking
    logging.info(f"Starting main loop to test blinking")
    blink_eyes(device, config)
    time.sleep(3)
    blink_eyes(device, config, eye="left", speed="medium")
    time.sleep(3)
    blink_eyes(device, config, eye="right", speed="slow")
    time.sleep(3)

    # Test eye closing and opening
    # logging.info(f"Starting main loop to test eye closing and opening")
    # time.sleep(3)
    # close_eyes(device, config, eye="both", speed="slow")
    # time.sleep(3)
    # open_eyes(device, config, eye="both", speed="slow")
    # time.sleep(3)
    # close_eyes(device, config, eye="left", speed="slow")
    # time.sleep(3)
    # blink_eyes(device, config, eye="left", speed="slow")
    # time.sleep(3)
    # close_eyes(device, config, eye="right", speed="slow")
    # time.sleep(3)
    # blink_eyes(device, config, eye="right", speed="slow")
    # time.sleep(3)

    # Main loop to test face change animation
    logging.info(f"Starting main loop to test face change animation")
    curious_mode(device, config)
    time.sleep(2)
    look(device, config, direction="TR", speed="fast")
    change_face(device, config, new_face="happy")
    blink_eyes(device, config)
    time.sleep(2)
    look(device, config, direction="BL", speed="medium")
    change_face(device, config, new_face="angry")
    blink_eyes(device, config)
    time.sleep(2)
    look(device, config, direction="T", speed="fast")
    change_face(device, config, new_face="tired")
    time.sleep(2)
    time.sleep(2)
    look(device, config, direction="TR", speed="fast")
    change_face(device, config, new_face="happy")
    blink_eyes(device, config)
    time.sleep(2)
    look(device, config, direction="BL", speed="medium")
    change_face(device, config, new_face="angry")
    blink_eyes(device, config)
    time.sleep(2)
    look(device, config, direction="T", speed="fast")
    change_face(device, config, new_face="tired")

    # Main loop to test look animation with curious mode on
    logging.info(f"Starting main loop to test look animation with curious mode on")
    look(device, config, direction="TL", speed="fast")
    time.sleep(1)
    look(device, config, direction="T", speed="fast")
    blink_eyes(device, config)
    time.sleep(1)
    blink_eyes(device, config)
    look(device, config, direction="TR", speed="fast")
    time.sleep(1)
    look(device, config, direction="L", speed="medium")
    time.sleep(1)
    look(device, config, direction="R", speed="medium")
    time.sleep(1)
    look(device, config, direction="BL", speed="slow")
    time.sleep(1)
    look(device, config, direction="B", speed="slow")
    time.sleep(1)
    look(device, config, direction="BR", speed="slow")
    time.sleep(1)
    look(device, config, direction="C", speed="slow")
    current_curious = False

if __name__ == "__main__":
    main()