import os
import time
import zipfile
import threading

import numpy as np
from PIL import Image

from windows_capture import (
    WindowsCapture,
    Frame,
    InternalCaptureControl,
)


# ============================================================
# SETTINGS
# ============================================================

WINDOW_NAME = "Snes9x"

# Actual framebuffer sent to SM64CoopDX
SOURCE_WIDTH = 256
SOURCE_HEIGHT = 224

# Actual Snes9x capture size
CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

# Snes9x is displaying the 256x224 image at 2x.
GAME_CAPTURE_WIDTH = 512
GAME_CAPTURE_HEIGHT = 448

# ============================================================
# MODFS PATH
#
# IMPORTANT:
# No "\save\" folder.
# ============================================================

MODFS_PATH = os.path.expandvars(
    r"%APPDATA%\sm64coopdx\sav\Earthbound.modfs"
)

RGB_FILENAME = "rgb.txt"

MINIMUM_UPDATE_INTERVAL = 16


# ============================================================
# STATE
# ============================================================

capture_closed = False

write_lock = threading.Lock()

last_rgb_text = None

last_dimensions_printed = False


# ============================================================
# CREATE / VERIFY MODFS
# ============================================================

def ensure_modfs():

    directory = os.path.dirname(
        MODFS_PATH
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    # ========================================================
    # Create the .modfs as a REAL ZIP if it doesn't exist.
    # ========================================================

    if not os.path.exists(MODFS_PATH):

        print(
            "[PYTHON] Creating:",
            MODFS_PATH
        )

        with zipfile.ZipFile(
            MODFS_PATH,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as z:

            z.writestr(
                RGB_FILENAME,
                ""
            )

        print(
            "[PYTHON] Earthbound.modfs created."
        )

        return


    # ========================================================
    # Verify existing .modfs is actually a ZIP.
    # ========================================================

    if not zipfile.is_zipfile(MODFS_PATH):

        print(
            "[PYTHON] Existing Earthbound.modfs "
            "is not a valid ZIP."
        )

        print(
            "[PYTHON] Recreating it..."
        )

        try:

            os.remove(
                MODFS_PATH
            )

        except OSError:

            pass


        with zipfile.ZipFile(
            MODFS_PATH,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as z:

            z.writestr(
                RGB_FILENAME,
                ""
            )


        print(
            "[PYTHON] Valid Earthbound.modfs created."
        )


# ============================================================
# WRITE RGB.TXT INTO MODFS
# ============================================================

def write_rgb_to_modfs(rgb_text):

    global last_rgb_text

    # ========================================================
    # Don't rewrite the ZIP if nothing changed.
    # ========================================================

    if rgb_text == last_rgb_text:
        return


    with write_lock:

        temp_path = (
            MODFS_PATH +
            ".tmp"
        )


        # ====================================================
        # Preserve every existing file except rgb.txt.
        # ====================================================

        old_files = {}

        try:

            with zipfile.ZipFile(
                MODFS_PATH,
                "r"
            ) as old_zip:

                for info in old_zip.infolist():

                    if info.filename == RGB_FILENAME:
                        continue

                    if info.is_dir():
                        continue

                    old_files[
                        info.filename
                    ] = old_zip.read(
                        info.filename
                    )


        except (
            zipfile.BadZipFile,
            FileNotFoundError
        ):

            old_files = {}


        # ====================================================
        # Build a completely new valid ZIP.
        # ====================================================

        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as new_zip:

            # Preserve other mod files.

            for filename, content in old_files.items():

                new_zip.writestr(
                    filename,
                    content
                )


            # Add framebuffer.

            new_zip.writestr(
                RGB_FILENAME,
                rgb_text
            )


        # ====================================================
        # Replace old ZIP atomically.
        # ====================================================

        os.replace(
            temp_path,
            MODFS_PATH
        )


        last_rgb_text = rgb_text


# ============================================================
# CONVERT FRAME
# ============================================================

def frame_to_rgb(frame):

    """
    Snes9x capture:

        600x500

    Actual game image:

        512x448

    Which is:

        256x224 at 2x

    Pipeline:

        600x500
             |
             v
        centered 512x448
             |
             v
        256x224
             |
             v
        RGB framebuffer
    """

    global last_dimensions_printed


    # ========================================================
    # Get capture buffer.
    # ========================================================

    buffer = frame.frame_buffer


    if buffer is None:

        print(
            "[PYTHON] Frame buffer is None."
        )

        return None


    # ========================================================
    # Make sure it is NumPy.
    # ========================================================

    if not isinstance(
        buffer,
        np.ndarray
    ):

        buffer = np.asarray(
            buffer
        )


    # ========================================================
    # Validate dimensions.
    # ========================================================

    if buffer.ndim != 3:

        print(
            "[PYTHON] Invalid frame dimensions:",
            buffer.shape
        )

        return None


    if buffer.shape[2] < 3:

        print(
            "[PYTHON] Frame has fewer than 3 channels:",
            buffer.shape
        )

        return None


    capture_height = buffer.shape[0]
    capture_width = buffer.shape[1]


    # ========================================================
    # Print capture dimensions once.
    # ========================================================

    if not last_dimensions_printed:

        print(
            "[PYTHON] Capture dimensions:",
            f"{capture_width}x{capture_height}"
        )

        last_dimensions_printed = True


    # ========================================================
    # Require the expected 600x500 capture.
    # ========================================================

    if (
        capture_width != CAPTURE_WIDTH
        or
        capture_height != CAPTURE_HEIGHT
    ):

        print(
            "[PYTHON] Unexpected capture size:",
            f"{capture_width}x{capture_height}",
            "expected",
            f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
        )

        return None


    # ========================================================
    # Determine where the 512x448 game image is.
    #
    # 600 - 512 = 88
    # 88 / 2 = 44
    #
    # 500 - 448 = 52
    # 52 / 2 = 26
    #
    # Therefore:
    #
    # left = 44
    # top  = 26
    # ========================================================

    left = (
        capture_width -
        GAME_CAPTURE_WIDTH
    ) // 2


    top = (
        capture_height -
        GAME_CAPTURE_HEIGHT
    ) // 2


    right = (
        left +
        GAME_CAPTURE_WIDTH
    )


    bottom = (
        top +
        GAME_CAPTURE_HEIGHT
    )


    # ========================================================
    # Safety check.
    # ========================================================

    if (
        left < 0
        or
        top < 0
        or
        right > capture_width
        or
        bottom > capture_height
    ):

        print(
            "[PYTHON] Game area does not fit inside capture."
        )

        print(
            "[PYTHON] Capture:",
            f"{capture_width}x{capture_height}"
        )

        print(
            "[PYTHON] Game:",
            f"{GAME_CAPTURE_WIDTH}x{GAME_CAPTURE_HEIGHT}"
        )

        return None


    # ========================================================
    # Extract COMPLETE 512x448 game image.
    # ========================================================

    game = buffer[
        top:bottom,
        left:right,
        :
    ]


    # ========================================================
    # Validate extracted image.
    # ========================================================

    if game.shape[0] != GAME_CAPTURE_HEIGHT:

        print(
            "[PYTHON] Wrong extracted height:",
            game.shape
        )

        return None


    if game.shape[1] != GAME_CAPTURE_WIDTH:

        print(
            "[PYTHON] Wrong extracted width:",
            game.shape
        )

        return None


    # ========================================================
    # Windows Capture normally provides BGRA.
    #
    # Convert:
    #
    # BGRA
    #   ↓
    # RGB
    # ========================================================

    game_rgb = game[
        :, :, :3
    ][
        :, :, ::-1
    ].copy()


    # ========================================================
    # Convert NumPy array to PIL image.
    # ========================================================

    image = Image.fromarray(
        game_rgb,
        "RGB"
    )


    # ========================================================
    # Reduce:
    #
    # 512x448
    #
    # to:
    #
    # 256x224
    #
    # NEAREST is intentional.
    #
    # Every 2x2 source block becomes exactly one SNES pixel.
    # ========================================================

    image = image.resize(
        (
            SOURCE_WIDTH,
            SOURCE_HEIGHT
        ),
        Image.Resampling.NEAREST
    )


    # ========================================================
    # PIL -> NumPy.
    # ========================================================

    rgb = np.asarray(
        image,
        dtype=np.uint8
    )


    # ========================================================
    # Final shape check.
    # ========================================================

    if rgb.shape != (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
        3
    ):

        print(
            "[PYTHON] Resize produced wrong shape:",
            rgb.shape
        )

        return None


    return rgb


# ============================================================
# RGB NUMPY ARRAY -> rgb.txt
# ============================================================

def rgb_to_text(rgb):

    # ========================================================
    # Verify exact framebuffer size.
    # ========================================================

    if rgb.shape != (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
        3
    ):

        raise ValueError(
            "Unexpected RGB shape: " +
            str(rgb.shape)
        )


    # ========================================================
    # Ensure uint8.
    # ========================================================

    rgb = np.asarray(
        rgb,
        dtype=np.uint8
    )


    # ========================================================
    # Flatten:
    #
    # row 1
    # row 2
    # ...
    # row 224
    #
    # Every row contains 256 pixels.
    # ========================================================

    flat = rgb.reshape(
        -1,
        3
    )


    # ========================================================
    # Convert every pixel to:
    #
    # R,G,B
    #
    # Exactly 57344 lines.
    # ========================================================

    lines = [
        f"{int(r)},{int(g)},{int(b)}"
        for r, g, b in flat
    ]


    return "\n".join(
        lines
    )


# ============================================================
# FRAME CAPTURE
# ============================================================

capture = WindowsCapture(

    cursor_capture=False,

    draw_border=False,

    # ========================================================
    # Capture the Snes9x window.
    #
    # No win32gui is required.
    # ========================================================

    window_name=WINDOW_NAME,

    monitor_index=None,

    minimum_update_interval=
        MINIMUM_UPDATE_INTERVAL
)


# ============================================================
# FRAME ARRIVED
# ============================================================

@capture.event
def on_frame_arrived(
    frame: Frame,
    capture_control: InternalCaptureControl
):

    global capture_closed

    try:

        if capture_closed:

            return


        # ====================================================
        # Convert 600x500 capture into 256x224 framebuffer.
        # ====================================================

        rgb = frame_to_rgb(
            frame
        )


        if rgb is None:

            return


        # ====================================================
        # Convert framebuffer to text.
        # ====================================================

        rgb_text = rgb_to_text(
            rgb
        )


        # ====================================================
        # Write framebuffer to ModFS.
        # ====================================================

        write_rgb_to_modfs(
            rgb_text
        )


    except Exception as error:

        print(
            "[PYTHON] Frame error:",
            repr(error)
        )


# ============================================================
# CAPTURE CLOSED
# ============================================================

@capture.event
def on_closed():

    global capture_closed

    capture_closed = True

    print(
        "[PYTHON] Capture closed."
    )

    print(
        "[PYTHON] Snes9x window was closed "
        "or the capture session ended."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global capture_closed
    global last_dimensions_printed
    global last_rgb_text


    capture_closed = False

    last_dimensions_printed = False

    last_rgb_text = None


    print(
        "[PYTHON] =================================================="
    )

    print(
        "[PYTHON] Snes9x RGB framebuffer capture"
    )

    print(
        "[PYTHON] =================================================="
    )

    print(
        "[PYTHON] Window:",
        WINDOW_NAME
    )

    print(
        "[PYTHON] Capture:",
        f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Game area:",
        f"{GAME_CAPTURE_WIDTH}x{GAME_CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Output framebuffer:",
        f"{SOURCE_WIDTH}x{SOURCE_HEIGHT}"
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )


    # ========================================================
    # Ensure Earthbound.modfs exists.
    # ========================================================

    ensure_modfs()


    # ========================================================
    # Start capture.
    # ========================================================

    try:

        capture.start()


    except Exception as error:

        print(
            "[PYTHON] Capture error:",
            repr(error)
        )

        return


    print(
        "[PYTHON] Capture session ended."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()