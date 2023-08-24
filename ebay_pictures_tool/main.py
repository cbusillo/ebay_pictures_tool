#!/usr/bin/env python3

import argparse
import logging
import re
import shutil
import subprocess
from multiprocessing import Pool, cpu_count
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from rembg.bg import remove, new_session
from pyzbar.pyzbar import decode
import numpy

# Defaults
SD_CARD_PATH = Path("/Volumes/EOS_DIGITAL")
# SD_CARD_PATH = Path.home() /"Desktop/Input files"
OUTPUT_PATH = Path.home() / "Desktop/eBay Pics"
TRIMMED_OUTPUT_PATH = OUTPUT_PATH / "Trimmed"
NB_OUTPUT_PATH = OUTPUT_PATH / "NB"

PHOTO_EXTENSIONS = ["JPG", "jpg", "CR2", "cr2", "PNG", "png", "JPEG", "jpeg"]
RGB = tuple[int, int, int]
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def eject_sd_card(sd_card_path: Path) -> None:
    try:
        subprocess.run(["diskutil", "eject", sd_card_path])
        logger.info("Ejected SD card")
    except subprocess.CalledProcessError as error:
        logger.error(f"Failed to eject SD card: {error}")


def create_directories(
        sd_card_path: Path,
        output_path: Path,
        trimmed_output_path: Path,
        nb_output_path: Path,
) -> bool:
    if not sd_card_path.exists():
        logger.error(f"SD card not found at {sd_card_path}")
        return False
    [
        output_path.mkdir(exist_ok=True)
        for output_path in [output_path, trimmed_output_path, nb_output_path]
    ]
    return True


def copy_images_from_sd_card(sd_card_path: Path, output_path: Path) -> list[Path]:
    files_to_process = []
    for ext in PHOTO_EXTENSIONS:
        for source_file in sd_card_path.rglob(f"*.{ext}"):
            destination_file = output_path / source_file.name
            shutil.copy(source_file, destination_file)
            logger.info(f"Processed {source_file.name}")
            files_to_process.append(destination_file)
            # source_file.unlink() # TODO: remove this after testing
    return files_to_process


def process_images(
        files_to_process: list[Path],
        nb_output_path: Path,
        trimmed_output_path: Path,
        model_name,
        background_color,
) -> None:
    chunk_size = max(1, len(files_to_process) // (cpu_count() * 4))
    args = [
        (file_path, nb_output_path, trimmed_output_path, model_name, background_color)
        for file_path in files_to_process
    ]
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

def process_image(
        original_image_file_path: Path,
        nb_output_path: Path,
        trimmed_output_path: Path,
        model_name: str,
        background_color: RGB,
) -> None:
    original_image = Image.open(original_image_file_path)

    qr_data, original_image = decode_and_remove_qr_label(original_image)
    if qr_data:
        logger.info(f"Found QR code with data: {qr_data}")
    else:
        qr_data = original_image_file_path.stem
        logger.warning("No QR code found, using original filename.")

    logger.info(f"Removing background from {original_image_file_path.name}")

    cleaned_image_file_path = generate_unique_filename(nb_output_path, qr_data + ".png")

    session = new_session(model_name)
    cleaned_image = remove(original_image, session=session)
    cleaned_image.save(cleaned_image_file_path)
    logger.info(f"Writing {cleaned_image_file_path.name}")

    trimmed_image = trim_image(cleaned_image)
    trimmed_image_file_path = generate_unique_filename(trimmed_output_path, qr_data + ".png")
    logger.info(f"Trimmed {trimmed_image_file_path.name}")

    trimmed_image_with_bg = add_background_color(trimmed_image, background_color)
    trimmed_image_with_bg.save(trimmed_image_file_path, format="PNG")
    original_image.close()


def trim_image(image: Image) -> Image:
    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    cropped_image = diff.getbbox()
    if cropped_image:
        return image.crop(cropped_image)
    return image  # Return original image if no changes detected


def add_background_color(image: Image, color: RGB = (255, 255, 255)) -> Image:
    if image.mode in ("RGBA", "LA"):
        background = Image.new(image.mode[:-1], image.size, color)
        background.paste(image, image.split()[-1])
        return background
    else:
        return image


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process images from SD card")
    parser.add_argument(
        "-s",
        "--sd_card_path",
        type=str,
        default=str(SD_CARD_PATH),
        help="Path to SD card",
    )
    parser.add_argument(
        "-o",
        "--output_path",
        type=str,
        default=str(OUTPUT_PATH),
        help="Path to output directory",
    )
    parser.add_argument(
        "-t",
        "--trimmed_output_path",
        type=str,
        default=str(TRIMMED_OUTPUT_PATH),
        help="Path to trimmed output directory",
    )
    parser.add_argument(
        "-n",
        "--nb_output_path",
        type=str,
        default=str(NB_OUTPUT_PATH),
        help="Path to no background output directory",
    )
    parser.add_argument(
        "-b",
        "--background_color",
        type=parse_rgb,
        default=(255, 255, 255),
        help="Background color to add to trimmed images in (R,G,B) format",
    )
    # noinspection SpellCheckingInspection
    parser.add_argument(
        "-m",
        "--model_name",
        type=str,
        default="isnet-general-use",
        help="Model name to use for background removal",
    )
    return parser.parse_args()


def parse_rgb(color_string: str) -> RGB:
    try:
        r, g, b = map(int, color_string.strip("()").split(","))
        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
            return r, g, b
        else:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid color format: {color_string}. Expected format: (R,G,B) with each value between 0 and 255."
        )


def install_brew():
    try:
        # Check if brew is already installed
        subprocess.check_output(["brew", "-v"])
        print("Homebrew is already installed.")
    except subprocess.CalledProcessError:
        print("Installing Homebrew...")
        # Install Homebrew
        subprocess.run(
            '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
            shell=True, check=True
        )
        print("Homebrew installed successfully.")


def install_with_brew(package_name):
    try:
        # Install package using brew
        subprocess.run(["brew", "install", package_name], check=True)
        print(f"{package_name} installed successfully.")
    except subprocess.CalledProcessError:
        print(f"Failed to install {package_name}.")


def check_zbar_dependency():
    try:
        from pyzbar.pyzbar import decode
    except ImportError as e:
        if 'zbar' in str(e).lower():
            logger.info("zbar dependency not found. Attempting to install...")
            install_brew()
            install_with_brew("zbar")
        else:
            raise e


def main() -> None:
    check_zbar_dependency()
    args = get_args()
    sd_card_path = Path(args.sd_card_path)
    output_path = Path(args.output_path)
    trimmed_output_path = Path(args.trimmed_output_path)
    nb_output_path = Path(args.nb_output_path)

    if create_directories(
            sd_card_path, output_path, trimmed_output_path, nb_output_path
    ):
        copied_files = copy_images_from_sd_card(sd_card_path, output_path)
        eject_sd_card(sd_card_path)
        process_images(
            copied_files,
            nb_output_path,
            trimmed_output_path,
            args.model_name,
            args.background_color,
        )


if __name__ == "__main__":
    main()
