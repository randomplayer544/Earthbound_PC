from windows_capture import WindowsCapture
from PIL import Image
import numpy as np

import zipfile
import os
import time
import ctypes
from ctypes import wintypes


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

Snes9x window should be focused for SendInput to reach it.


# ============================================================
# WINDOWS KEYBOARD
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
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
    ]


class INPUT(ctypes.Structure):

    _fields_ = [
        ("type", wintypes.DWORD),
        ("ki", KEYBDINPUT)
    ]


# ============================================================
# KEY CODES
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
# CURRENT KEY STATE
# ============================================================

current_keys = {}


def send_key(vk, down):

    previous = current_keys.get(vk, False)

    if previous == down:
        return

    current_keys[vk] = down


    flags = 0

    if not down:
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

    for vk, pressed in list(current_keys.items()):

        if pressed:
            send_key(vk, False)


# ============================================================
# INPUT -> SNES9X
# ============================================================

def apply_input(values):

    if len(values) != 10:
        return


    up = values[0]
    down = values[1]
    left = values[2]
    right = values[3]

    a = values[4]
    b = values[5]

    l = values[6]
    r = values[7]

    x = values[8]
    y = values[9]


    # --------------------------------------------------------
    # D-PAD
    # --------------------------------------------------------

    send_key(
        VK_W,
        up
    )

    send_key(
        VK_S,
        down
    )

    send_key(
        VK_A,
        left
    )

    send_key(
        VK_D,
        right
    )


    # --------------------------------------------------------
    # SNES BUTTONS
    # --------------------------------------------------------

    send_key(
        VK_SPACE,
        a
    )

    send_key(
        VK_CONTROL,
        b
    )

    send_key(
        VK_1,
        l
    )

    send_key(
        VK_2,
        r
    )

    send_key(
        VK_Q,
        x
    )

    send_key(
        VK_E,
        y
    )


# ============================================================
# READ INPUT MODFS
# ============================================================

last_input = None


def read_input():

    global last_input


    if not os.path.exists(INPUT_MODFS):
        return


    try:

        with zipfile.ZipFile(
            INPUT_MODFS,
            "r"
        ) as z:

            data =
                z.read(
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

        # Lua may currently be saving the ModFS.
        # Just try again next loop.
        return


    data = data.strip()


    if not data:
        return


    if data == last_input:
        return


    last_input = data


    try:

        values = [
            int(x)
            for x in data.split(",")
        ]

    except ValueError:
        return


    apply_input(values)


# ============================================================
# RGB MODFS
# ============================================================

def write_rgb_modfs(rgb_text):

    os.makedirs(
        MODFS_DIR,
        exist_ok=True
    )


    temp_path =
        RGB_MODFS + ".tmp"


    # --------------------------------------------------------
    # Write a completely new ZIP.
    # --------------------------------------------------------

    with zipfile.ZipFile(
        temp_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1
    ) as z:

        z.writestr(
            RGB_FILENAME,
            rgb_text
        )


    # --------------------------------------------------------
    # Replace the old ModFS atomically.
    # --------------------------------------------------------

    os.replace(
        temp_path,
        RGB_MODFS
    )


# ============================================================
# SCREEN -> RGB TEXT
# ============================================================

def image_to_rgb_text(image):

    image =
        image.resize(
            (WIDTH, HEIGHT),
            Image.Resampling.NEAREST
        ).convert("RGB")


    array =
        np.asarray(image)


    lines = []


    for row in array:

        for pixel in row:

            r = int(pixel[0])
            g = int(pixel[1])
            b = int(pixel[2])


            lines.append(
                f"{r},{g},{b}"
            )


    return "\n".join(lines)


# ============================================================
# CAPTURE
# ============================================================

capture = WindowsCapture(
    cursor_capture=False
)


@capture.event
def on_frame_arrived(frame, capture_control):

    # --------------------------------------------------------
    # Read multiplayer input every captured frame.
    # --------------------------------------------------------

    read_input()


    # --------------------------------------------------------
    # Capture Snes9x.
    # --------------------------------------------------------

    image =
        frame.convert_to_pil()


    # --------------------------------------------------------
    # Convert to EarthBound framebuffer.
    # --------------------------------------------------------

    rgb_text =
        image_to_rgb_text(
            image
        )


    # --------------------------------------------------------
    # Write framebuffer.
    # --------------------------------------------------------

    try:

        write_rgb_modfs(
            rgb_text
        )

    except OSError as e:

        print(
            "[RGB] ModFS write error:",
            e
        )


@capture.event
def on_closed():

    print(
        "[CAPTURE] Capture closed"
    )

    release_all_keys()


# ============================================================
# MAIN
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
    "Framebuffer:"
)

print(
    RGB_MODFS
)

print()

print(
    "Input:"
)

print(
    INPUT_MODFS
)

print()

print(
    "Controls:"
)

print(
    "W/A/S/D = D-Pad"
)

print(
    "Space = A"
)

print(
    "Ctrl = B"
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

print()

print(
    "Make sure Snes9x has focus."
)

print(
    "============================================"
)


try:

    capture.start()

finally:

    release_all_keys()