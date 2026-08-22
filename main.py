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

# Output framebuffer
OUTPUT_WIDTH = 128
OUTPUT_HEIGHT = 96

# Expected Snes9x capture
CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

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
# MODFS
# ============================================================

def ensure_modfs():

    directory = os.path.dirname(MODFS_PATH)

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
            "[PYTHON] Earthbound.modfs is not a valid ZIP."
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
            "[PYTHON] Recreated valid Earthbound.modfs."
        )


# ============================================================
# WRITE RGB.TXT
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

        # ----------------------------------------------------
        # Build completely new ZIP.
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Atomic replacement.
        # ----------------------------------------------------

        os.replace(
            temp_path,
            MODFS_PATH
        )

        last_rgb_text = rgb_text


# ============================================================
# CAPTURE -> 128x96
# ============================================================

def frame_to_rgb(frame):

    buffer = frame.frame_buffer

    if buffer is None:
        return None

    if not isinstance(buffer, np.ndarray):

        buffer = np.asarray(buffer)

    if buffer.ndim != 3:

        print(
            "[PYTHON] Invalid frame:",
            buffer.shape
        )

        return None

    if buffer.shape[2] < 3:

        print(
            "[PYTHON] Not enough color channels:",
            buffer.shape
        )

        return None

    source_height = buffer.shape[0]
    source_width = buffer.shape[1]

    if (
        source_width < OUTPUT_WIDTH
        or
        source_height < OUTPUT_HEIGHT
    ):

        print(
            "[PYTHON] Capture too small:",
            f"{source_width}x{source_height}"
        )

        return None

    # ========================================================
    # MATHEMATICAL RESIZE
    #
    # The Snes9x capture is approximately 600x500.
    #
    # We preserve the complete captured image and map it
    # mathematically into 128x96.
    # ========================================================

    x_positions = (
        (
            np.arange(OUTPUT_WIDTH) + 0.5
        )
        *
        source_width
        /
        OUTPUT_WIDTH
    ).astype(np.int32)

    y_positions = (
        (
            np.arange(OUTPUT_HEIGHT) + 0.5
        )
        *
        source_height
        /
        OUTPUT_HEIGHT
    ).astype(np.int32)

    # Prevent possible boundary overflow.

    x_positions = np.clip(
        x_positions,
        0,
        source_width - 1
    )

    y_positions = np.clip(
        y_positions,
        0,
        source_height - 1
    )

    # ========================================================
    # Nearest mathematical sampling.
    #
    # No guessed crop dimensions.
    # ========================================================

    sampled = buffer[
        y_positions[:, None],
        x_positions[None, :],
        :3
    ]

    # ========================================================
    # Windows capture is BGRA.
    # Convert:
    #
    # B G R
    # ->
    # R G B
    # ========================================================

    rgb = sampled[
        :, :, ::-1
    ].copy()

    return rgb


# ============================================================
# RGB -> TEXT
# ============================================================

def rgb_to_text(rgb):

    if rgb.shape != (
        OUTPUT_HEIGHT,
        OUTPUT_WIDTH,
        3
    ):

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
# CAPTURE CLOSED
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
        "=================================================="
    )

    print(
        "[PYTHON] Snes9x 128x96 framebuffer"
    )

    print(
        "[PYTHON] Capture:",
        f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Output:",
        f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}"
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )

    print(
        "=================================================="
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