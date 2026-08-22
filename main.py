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

# ------------------------------------------------------------
# Final framebuffer size
# ------------------------------------------------------------

OUTPUT_WIDTH = 320
OUTPUT_HEIGHT = 224

# ------------------------------------------------------------
# Actual 2x SNES game image inside the 600x500 capture
#
# 256x224 -> 512x448
# ------------------------------------------------------------

GAME_WIDTH = 512
GAME_HEIGHT = 448

CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

# ------------------------------------------------------------
# ModFS
# ------------------------------------------------------------

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
    # Create a REAL ZIP if it doesn't exist.
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

        return


    # ========================================================
    # Verify it is actually a ZIP.
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
    # Don't rewrite unchanged frames.
    # ========================================================

    if rgb_text == last_rgb_text:
        return


    with write_lock:

        temp_path = MODFS_PATH + ".tmp"


        # ====================================================
        # Preserve existing ModFS files.
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
        # Create completely new valid ZIP.
        # ====================================================

        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as new_zip:

            # Preserve other files.

            for filename, content in old_files.items():

                new_zip.writestr(
                    filename,
                    content
                )


            # Write new framebuffer.

            new_zip.writestr(
                RGB_FILENAME,
                rgb_text
            )


        # ====================================================
        # Atomically replace old ModFS.
        # ====================================================

        os.replace(
            temp_path,
            MODFS_PATH
        )


        last_rgb_text = rgb_text


# ============================================================
# CAPTURE -> 320x224 RGB
# ============================================================

def frame_to_rgb(frame):

    """
    Snes9x capture:

        approximately 600x500

    Actual 2x game image:

        512x448

    Final framebuffer:

        320x224
    """


    buffer = frame.frame_buffer


    if buffer is None:
        return None


    if not isinstance(
        buffer,
        np.ndarray
    ):

        buffer = np.asarray(
            buffer
        )


    # ========================================================
    # Validate frame.
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


    source_height = buffer.shape[0]
    source_width = buffer.shape[1]


    if (
        source_width < CAPTURE_WIDTH
        or
        source_height < CAPTURE_HEIGHT
    ):

        print(
            "[PYTHON] Capture smaller than expected:",
            f"{source_width}x{source_height}"
        )

        return None


    # ========================================================
    # CENTER CROP 600x500 -> 512x448
    #
    # This isolates the actual 2x SNES image.
    # ========================================================

    left = (
        source_width -
        GAME_WIDTH
    ) // 2


    top = (
        source_height -
        GAME_HEIGHT
    ) // 2


    cropped = buffer[
        top:
        top + GAME_HEIGHT,

        left:
        left + GAME_WIDTH,

        :
    ]


    # ========================================================
    # BGRA -> RGB
    # ========================================================

    rgb = cropped[
        :, :, :3
    ][
        :, :, ::-1
    ].copy()


    # ========================================================
    # 512x448 -> 320x224
    #
    # We deliberately do NOT use nearest-neighbor.
    #
    # 512 -> 320 is not an integer scale.
    #
    # LANCZOS gives a proper resample instead of selecting
    # arbitrary source pixels and producing uneven pixel sizes.
    # ========================================================

    image = Image.fromarray(
        rgb,
        mode="RGB"
    )


    image = image.resize(
        (
            OUTPUT_WIDTH,
            OUTPUT_HEIGHT
        ),
        Image.Resampling.LANCZOS
    )


    # ========================================================
    # Return NumPy RGB array.
    # ========================================================

    return np.asarray(
        image,
        dtype=np.uint8
    )


# ============================================================
# RGB -> TEXT
# ============================================================

def rgb_to_text(rgb):

    expected_shape = (
        OUTPUT_HEIGHT,
        OUTPUT_WIDTH,
        3
    )


    if rgb.shape != expected_shape:

        raise ValueError(
            "Unexpected RGB shape: " +
            str(rgb.shape) +
            " expected " +
            str(expected_shape)
        )


    rgb = np.asarray(
        rgb,
        dtype=np.uint8
    )


    # ========================================================
    # Row-major:
    #
    # 320 pixels
    # then next row
    # ...
    # 224 rows
    #
    # Total:
    #
    # 320 * 224 = 71680 pixels
    # ========================================================

    flat = rgb.reshape(
        -1,
        3
    )


    lines = [
        f"{int(r)},{int(g)},{int(b)}"
        for r, g, b in flat
    ]


    return "\n".join(
        lines
    )


# ============================================================
# CAPTURE
# ============================================================

capture = WindowsCapture(

    cursor_capture=False,

    draw_border=False,

    window_name=WINDOW_NAME,

    monitor_index=None,

    minimum_update_interval=
        MINIMUM_UPDATE_INTERVAL,
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
        # 600x500 -> 512x448 -> 320x224
        # ====================================================

        rgb = frame_to_rgb(
            frame
        )


        if rgb is None:
            return


        # ====================================================
        # Convert to text.
        # ====================================================

        rgb_text = rgb_to_text(
            rgb
        )


        # ====================================================
        # Write into Earthbound.modfs.
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

    capture_closed = False


    print(
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Snes9x RGB framebuffer"
    )

    print(
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Capture window:",
        WINDOW_NAME
    )

    print(
        "[PYTHON] Capture:",
        f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Game crop:",
        f"{GAME_WIDTH}x{GAME_HEIGHT}"
    )

    print(
        "[PYTHON] Output:",
        f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}"
    )

    print(
        "[PYTHON] Pixels:",
        OUTPUT_WIDTH * OUTPUT_HEIGHT
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )


    # ========================================================
    # Make sure ModFS exists.
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