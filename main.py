-- ============================================================
-- RGB FRAMEBUFFER
--
-- Resolution:
--     320x224
--
-- ModFS:
--     %APPDATA%\sm64coopdx\sav\Earthbound.modfs
--
-- File:
--     rgb.txt
--
-- DISPLAY:
--     Centered
--     4:3
--
-- IMPORTANT:
--     Last valid frame remains displayed if rgb.txt
--     temporarily cannot be read.
--
-- NETWORK:
--     HOST reads ModFS
--     HOST sends framebuffer
--     CLIENTS reconstruct framebuffer
--     1024-byte chunks
-- ============================================================


local WIDTH = 320
local HEIGHT = 224

local TOTAL_PIXELS =
    WIDTH * HEIGHT

local RGB_BYTES =
    TOTAL_PIXELS * 3


-- ============================================================
-- NETWORK
-- ============================================================

local PACKET_ID = 0x52

local PACKET_START = 0x01
local PACKET_DATA  = 0x02
local PACKET_END   = 0x03

local CHUNK_SIZE = 1024

local TOTAL_CHUNKS =
    math.ceil(
        RGB_BYTES / CHUNK_SIZE
    )


-- ============================================================
-- DISPLAY
-- ============================================================

local FRAME_ASPECT = 4 / 3


-- ============================================================
-- FRAMEBUFFER
-- ============================================================

local pixels = {}

local framebuffer_loaded = false

local last_rgb = ""


-- ============================================================
-- NETWORK RECEIVE
-- ============================================================

local receiving_frame = false

local receiving_frame_id = 0

local receiving_total_chunks = 0

local received_chunks = {}

local received_chunk_count = 0


-- ============================================================
-- HOST SEND
-- ============================================================

local sending_frame = false

local sending_frame_id = 0

local sending_chunk = 1

local sending_data = nil


-- ============================================================
-- BLACK FRAME
-- ============================================================

local function create_black_frame()

    pixels = {}

    for y = 1, HEIGHT do

        pixels[y] = {}

        for x = 1, WIDTH do

            pixels[y][x] = {
                r = 0,
                g = 0,
                b = 0
            }

        end

    end

end


-- ============================================================
-- BINARY RGB -> FRAMEBUFFER
-- ============================================================

local function rgb_string_to_framebuffer(data)

    if not data then
        return false
    end


    if #data ~= RGB_BYTES then

        print(
            "[RGB] Bad network frame size: " ..
            tostring(#data) ..
            "/" ..
            tostring(RGB_BYTES)
        )

        return false

    end


    local new_pixels = {}

    for y = 1, HEIGHT do
        new_pixels[y] = {}
    end


    local index = 1


    for y = 1, HEIGHT do

        for x = 1, WIDTH do

            local r =
                string.byte(
                    data,
                    index
                )

            local g =
                string.byte(
                    data,
                    index + 1
                )

            local b =
                string.byte(
                    data,
                    index + 2
                )


            if not r
                or not g
                or not b
            then

                return false

            end


            new_pixels[y][x] = {
                r = r,
                g = g,
                b = b
            }


            index =
                index + 3

        end

    end


    -- ========================================================
    -- Atomic replacement.
    -- ========================================================

    pixels =
        new_pixels

    framebuffer_loaded =
        true


    return true

end


-- ============================================================
-- FRAMEBUFFER -> BINARY RGB
-- ============================================================

local function framebuffer_to_rgb_string()

    local output = {}

    local output_index = 1


    for y = 1, HEIGHT do

        local row =
            pixels[y]


        for x = 1, WIDTH do

            local pixel =
                row[x]


            output[output_index] =
                string.char(
                    pixel.r,
                    pixel.g,
                    pixel.b
                )


            output_index =
                output_index + 1

        end

    end


    return table.concat(
        output
    )

end


-- ============================================================
-- LOAD RGB.TXT
-- ============================================================

local function load_rgb()

    mod_fs_reload()


    local modFs =
        mod_fs_get()


    -- ========================================================
    -- IMPORTANT:
    --
    -- Failure does NOT erase the existing framebuffer.
    -- ========================================================

    if not modFs then
        return false
    end


    local file =
        modFs:get_file(
            "rgb.txt"
        )


    if not file then
        return false
    end


    file:set_text_mode(true)

    file:rewind()


    local data =
        file:read_string()


    if not data
        or
        data == ""
    then

        return false

    end


    -- ========================================================
    -- Nothing changed.
    -- ========================================================

    if data == last_rgb then
        return true
    end


    -- ========================================================
    -- Parse frame.
    -- ========================================================

    local new_pixels = {}

    for y = 1, HEIGHT do
        new_pixels[y] = {}
    end


    local index = 1


    for line in data:gmatch(
        "[^\r\n]+"
    ) do

        local r, g, b =
            line:match(
                "^%s*(%d+)%s*,%s*(%d+)%s*,%s*(%d+)%s*$"
            )


        if r and g and b then

            if index > TOTAL_PIXELS then
                break
            end


            local zero_index =
                index - 1


            local x =
                (zero_index % WIDTH) + 1


            local y =
                math.floor(
                    zero_index / WIDTH
                ) + 1


            new_pixels[y][x] = {
                r = tonumber(r),
                g = tonumber(g),
                b = tonumber(b)
            }


            index =
                index + 1

        end

    end


    local count =
        index - 1


    -- ========================================================
    -- Never apply a partial frame.
    -- ========================================================

    if count ~= TOTAL_PIXELS then

        print(
            "[RGB] Invalid frame: " ..
            tostring(count) ..
            "/" ..
            tostring(TOTAL_PIXELS)
        )

        return false

    end


    -- ========================================================
    -- Apply complete frame.
    -- ========================================================

    pixels =
        new_pixels

    last_rgb =
        data

    framebuffer_loaded =
        true


    -- ========================================================
    -- HOST NETWORK TRANSMISSION
    -- ========================================================

    if network_is_server() then

        sending_frame_id =
            (sending_frame_id + 1) %
            65536


        sending_data =
            framebuffer_to_rgb_string()


        sending_chunk =
            1


        sending_frame =
            true

    end


    return true

end


-- ============================================================
-- SEND START
-- ============================================================

local function send_frame_start()

    local packet =
        string.pack(
            "<BBHH",
            PACKET_ID,
            PACKET_START,
            sending_frame_id,
            TOTAL_CHUNKS
        )


    network_send_bytestring(
        true,
        packet
    )

end


-- ============================================================
-- SEND CHUNK
-- ============================================================

local function send_frame_chunk()

    if not sending_data then
        return
    end


    if sending_chunk > TOTAL_CHUNKS then
        return
    end


    local start_position =
        ((sending_chunk - 1) *
        CHUNK_SIZE) + 1


    local end_position =
        math.min(
            start_position +
            CHUNK_SIZE - 1,
            #sending_data
        )


    local chunk =
        string.sub(
            sending_data,
            start_position,
            end_position
        )


    local packet =
        string.pack(
            "<BBHH",
            PACKET_ID,
            PACKET_DATA,
            sending_frame_id,
            sending_chunk
        )
        ..
        chunk


    network_send_bytestring(
        true,
        packet
    )


    sending_chunk =
        sending_chunk + 1

end


-- ============================================================
-- SEND END
-- ============================================================

local function send_frame_end()

    local packet =
        string.pack(
            "<BBH",
            PACKET_ID,
            PACKET_END,
            sending_frame_id
        )


    network_send_bytestring(
        true,
        packet
    )

end


-- ============================================================
-- NETWORK RECEIVE
-- ============================================================

local function on_packet_bytestring_receive(bytestring)

    if not bytestring then
        return
    end


    if #bytestring < 2 then
        return
    end


    local packet_id,
          packet_type =
        string.unpack(
            "<BB",
            bytestring,
            1
        )


    if packet_id ~= PACKET_ID then
        return
    end


    -- ========================================================
    -- START
    -- ========================================================

    if packet_type == PACKET_START then

        if network_is_server() then
            return
        end


        local frame_id,
              total_chunks =
            string.unpack(
                "<HH",
                bytestring,
                3
            )


        receiving_frame =
            true

        receiving_frame_id =
            frame_id

        receiving_total_chunks =
            total_chunks

        received_chunks =
            {}

        received_chunk_count =
            0


        return

    end


    -- ========================================================
    -- DATA
    -- ========================================================

    if packet_type == PACKET_DATA then

        if network_is_server() then
            return
        end


        if not receiving_frame then
            return
        end


        local frame_id,
              chunk_number,
              offset


        frame_id,
        chunk_number,
        offset =
            string.unpack(
                "<HH",
                bytestring,
                3
            )


        if frame_id ~=
            receiving_frame_id
        then

            return

        end


        if chunk_number < 1
            or
            chunk_number >
            receiving_total_chunks
        then

            return

        end


        if not received_chunks[
            chunk_number
        ]
        then

            received_chunks[
                chunk_number
            ] =
                string.sub(
                    bytestring,
                    offset
                )


            received_chunk_count =
                received_chunk_count + 1

        end


        return

    end


    -- ========================================================
    -- END
    -- ========================================================

    if packet_type == PACKET_END then

        if network_is_server() then
            return
        end


        if not receiving_frame then
            return
        end


        local frame_id =
            string.unpack(
                "<H",
                bytestring,
                3
            )


        if frame_id ~=
            receiving_frame_id
        then

            return

        end


        if received_chunk_count ~=
            receiving_total_chunks
        then

            print(
                "[RGB] Network frame incomplete"
            )


            receiving_frame =
                false


            return

        end


        local complete_data = {}


        for i = 1,
            receiving_total_chunks
        do

            if not received_chunks[i] then

                receiving_frame =
                    false

                return

            end


            complete_data[i] =
                received_chunks[i]

        end


        local frame_data =
            table.concat(
                complete_data
            )


        if #frame_data ~=
            RGB_BYTES
        then

            print(
                "[RGB] Invalid network framebuffer"
            )


            receiving_frame =
                false


            return

        end


        rgb_string_to_framebuffer(
            frame_data
        )


        receiving_frame =
            false


        received_chunks =
            {}

        received_chunk_count =
            0


        return

    end

end


-- ============================================================
-- GEOMETRY
-- ============================================================

local function get_geometry()

    local screen_width =
        djui_hud_get_screen_width()


    local screen_height =
        djui_hud_get_screen_height()


    local draw_width
    local draw_height


    -- ========================================================
    -- Fit 4:3 into the available screen.
    -- ========================================================

    if
        screen_width / screen_height
        >
        FRAME_ASPECT
    then

        draw_height =
            screen_height

        draw_width =
            draw_height *
            FRAME_ASPECT

    else

        draw_width =
            screen_width

        draw_height =
            draw_width /
            FRAME_ASPECT

    end


    local offset_x =
        (screen_width -
        draw_width) *
        0.5


    local offset_y =
        (screen_height -
        draw_height) *
        0.5


    return
        draw_width,
        draw_height,
        offset_x,
        offset_y

end


-- ============================================================
-- DRAW FRAME
-- ============================================================

local function draw_frame()

    local draw_width,
          draw_height,
          offset_x,
          offset_y =
        get_geometry()


    for y = 1, HEIGHT do

        local row =
            pixels[y]


        if row then

            local y0 =
                offset_y +
                ((y - 1) / HEIGHT) *
                draw_height


            local y1 =
                offset_y +
                (y / HEIGHT) *
                draw_height


            local x = 1


            while x <= WIDTH do

                local pixel =
                    row[x]


                if not pixel then

                    x = x + 1

                else

                    local r =
                        pixel.r

                    local g =
                        pixel.g

                    local b =
                        pixel.b


                    local start_x =
                        x


                    local run =
                        1


                    -- =================================================
                    -- Merge adjacent pixels with the same RGB.
                    -- =================================================

                    while
                        x + run <= WIDTH
                    do

                        local next =
                            row[x + run]


                        if not next then
                            break
                        end


                        if
                            next.r ~= r
                            or
                            next.g ~= g
                            or
                            next.b ~= b
                        then

                            break

                        end


                        run =
                            run + 1

                    end


                    local x0 =
                        offset_x +
                        ((start_x - 1) / WIDTH) *
                        draw_width


                    local x1 =
                        offset_x +
                        ((start_x - 1 + run) / WIDTH) *
                        draw_width


                    djui_hud_set_color(
                        r,
                        g,
                        b,
                        255
                    )


                    djui_hud_render_rect(
                        x0,
                        y0,
                        x1 - x0,
                        y1 - y0
                    )


                    x =
                        start_x + run

                end

            end

        end

    end

end


-- ============================================================
-- UPDATE
-- ============================================================

hook_event(
    HOOK_UPDATE,
    function()

        -- ====================================================
        -- HOST reads ModFS.
        -- ====================================================

        if network_is_server() then

            load_rgb()

        end


        -- ====================================================
        -- One network chunk per update.
        -- ====================================================

        if
            network_is_server()
            and
            sending_frame
        then

            if sending_chunk == 1 then

                send_frame_start()

            end


            send_frame_chunk()


            if sending_chunk >
                TOTAL_CHUNKS
            then

                send_frame_end()


                sending_frame =
                    false

                sending_data =
                    nil

            end

        end

    end
)


-- ============================================================
-- NETWORK HOOK
-- ============================================================

hook_event(
    HOOK_ON_PACKET_BYTESTRING_RECEIVE,
    on_packet_bytestring_receive
)


-- ============================================================
-- HUD
-- ============================================================

hook_event(
    HOOK_ON_HUD_RENDER,
    function()

        djui_hud_set_resolution(
            RESOLUTION_DJUI
        )


        -- ====================================================
        -- No valid frame yet = black.
        -- ====================================================

        if not framebuffer_loaded then

            djui_hud_set_color(
                0,
                0,
                0,
                255
            )


            djui_hud_render_rect(
                0,
                0,
                djui_hud_get_screen_width(),
                djui_hud_get_screen_height()
            )


            return

        end


        -- ====================================================
        -- Always draw the last valid frame.
        -- ====================================================

        draw_frame()

    end
)


-- ============================================================
-- INITIALIZATION
-- ============================================================

create_black_frame()

framebuffer_loaded =
    false

last_rgb =
    ""


-- ============================================================
-- INITIAL HOST LOAD
-- ============================================================

if network_is_server() then

    load_rgb()

end


print(
    "[RGB] 320x224 persistent framebuffer initialized"
)