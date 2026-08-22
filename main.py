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

WIDTH = 64
HEIGHT = 54

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
# CREATE / VERIFY MODFS
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
            "[PYTHON] Invalid ModFS. Recreating."
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


# ============================================================
# WRITE RGB.TXT
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
# MATHEMATICAL NEAREST-NEIGHBOR RESIZE
# ============================================================

def resize_nearest(
    image,
    new_width,
    new_height
):

    source_height = image.shape[0]
    source_width = image.shape[1]


    y_indices = (
        np.arange(new_height)
        * source_height
        // new_height
    )


    x_indices = (
        np.arange(new_width)
        * source_width
        // new_width
    )


    return image[
        y_indices[:, None],
        x_indices[None, :],
        :
    ]


# ============================================================
# FRAME -> 64x54 RGB
# ============================================================

def frame_to_rgb(frame):

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
        return None


    if buffer.shape[2] < 3:
        return None


    capture_height = buffer.shape[0]
    capture_width = buffer.shape[1]


    if (
        capture_width <= 0
        or
        capture_height <= 0
    ):

        return None


    # ========================================================
    # DETECT ACTUAL CAPTURE SIZE
    # ========================================================

    target_aspect = 4.0 / 3.0

    capture_aspect = (
        capture_width /
        capture_height
    )


    # ========================================================
    # FIND LARGEST CENTERED 4:3 AREA
    # ========================================================

    if capture_aspect > target_aspect:

        crop_height = capture_height

        crop_width = int(
            round(
                crop_height *
                target_aspect
            )
        )

    else:

        crop_width = capture_width

        crop_height = int(
            round(
                crop_width /
                target_aspect
            )
        )


    crop_width = min(
        crop_width,
        capture_width
    )

    crop_height = min(
        crop_height,
        capture_height
    )


    # ========================================================
    # CENTER CROP
    # ========================================================

    left = (
        capture_width -
        crop_width
    ) // 2


    top = (
        capture_height -
        crop_height
    ) // 2


    cropped = buffer[
        top:
        top + crop_height,

        left:
        left + crop_width,

        :
    ]


    # ========================================================
    # BGRA -> RGB
    # ========================================================

    rgb = cropped[
        :, :, :3
    ][
        :, :, ::-1
    ]


    # ========================================================
    # RESIZE MATHEMATICALLY
    # ========================================================

    resized = resize_nearest(
        rgb,
        WIDTH,
        HEIGHT
    )


    return resized.copy()


# ============================================================
# RGB -> TEXT
# ============================================================

def rgb_to_text(rgb):

    if rgb.shape != (
        HEIGHT,
        WIDTH,
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
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Snes9x -> 64x54 framebuffer"
    )

    print(
        "[PYTHON] ================================================"
    )

    print(
        "[PYTHON] Window:",
        WINDOW_NAME
    )

    print(
        "[PYTHON] Resolution:",
        f"{WIDTH}x{HEIGHT}"
    )

    print(
        "[PYTHON] RGB bytes:",
        WIDTH * HEIGHT * 3
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


if __name__ == "__main__":
    main()