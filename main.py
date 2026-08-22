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

# Lua framebuffer size
SOURCE_WIDTH = 301
SOURCE_HEIGHT = 224

# Expected Snes9x capture size
CAPTURE_WIDTH = 600
CAPTURE_HEIGHT = 500

# Exact ModFS location
MODFS_PATH = os.path.expandvars(
    r"%APPDATA%\sm64coopdx\sav\earthbound.modfs"
)

RGB_FILENAME = "rgb.txt"

# Capture update interval in milliseconds
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

    # --------------------------------------------------------
    # Create a REAL ZIP .modfs if it doesn't exist.
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Make sure the existing .modfs is actually a ZIP.
    # --------------------------------------------------------

    if not zipfile.is_zipfile(MODFS_PATH):

        print(
            "[PYTHON] Existing earthbound.modfs "
            "is not a valid ZIP."
        )

        print(
            "[PYTHON] Recreating it..."
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
            "[PYTHON] Valid earthbound.modfs created."
        )


# ============================================================
# WRITE RGB.TXT INTO MODFS
# ============================================================

def write_rgb_to_modfs(rgb_text):

    global last_rgb_text

    # --------------------------------------------------------
    # Don't rewrite the ZIP when nothing changed.
    # --------------------------------------------------------

    if rgb_text == last_rgb_text:
        return


    with write_lock:

        temp_path = MODFS_PATH + ".tmp"


        # ----------------------------------------------------
        # Preserve every other file in the ModFS.
        # ----------------------------------------------------

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
        # Create a new valid ZIP.
        # ----------------------------------------------------

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

            # Write framebuffer.
            new_zip.writestr(
                RGB_FILENAME,
                rgb_text
            )


        # ----------------------------------------------------
        # Replace the old ModFS atomically.
        # ----------------------------------------------------

        os.replace(
            temp_path,
            MODFS_PATH
        )


        last_rgb_text = rgb_text


# ============================================================
# CAPTURE -> 301x224 RGB
# ============================================================

def frame_to_rgb(frame):

   # """
    #Capture:

        #approximately 600x500

    #Output:

        #exactly 301x224 RGB

    #The capture is taken from the entire Snes9x window.

    #We crop the CENTER of that capture to the 301x224
    #framebuffer used by Lua.
   # ""

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


    # --------------------------------------------------------
    # Validate frame.
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Show the actual capture size once if useful.
    # --------------------------------------------------------

    if (
        capture_width != CAPTURE_WIDTH
        or
        capture_height != CAPTURE_HEIGHT
    ):

        print(
            "[PYTHON] Actual capture:",
            f"{capture_width}x{capture_height}"
        )


    # --------------------------------------------------------
    # Make sure the captured window is large enough.
    # --------------------------------------------------------

    if (
        capture_width < SOURCE_WIDTH
        or
        capture_height < SOURCE_HEIGHT
    ):

        print(
            "[PYTHON] Capture too small:",
            f"{capture_width}x{capture_height}"
        )

        return None


    # ========================================================
    # CENTER CROP
    # ========================================================
    #
    # Example:
    #
    # capture = 600x500
    #
    # framebuffer = 301x224
    #
    # The crop is centered inside the captured window.
    #
    # ========================================================

    left = (
        capture_width -
        SOURCE_WIDTH
    ) // 2


    top = (
        capture_height -
        SOURCE_HEIGHT
    ) // 2


    cropped = buffer[
        top:
        top + SOURCE_HEIGHT,

        left:
        left + SOURCE_WIDTH,

        :
    ]


    # --------------------------------------------------------
    # BGRA -> RGB
    # --------------------------------------------------------

    rgb = cropped[
        :, :, :3
    ][
        :, :, ::-1
    ].copy()


    return rgb


# ============================================================
# RGB ARRAY -> TEXT
# ============================================================

def rgb_to_text(rgb):

    if rgb.shape != (
        SOURCE_HEIGHT,
        SOURCE_WIDTH,
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


    # --------------------------------------------------------
    # Flatten while preserving row order.
    #
    # 301 pixels
    # row 1
    #
    # 301 pixels
    # row 2
    #
    # ...
    #
    # 224 rows
    # --------------------------------------------------------

    flat = rgb.reshape(
        -1,
        3
    )


    # --------------------------------------------------------
    # Generate exactly:
    #
    # 301 * 224 = 67424 RGB lines
    # --------------------------------------------------------

    lines = [
        f"{int(r)},{int(g)},{int(b)}"
        for r, g, b in flat
    ]


    return "\n".join(
        lines
    )


# ============================================================
# WINDOWS CAPTURE
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


        # ----------------------------------------------------
        # Capture the Snes9x window.
        # ----------------------------------------------------

        rgb = frame_to_rgb(
            frame
        )


        if rgb is None:
            return


        # ----------------------------------------------------
        # Convert to rgb.txt.
        # ----------------------------------------------------

        rgb_text = rgb_to_text(
            rgb
        )


        # ----------------------------------------------------
        # Write to earthbound.modfs.
        # ----------------------------------------------------

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
        "or capture ended."
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
        "[PYTHON] Snes9x RGB framebuffer capture"
    )

    print(
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Window:",
        WINDOW_NAME
    )

    print(
        "[PYTHON] Expected capture:",
        f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}"
    )

    print(
        "[PYTHON] Output framebuffer:",
        f"{SOURCE_WIDTH}x{SOURCE_HEIGHT}"
    )

    print(
        "[PYTHON] ModFS:",
        MODFS_PATH
    )


    # --------------------------------------------------------
    # Create/verify real ZIP ModFS.
    # --------------------------------------------------------

    ensure_modfs()


    # --------------------------------------------------------
    # Start Windows Capture.
    # --------------------------------------------------------

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