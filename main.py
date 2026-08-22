import os
import time
import zipfile
import threading
import ctypes
from ctypes import wintypes

import numpy as np

from windows_capture import WindowsCapture


# ============================================================
# SETTINGS
# ============================================================

WIDTH = 224
HEIGHT = 168

APPDATA = os.environ["APPDATA"]

MODFS_DIR = os.path.join(
    APPDATA,
    "sm64coopdx"
)

RGB_MODFS = os.path.join(
    MODFS_DIR,
    "earthbound.modfs"
)

INPUT_MODFS = os.path.join(
    MODFS_DIR,
    "earthbound_input.modfs"
)

RGB_FILENAME = "rgb.txt"
INPUT_FILENAME = "input.txt"


# ============================================================
# THREAD STATE
# ============================================================

running = True

frame_lock = threading.Lock()

latest_frame = None

frame_changed = False


# ============================================================
# INPUT STATE
# ============================================================

last_input_data = None

input_lock = threading.Lock()


# ============================================================
# WINDOWS KEYBOARD API
# ============================================================

user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):

    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        (
            "dwExtraInfo",
            ctypes.POINTER(wintypes.ULONG)
        )
    ]


class INPUT(ctypes.Structure):

    _fields_ = [
        ("type", wintypes.DWORD),
        ("ki", KEYBDINPUT)
    ]


# ============================================================
# WINDOWS VIRTUAL KEYS
# ============================================================

VK_W = 0x57
VK_A = 0x41
VK_S = 0x53
VK_D = 0x44

VK_SPACE = 0x20
VK_CONTROL = 0x11

VK_1 = 0x31
VK_2 = 0x32

VK_Q = 0x51
VK_E = 0x45


# ============================================================
# KEY STATE
# ============================================================

current_keys = {}


def send_key(vk, pressed):

    previous = current_keys.get(
        vk,
        False
    )

    if previous == pressed:
        return

    current_keys[vk] = pressed

    flags = 0

    if not pressed:
        flags |= KEYEVENTF_KEYUP

    extra = wintypes.ULONG(0)

    keyboard_input = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=ctypes.pointer(extra)
        )
    )

    user32.SendInput(
        1,
        ctypes.byref(keyboard_input),
        ctypes.sizeof(INPUT)
    )


# ============================================================
# RELEASE ALL
# ============================================================

def release_all_keys():

    for vk in list(current_keys.keys()):

        if current_keys[vk]:

            send_key(
                vk,
                False
            )


# ============================================================
# APPLY EARTHBOUND INPUT
# ============================================================

def apply_input(values):

    if len(values) != 10:
        return


    up = values[0] != 0
    down = values[1] != 0
    left = values[2] != 0
    right = values[3] != 0

    a = values[4] != 0
    b = values[5] != 0

    l = values[6] != 0
    r = values[7] != 0

    x = values[8] != 0
    y = values[9] != 0


    # --------------------------------------------------------
    # D-PAD
    # --------------------------------------------------------

    send_key(VK_W, up)
    send_key(VK_S, down)
    send_key(VK_A, left)
    send_key(VK_D, right)


    # --------------------------------------------------------
    # BUTTONS
    # --------------------------------------------------------

    send_key(VK_SPACE, a)
    send_key(VK_CONTROL, b)

    send_key(VK_1, l)
    send_key(VK_2, r)

    send_key(VK_Q, x)
    send_key(VK_E, y)


# ============================================================
# READ INPUT MODFS
# ============================================================

def read_input_modfs():

    global last_input_data

    if not os.path.exists(INPUT_MODFS):
        return

    try:

        with zipfile.ZipFile(
            INPUT_MODFS,
            "r"
        ) as archive:

            data = archive.read(
                INPUT_FILENAME
            ).decode(
                "utf-8",
                errors="ignore"
            )

    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        KeyError
    ):

        # Lua may be in the middle of saving.
        return


    data = data.strip()

    if not data:
        return


    if data == last_input_data:
        return


    try:

        values = [
            int(value)
            for value in data.split(",")
        ]

    except ValueError:

        return


    if len(values) != 10:
        return


    last_input_data = data

    apply_input(values)


# ============================================================
# INPUT THREAD
# ============================================================

def input_worker():

    while running:

        try:

            read_input_modfs()

        except Exception as error:

            print(
                "[INPUT] Error:",
                repr(error)
            )

        time.sleep(0.005)


# ============================================================
# CREATE RGB MODFS
# ============================================================

def write_rgb_modfs(rgb_text):

    os.makedirs(
        MODFS_DIR,
        exist_ok=True
    )

    temporary_path = RGB_MODFS + ".tmp"


    with zipfile.ZipFile(
        temporary_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1
    ) as archive:

        archive.writestr(
            RGB_FILENAME,
            rgb_text
        )


    os.replace(
        temporary_path,
        RGB_MODFS
    )


# ============================================================
# FRAME -> RGB TEXT
# ============================================================

def frame_to_rgb_text(frame_buffer):

    # --------------------------------------------------------
    # Windows Capture gives BGRA.
    # We only need BGR here, then reverse to RGB.
    # --------------------------------------------------------

    image = frame_buffer[:, :, :3]


    # --------------------------------------------------------
    # Resize directly with nearest-neighbor.
    # --------------------------------------------------------

    source_height = image.shape[0]
    source_width = image.shape[1]


    if (
        source_width == WIDTH
        and
        source_height == HEIGHT
    ):

        resized = image

    else:

        x_indices = (
            np.arange(WIDTH)
            * source_width
            // WIDTH
        )

        y_indices = (
            np.arange(HEIGHT)
            * source_height
            // HEIGHT
        )

        resized = image[
            y_indices[:, None],
            x_indices[None, :]
        ]


    # --------------------------------------------------------
    # BGRA/BGR -> RGB
    # --------------------------------------------------------

    rgb = resized[:, :, ::-1]


    # --------------------------------------------------------
    # Generate RGB text.
    # --------------------------------------------------------

    flat = rgb.reshape(
        -1,
        3
    )


    lines = [
        f"{int(pixel[0])},"
        f"{int(pixel[1])},"
        f"{int(pixel[2])}"
        for pixel in flat
    ]


    return "\n".join(lines)


# ============================================================
# RGB WORKER
# ============================================================

def rgb_worker():

    global latest_frame
    global frame_changed

    last_written_frame = None

    while running:

        frame = None

        with frame_lock:

            if frame_changed:

                frame = latest_frame.copy()

                frame_changed = False


        if frame is None:

            time.sleep(0.001)

            continue


        try:

            rgb_text = frame_to_rgb_text(
                frame
            )


            # ------------------------------------------------
            # Don't rewrite the ModFS if the RGB image didn't
            # actually change.
            # ------------------------------------------------

            if rgb_text == last_written_frame:

                continue


            write_rgb_modfs(
                rgb_text
            )


            last_written_frame = rgb_text

        except Exception as error:

            print(
                "[RGB] Worker error:",
                repr(error)
            )

            time.sleep(0.01)


# ============================================================
# WINDOWS CAPTURE
# ============================================================

capture = WindowsCapture(
    cursor_capture=False,
    draw_border=False
)


# ============================================================
# FRAME CALLBACK
# ============================================================

@capture.event
def on_frame_arrived(
    frame,
    capture_control
):

    global latest_frame
    global frame_changed


    try:

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT read ZIP files here.
        # Do NOT write ZIP files here.
        # Do NOT perform PIL conversion here.
        #
        # Only copy the captured pixels and return.
        # ----------------------------------------------------

        buffer = np.array(
            frame.frame_buffer,
            copy=True
        )


        with frame_lock:

            latest_frame = buffer

            frame_changed = True


    except Exception as error:

        print(
            "[CAPTURE] Frame error:",
            repr(error)
        )


# ============================================================
# CAPTURE CLOSED
# ============================================================

@capture.event
def on_closed():

    global running

    running = False

    release_all_keys()

    print(
        "[CAPTURE] Capture closed"
    )


# ============================================================
# START
# ============================================================

print(
    "============================================"
)

print(
    "EarthBound SM64CoopDX Bridge"
)

print(
    "============================================"
)

print(
    "RGB ModFS:"
)

print(
    RGB_MODFS
)

print()

print(
    "Input ModFS:"
)

print(
    INPUT_MODFS
)

print()

print(
    "Controls:"
)

print(
    "W = Up"
)

print(
    "A = Left"
)

print(
    "S = Down"
)

print(
    "D = Right"
)

print(
    "SPACE = A"
)

print(
    "CTRL = B"
)

print(
    "1 = L"
)

print(
    "2 = R"
)

print(
    "Q = X"
)

print(
    "E = Y"
)

print(
    "============================================"
)


# ============================================================
# WORKERS
# ============================================================

input_thread = threading.Thread(
    target=input_worker,
    daemon=True
)

rgb_thread = threading.Thread(
    target=rgb_worker,
    daemon=True
)


input_thread.start()
rgb_thread.start()


# ============================================================
# CAPTURE
# ============================================================

try:

    capture.start()

except Exception as error:

    print(
        "[CAPTURE] Fatal error:",
        repr(error)
    )

finally:

    running = False

    release_all_keys()

    print(
        "[BRIDGE] Stopped."
    )