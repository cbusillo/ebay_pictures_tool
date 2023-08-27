#!/usr/bin/env python3

import argparse
import base64
import json
import logging
import os
import plistlib
import re
import shutil
import subprocess
import xmlrpc.client
from io import BytesIO
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy
from PIL import Image, ImageChops, ImageDraw
from colour import COLOR_NAME_TO_RGB
from pyzbar.pyzbar import decode
from rembg.bg import remove, new_session

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("/tmp/ebay_pictures_tool.log")
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Debug settings
IS_TESTING = os.environ.get("IS_TESTING", "").lower() in ["true", "1"]
LEAVE_IMAGES = os.environ.get("LEAVE_IMAGES", "").lower() in ["true", "1"]

# Defaults
INPUT_PATH = Path("/Volumes/EOS_DIGITAL")
if IS_TESTING:
    INPUT_PATH = Path.home() / "Pictures" / "Canon"
ROOT_OUTPUT_PATH = Path.home() / "Desktop/eBay Pics"
ORIGINAL_OUTPUT_PATH = ROOT_OUTPUT_PATH / "Original"
NB_TRIMMED_OUTPUT_PATH = ROOT_OUTPUT_PATH / "NB_Trimmed"
NB_OUTPUT_PATH = ROOT_OUTPUT_PATH / "NB"
TRIMMED_OUTPUT_PATH = ROOT_OUTPUT_PATH / "Trimmed"
# noinspection SpellCheckingInspection
MODEL_NAME = "isnet-general-use"
BACKGROUND_COLOR = 'white'

PHOTO_EXTENSIONS = ["JPG", "jpg", "CR2", "cr2", "PNG", "png", "JPEG", "jpeg"]
RGB = tuple[int, int, int]


def load_secrets_from_file() -> dict[str, str]:
    home = Path.home()
    secret_file_path = home / ".shiny" / "secret.json"

    try:
        with open(secret_file_path) as file:
            secret_file_json = json.load(file)
    except FileNotFoundError:
        logger.error(f"Secret file not found at {secret_file_path}.  Creating template file")
        root_project_path = Path(__file__).parent
        sample_secret_file_path = root_project_path / "secret.json.sample"
        os.makedirs(os.path.dirname(secret_file_path), exist_ok=True)
        shutil.copy(sample_secret_file_path, secret_file_path)

        return {}

    return secret_file_json


secrets = load_secrets_from_file()
ODOO_URL = secrets.get("odoo_url", "")
ODOO_DB = secrets.get("odoo_db", "")
ODOO_USERNAME = secrets.get("odoo_username", "")
ODOO_PASSWORD = secrets.get("odoo_password", "")


def get_brew_path() -> Path | None:
    try:
        architecture = subprocess.check_output(['uname', '-m']).decode('utf-8').strip()
    except Exception as e:
        logger.error(f"Failed to determine architecture: {e}")
        return None

    if architecture == "x86_64":
        return Path("/usr/local/bin")
    elif "arm" in architecture:
        return Path("/opt/homebrew/bin")
    else:
        logger.error(f"Unsupported architecture: {architecture}")
        raise ValueError(f"Unsupported architecture: {architecture}")


def restart_launch_agent(launch_agent_path: Path):
    try:
        uid = subprocess.check_output(["id", "-u"]).decode('utf-8').strip()
        domain = f"gui/{uid}"

        logger.info(f"Stopping launch agent at {launch_agent_path.stem}")

        # noinspection SpellCheckingInspection
        command_to_run = ["launchctl", "bootout", f"{domain}/{launch_agent_path.stem}"]
        subprocess.run(command_to_run)
        logger.info(" ".join(command_to_run))

        logger.info(f"Starting launch agent at {launch_agent_path.stem}")

        command_to_run = ["launchctl", "bootstrap", domain, launch_agent_path.as_posix()]
        subprocess.run(command_to_run)
        logger.info(" ".join(command_to_run))

        command_to_run = ["launchctl", "kickstart", "-k", f"{domain}/{launch_agent_path.stem}"]
        subprocess.run(command_to_run)
        logger.info(" ".join(command_to_run))

        logger.info("Loaded launch agent")
    except subprocess.CalledProcessError:
        logger.error("Failed to load launch agent")
        raise


def install_launch_agent() -> None:
    home = Path.home()
    launch_agent_dir = home / "Library" / "LaunchAgents"
    # noinspection SpellCheckingInspection
    launch_agent_name = "com.shiny.folder-listener.plist"
    launch_agent_path = launch_agent_dir / launch_agent_name

    root_project_dir = Path(__file__).parent
    plist_file_path = root_project_dir / launch_agent_name
    is_changed = False
    if not launch_agent_path.exists():
        is_changed = True
        logger.info(f"Installing launch agent at {launch_agent_path}")
        launch_agent_dir.mkdir(exist_ok=True)
        shutil.copy(plist_file_path, launch_agent_path)

    with open(launch_agent_path, "rb") as file:
        plist_data = plistlib.load(file)

    correct_script_path = get_brew_path() / "ebay_pictures_tool"
    if plist_data["ProgramArguments"][0] != correct_script_path.as_posix():
        is_changed = True
        logger.info(f"Updating launch agent path to {correct_script_path}")
        plist_data["ProgramArguments"][0] = correct_script_path.as_posix()

    correct_input_path = str(INPUT_PATH)
    if plist_data["QueueDirectories"][0] != correct_input_path:
        if "EnvironmentVariables" not in plist_data:
            plist_data["EnvironmentVariables"] = {}
        if IS_TESTING:
            plist_data["EnvironmentVariables"]["IS_TESTING"] = "True"
        else:
            plist_data["EnvironmentVariables"].pop("IS_TESTING", None)
        logger.info(f"Updating input path to {correct_input_path}")
        plist_data["QueueDirectories"][0] = correct_input_path
        is_changed = True

    if is_changed:
        with launch_agent_path.open("wb") as file:
            plistlib.dump(plist_data, file)
        restart_launch_agent(launch_agent_path)


def get_mount_point(input_path: Path) -> Path:
    current_path = input_path
    while not current_path.is_mount():
        current_path = current_path.parent
    return current_path


def is_ejectable_drive(path_to_test: Path) -> bool:
    try:
        mount_point_to_test = get_mount_point(path_to_test)
        mount_output = subprocess.check_output(["diskutil", "info", mount_point_to_test]).decode('utf-8')
        mount_lines = mount_output.splitlines()
        for line in mount_lines:
            if "Ejectable:" in line:  # TODO: check if new macOS uses "Removable Media:"
                return "Yes" in line.strip().split()[-1]
    except subprocess.CalledProcessError as error:
        logging.info(f"Failed to get diskutil info: {error.output}")
    return False


def eject_external_drive(path_to_eject: Path) -> bool:
    try:
        subprocess.run(["diskutil", "eject", path_to_eject])
        logger.info("Ejected external drive")
        return True
    except subprocess.CalledProcessError as error:
        logger.error(f"Failed to eject external drive: {error}")
        return False


def create_directories(
        paths_to_create: list[Path],
) -> bool:
    for output_path in paths_to_create:
        output_path.mkdir(exist_ok=True, parents=True)
    return True


def copy_images_from_input_folder(input_folder_path: Path, output_path: Path) -> list[Path]:
    files_to_process = []
    for ext in PHOTO_EXTENSIONS:
        for source_file in input_folder_path.rglob(f"*.{ext}"):
            destination_file = output_path / source_file.name
            shutil.copy(source_file, destination_file)
            logger.info(f"Processing {source_file.name}")
            files_to_process.append(destination_file)
            if not LEAVE_IMAGES:
                source_file.unlink()
    return files_to_process


def process_images(
        files_to_process: list[Path],
        nb_output_path: Path,
        trimmed_output_path: Path,
        nb_trimmed_output_path: Path,
        model_name,
        background_color,
) -> None:
    args = [
        (file_path, nb_output_path, trimmed_output_path, nb_trimmed_output_path, model_name, background_color)
        for file_path in files_to_process
    ]
    if IS_TESTING:
        for arg in args:
            process_image(*arg)
        return
    else:
        chunk_size = max(1, len(files_to_process) // (cpu_count() * 4))
        with Pool(cpu_count()) as pool:
            pool.starmap(process_image, args, chunksize=chunk_size)


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '', filename)


def decode_and_remove_qr_label(image: Image) -> (str | None, Image):
    image_np = numpy.array(image.convert('L'))
    decoded_objects = decode(image_np)

    for obj in decoded_objects:
        # Get the bounding rectangle
        x, y, w, h = obj.rect.left, obj.rect.top, obj.rect.width, obj.rect.height

        # Calculate the expanded rectangle dimensions
        expanded_w = x + w * 1.10
        expanded_h = y + h * 1.10

        adjusted_x = x - w * 0.10
        adjusted_y = y - h * 0.10

        coords = (
            (int(adjusted_x), int(adjusted_y)),
            (int(expanded_w), int(expanded_h))
        )

        image_draw = ImageDraw.Draw(image)
        image_draw.rectangle(coords, fill="white")
        sanitized_name = sanitize_filename(obj.data.decode('utf-8'))
        return sanitized_name, image

    return None, image


def generate_unique_filename(output_path: Path, filename: str) -> Path:
    base_name = output_path.joinpath(filename).stem
    extension = output_path.joinpath(filename).suffix

    counter = 1
    new_filepath = output_path / filename
    while new_filepath.exists():
        new_filepath = output_path / f"{base_name}_{counter}{extension}"
        counter += 1
    return new_filepath


def add_image_to_odoo(sku: str, image: Image) -> None:
    if sku and 0 < len(sku) < 10 and sku.isdigit():
        logger.info(f"Updating record {sku} with image")
        add_odoo_product_image(ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, sku, image)
    else:
        logger.warning(f"Record not found for SKU: {sku}")


def process_image(
        original_image_file_path: Path,
        nb_output_path: Path,
        trimmed_output_path: Path,
        nb_trimmed_output_path: Path,
        model_name: str,
        background_color: RGB,
) -> None:
    original_image = Image.open(original_image_file_path)

    # qr_data, original_image = decode_and_remove_qr_label(original_image)
    qr_data = None  # TODO: Remove this line when QR code is working
    output_file_name = original_image_file_path.stem
    if qr_data:
        output_file_name = qr_data
        logger.info(f"Found QR code with data: {qr_data}")
    else:
        logger.warning("No QR code found, using original filename.")

    logger.info(f"Removing background from {original_image_file_path.name}")

    cleaned_image_file_path = generate_unique_filename(nb_output_path, output_file_name + ".png")

    session = new_session(model_name)
    cleaned_image = remove(original_image, session=session)

    cleaned_image.save(cleaned_image_file_path)
    logger.info(f"Writing {cleaned_image_file_path.name}")

    nb_trimmed_image, crop_box = trim_image(cleaned_image)

    if crop_box:  # Only process if a bounding box was returned
        nb_trimmed_image_with_bg = add_background_color(nb_trimmed_image, background_color)
        nb_trimmed_image_file_path = generate_unique_filename(nb_trimmed_output_path, output_file_name + ".png")

        logger.info(f"Trimmed {nb_trimmed_image_file_path.name}")
        nb_trimmed_image_with_bg.save(nb_trimmed_image_file_path, format="PNG")

        # Use the returned crop_box to crop the original image
        trimmed_image = original_image.crop(crop_box)
        trimmed_image_file_path = generate_unique_filename(trimmed_output_path, output_file_name + ".png")

        trimmed_image.save(trimmed_image_file_path, format="PNG")
        logger.info(f"Writing NB trimmed {nb_trimmed_image_file_path.name}")

    if ODOO_DB and qr_data:
        add_image_to_odoo(output_file_name, nb_trimmed_image)


def trim_image(image: Image) -> tuple[Image, tuple[int, int, int, int] | None]:
    buffer_size = 100
    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    cropped_image_box = diff.getbbox()
    if cropped_image_box:
        # Add buffer to the bounding box
        buffered_box = (
            max(0, cropped_image_box[0] - buffer_size),  # left
            max(0, cropped_image_box[1] - buffer_size),  # upper
            min(image.width, cropped_image_box[2] + buffer_size),  # right
            min(image.height, cropped_image_box[3] + buffer_size)  # lower
        )
        return image.crop(buffered_box), buffered_box
    return image, None  # Return original image and None if no changes detected


def add_background_color(image: Image, color: RGB) -> Image:
    if image.mode in ("RGBA", "LA"):
        background = Image.new(image.mode[:-1], image.size, color)
        background.paste(image, image.split()[-1])
        return background
    else:
        return image


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process images from folder")
    parser.add_argument(
        "-i",
        "--input_path",
        type=str,
        default=INPUT_PATH.as_posix(),
        help=("Path to input folder.  If this folder is on an external drive, it will be automatically ejected.  Default value of "
              f"{INPUT_PATH}, if not provided."),
    )
    parser.add_argument(
        "-o",
        "--output_path",
        type=str,
        default=ROOT_OUTPUT_PATH.as_posix(),
        help=("Path to root output folder.   "
              f"{ROOT_OUTPUT_PATH}, if not provided."),
    )
    parser.add_argument(
        "-oo",
        "--original_output_path",
        type=str,
        default=ORIGINAL_OUTPUT_PATH.as_posix(),
        help=f"Path to original output folder.  If not provided, defaults to {ORIGINAL_OUTPUT_PATH}",
    )
    parser.add_argument(
        "-nt",
        "--nb_trimmed_output_path",
        type=str,
        default=NB_TRIMMED_OUTPUT_PATH.as_posix(),
        help=f"Path to trimmed output folder.  If not provided, defaults to {NB_TRIMMED_OUTPUT_PATH}",
    )
    parser.add_argument(
        "-n",
        "--nb_output_path",
        type=str,
        default=NB_OUTPUT_PATH.as_posix(),
        help=f"Path to no background output folder.  If not provided, defaults to {NB_OUTPUT_PATH}",
    )
    parser.add_argument(
        "-t",
        "--trimmed_output_path",
        type=str,
        default=TRIMMED_OUTPUT_PATH.as_posix(),
        help="Path to trimmed output folder.  If not provided, defaults to {TRIMMED_OUTPUT_PATH}",
    )
    parser.add_argument(
        "-b",
        "--background_color",
        type=str,
        default=BACKGROUND_COLOR,
        help=("Background color to add to trimmed images in W3C color naming.  https://www.w3.org/TR/css-color-3/#svg-color"
              f"Default is {BACKGROUND_COLOR}."),
    )
    # noinspection SpellCheckingInspection
    parser.add_argument(
        "-m",
        "--model_name",
        type=str,
        default=MODEL_NAME,
        help=f"""Model name to use for background removal. Available options:
          - 'isnet-general-use': This model is optimal for cleanly cutting out the primary object, 
                                 but it will remove everything except the main subject.
          - 'u2net': This model doesn't cut as cleanly as 'isnet-general-use', 
                     but retains smaller parts in the pictures, such as screws or other minor details.
          - 'auto': This will automatically select the best model based on the number of objects in the image.
        Default is '{MODEL_NAME}'.""",
    )

    return parser.parse_args()


def add_odoo_product_image(url, db, username, password, product_sku, image: Image):
    # noinspection SpellCheckingInspection
    common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
    uid = common.authenticate(db, username, password, {})
    # noinspection SpellCheckingInspection
    models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

    # 1. Find the product based on its SKU
    product_ids = models.execute_kw(
        db, uid, password,
        'product.import', 'search',
        [[['default_code', '=', product_sku]]]
    )

    if not product_ids:
        raise ValueError(f"No product found with SKU: {product_sku}")

    product_id = product_ids[0]  # Assuming there's only one unique SKU

    # 2. Read the image and encode it to base64
    buffered = BytesIO()
    image.save(buffered, format="JPEG")
    image_data = base64.b64encode(buffered.getvalue()).decode('utf-8')

    # 3. Create a new image record linked to the product
    image_record_id = models.execute_kw(
        db, uid, password,
        'product.import.image', 'create',
        [{
            'image_data': image_data,
            'product_id': product_id
        }]
    )

    return image_record_id


def main() -> None:
    install_launch_agent()
    args = get_args()
    input_path = Path(args.input_path)
    if not input_path.exists():
        logger.error(f"Input folder not found at {input_path}")
        return

    root_output_path = Path(args.output_path)
    if root_output_path:
        original_output_path = root_output_path / "Original"
        trimmed_output_path = root_output_path / "Trimmed"
        nb_trimmed_output_path = root_output_path / "NB_Trimmed"
        nb_output_path = root_output_path / "NB"
    else:
        original_output_path = Path(args.original_output_path) if args.original_output_path else ORIGINAL_OUTPUT_PATH
        trimmed_output_path = Path(args.trimmed_output_path)
        nb_trimmed_output_path = Path(args.nb_trimmed_output_path)
        nb_output_path = Path(args.nb_output_path)

    try:
        background_color = COLOR_NAME_TO_RGB[args.background_color]
    except AttributeError:
        logger.error(f"Invalid background color: {args.background_color}")
        return

    if args.model_name not in ["isnet-general-use", "u2net", "auto"]:
        logger.error(f"Invalid model name: {args.model_name}")
        return

    if create_directories(
            [original_output_path, trimmed_output_path, nb_output_path, nb_trimmed_output_path]
    ):
        copied_files = copy_images_from_input_folder(input_path, original_output_path)
        if is_ejectable_drive(input_path):
            eject_external_drive(input_path)
        process_images(
            copied_files,
            nb_output_path,
            trimmed_output_path,
            nb_trimmed_output_path,
            args.model_name,
            background_color,
        )


if __name__ == "__main__":
    main()
