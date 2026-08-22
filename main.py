import os
import zipfile
import threading

import numpy as np

from windows_capture import (
    WindowsCapture,
    Frame,
    InternalCaptureControl,
)


# ============================================================
# SETTINGS
# ============================================================

WINDOW_NAME = "Snes9x"

# Final framebuffer
SOURCE_WIDTH = 301
SOURCE_HEIGHT = 224

# Snes9x capture
CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

# Actual 2x SNES image
GAME_WIDTH = 512
GAME_HEIGHT = 448

# ModFS
MODFS_PATH = os.path.expandvars(
    r"%APPDATA%\sm64coopdx\sav\earthbound.modfs"
)

RGB_FILENAME = "rgb.txt"

MINIMUM_UPDATE_INTERVAL = 16


# ============================================================
# STATE
# ============================================================

capture_closed = False

write_lock = threading.Lock()

last_rgb_text = None

printed_capture_size = False


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


    if not zipfile.is_zipfile(MODFS_PATH):

        print(
            "[PYTHON] Existing Earthbound.modfs "
            "is not a valid ZIP."
        )

        try:
            os.remove(MODFS_PATH)
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

    if rgb_text == last_rgb_text:
        return

    with write_lock:

        temp_path = (
            MODFS_PATH +
            ".tmp"
        )

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


        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as new_zip:

            for filename, content in old_files.items():

                new_zip.writestr(
                    filename,
                    content
                )

            new_zip.writestr(
                RGB_FILENAME,
                rgb_text
            )


        os.replace(
            temp_path,
            MODFS_PATH
        )

        last_rgb_text = rgb_text


# ============================================================
# RESIZE WIDTH ONLY
# ============================================================

def resize_width_nearest(image, new_width):

    """
    Resize only the horizontal dimension.

    Input:
        512x448

    Output:
        301x448

    Height is untouched.
    """

    old_height = image.shape[0]
    old_width = image.shape[1]

    x_indices = (
        np.arange(new_width)
        * old_width
        // new_width
    )

    return image[
        :,
        x_indices,
        :
    ]


# ============================================================
# CONVERT CAPTURE TO 301x224 RGB
# ============================================================

def frame_to_rgb(frame):

    global printed_capture_size

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


    if not printed_capture_size:

        print(
            "[PYTHON] Capture size:",
            f"{capture_width}x{capture_height}"
        )

        print(
            "[PYTHON] Game area:",
            f"{GAME_WIDTH}x{GAME_HEIGHT}"
        )

        print(
            "[PYTHON] Final framebuffer:",
            f"{SOURCE_WIDTH}x{SOURCE_HEIGHT}"
        )

        printed_capture_size = True


    # ========================================================
    # CENTER CROP 512x448 FROM 600x500
    # ========================================================

    if (
        capture_width < GAME_WIDTH
        or
        capture_height < GAME_HEIGHT
    ):

        print(
            "[PYTHON] Capture too small:",
            f"{capture_width}x{capture_height}"
        )

        return None


    left = (
        capture_width -
        GAME_WIDTH
    ) // 2

    top = (
        capture_height -
        GAME_HEIGHT
    ) // 2


    game = buffer[
        top:
        top + GAME_HEIGHT,

        left:
        left + GAME_WIDTH,

        :
    ]


    # ========================================================
    # BGRA -> RGB
    # ========================================================

    game_rgb = game[
        :, :, :3
    ][
        :, :, ::-1
    ]


    # ========================================================
    # REDUCE HEIGHT 448 -> 224
    #
    # This is an exact 2x reduction vertically.
    # ========================================================

    game_rgb = game_rgb[
        0::2,
        :,
        :
    ]


    # ========================================================
    # RESIZE WIDTH 512 -> 301
    #
    # Height remains exactly 224.
    #
    # Nearest-neighbor is used so there is no interpolation
    # blur introduced into the framebuffer.
    # ========================================================

    rgb = resize_width_nearest(
        game_rgb,
        SOURCE_WIDTH
    ).copy()


    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    expected_shape = (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
        3
    )

    if rgb.shape != expected_shape:

        print(
            "[PYTHON] Wrong final RGB shape:",
            rgb.shape,
            "expected:",
            expected_shape
        )

        return None


    return rgb


# ============================================================
# RGB -> TEXT
# ============================================================

def rgb_to_text(rgb):

    expected_shape = (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
        3
    )

    if rgb.shape != expected_shape:

        raise ValueError(
            "Unexpected RGB shape: " +
            str(rgb.shape)
        )


    rgb = np.asarray(
        rgb,
        dtype=np.uint8
    )


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


        rgb = frame_to_rgb(
            frame
        )

        if rgb is None:
            return


        rgb_text = rgb_to_text(
            rgb
        )


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
        "[PYTHON] Snes9x 301x224 RGB framebuffer"
    )

    print(
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Capture:",
        f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Game:",
        f"{GAME_WIDTH}x{GAME_HEIGHT}"
    )

    print(
        "[PYTHON] Output:",
        f"{SOURCE_WIDTH}x{SOURCE_HEIGHT}"
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )


    ensure_modfs()


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