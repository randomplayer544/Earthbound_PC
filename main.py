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

SOURCE_WIDTH = 160
SOURCE_HEIGHT = 120

CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

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


# ============================================================
# MODFS
# ============================================================

def ensure_modfs():

    directory = os.path.dirname(MODFS_PATH)

    os.makedirs(
        directory,
        exist_ok=True
    )

    if not os.path.exists(MODFS_PATH):

        print("[PYTHON] Creating:", MODFS_PATH)

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

        print("[PYTHON] Invalid modfs. Recreating.")

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


# ============================================================
# WRITE RGB
# ============================================================

def write_rgb_to_modfs(rgb_text):

    global last_rgb_text

    if rgb_text == last_rgb_text:
        return

    with write_lock:

        temp_path = MODFS_PATH + ".tmp"

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

                    old_files[info.filename] = (
                        old_zip.read(info.filename)
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
# RESIZE 600x500 -> 160x120
#
# Uses mathematical nearest-neighbour sampling.
#
# The entire captured Snes9x window is used.
# ============================================================

def resize_frame(rgb):

    source_h, source_w = rgb.shape[:2]

    if source_w != CAPTURE_WIDTH or source_h != CAPTURE_HEIGHT:

        print(
            "[PYTHON] Capture dimensions:",
            f"{source_w}x{source_h}"
        )

    # Mathematical sampling positions.
    #
    # This does not guess a crop.
    # It samples the complete captured window.

    x_indices = (
        np.floor(
            np.arange(SOURCE_WIDTH)
            * source_w
            / SOURCE_WIDTH
        ).astype(np.int32)
    )

    y_indices = (
        np.floor(
            np.arange(SOURCE_HEIGHT)
            * source_h
            / SOURCE_HEIGHT
        ).astype(np.int32)
    )

    x_indices = np.clip(
        x_indices,
        0,
        source_w - 1
    )

    y_indices = np.clip(
        y_indices,
        0,
        source_h - 1
    )

    resized = rgb[
        y_indices[:, None],
        x_indices[None, :],
        :
    ]

    return resized.copy()


# ============================================================
# FRAME -> RGB
# ============================================================

def frame_to_rgb(frame):

    buffer = frame.frame_buffer

    if buffer is None:
        return None

    if not isinstance(buffer, np.ndarray):

        buffer = np.asarray(buffer)

    if buffer.ndim != 3:
        return None

    if buffer.shape[2] < 3:
        return None

    source_height = buffer.shape[0]
    source_width = buffer.shape[1]

    if (
        source_width < 1
        or
        source_height < 1
    ):
        return None

    # Windows capture is BGRA.
    # Convert to RGB.

    rgb = buffer[
        :, :, :3
    ][:, :, ::-1]

    # Resize the ENTIRE capture.
    rgb = resize_frame(rgb)

    return rgb


# ============================================================
# RGB -> TEXT
# ============================================================

def rgb_to_text(rgb):

    if rgb.shape != (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
        3
    ):

        raise ValueError(
            "Unexpected RGB shape: "
            + str(rgb.shape)
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

    return "\n".join(lines)


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

        rgb = frame_to_rgb(frame)

        if rgb is None:
            return

        rgb_text = rgb_to_text(rgb)

        write_rgb_to_modfs(
            rgb_text
        )

    except Exception as error:

        print(
            "[PYTHON] Frame error:",
            repr(error)
        )


# ============================================================
# CLOSED
# ============================================================

@capture.event
def on_closed():

    global capture_closed

    capture_closed = True

    print(
        "[PYTHON] Capture closed."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global capture_closed

    capture_closed = False

    print(
        "[PYTHON] =========================================="
    )

    print(
        "[PYTHON] Snes9x -> 160x120 RGB framebuffer"
    )

    print(
        "[PYTHON] Capture: entire 600x500 window"
    )

    print(
        "[PYTHON] Output: 160x120"
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )

    print(
        "[PYTHON] =========================================="
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