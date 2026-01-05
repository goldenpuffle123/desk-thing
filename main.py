import asyncio
import threading
import time
from packet_encoder import encode_art, encode_meta, ArtFormat

from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.storage.streams import \
    DataReader, Buffer, InputStreamOptions
import matplotlib.pyplot as plt
from PIL import Image
import io
import queue
import serial

last_track = None
serial_tx_queue = queue.Queue()

def serial_tx(ser: serial.Serial):
    while True:
        try:
            print("Serial connected")
            while True:
                msg = serial_tx_queue.get()
                print("Sending to serial:", msg)
                ser.write((msg + "\n").encode())

        except Exception as e:
            print("Serial tx error:", e)
            time.sleep(2)  # retry

def serial_rx(ser: serial.Serial):
    while True:
        try:
            ret = ser.readline().decode(errors="ignore").strip()
            if ret:
                print("[ESP32] ", ret)
        except Exception as e:
            print("Serial rx error:", e)
            break

def format_media_for_serial(info_dict):
    return f"META|{info_dict['artist']}|{info_dict['title']}"

async def handle_media_properties_changed(current_session):
    """Callback handler for media playback changes"""
    global last_track
    global serial_tx_queue
    try:
        print("\nMedia change detected...")
        info_dict, image_data = await get_media_info(current_session)
        if info_dict:
            if info_dict == last_track: # Prevent duplicates, weird behavior
                return
            serial_tx_queue.put(
                encode_meta(info_dict['title'], info_dict['artist'], info_dict['album_title'])
            )
        if image_data:
            art_packets = encode_art(
                image_data, ArtFormat.RGB565
            )
            for packet in art_packets:
                serial_tx_queue.put(packet)
        display_media_info(info_dict, image_data) # for demo on this computer
        last_track = info_dict
    except Exception as e:
        print(f"Error handling playback change: {e}")

async def setup_handler():
    loop = asyncio.get_running_loop()
    sessions = await SessionManager.request_async()
    current_session = sessions.get_current_session()
    if current_session:
        def handler(sender, args):
            asyncio.run_coroutine_threadsafe(handle_media_properties_changed(current_session), loop)
        playback_event_token = current_session.add_media_properties_changed(handler)
        return playback_event_token, current_session
    return None, None

async def get_media_info(current_session):
    if current_session:
        info = await current_session.try_get_media_properties_async()
        
        info_dict = {
            "album_artist": info.album_artist,
            "album_title": info.album_title,
            "album_track_count": info.album_track_count,
            "artist": info.artist,
            "genres": list(info.genres),
            "subtitle": info.subtitle,
            "title": info.title,
            "track_number": info.track_number
        }
        
        image_data = None
        if info.thumbnail:
            stream = await info.thumbnail.open_read_async()
            reader = DataReader(stream)
            await reader.load_async(stream.size)
            image_data = bytearray(stream.size)
            reader.read_bytes(image_data)
        
        return info_dict, image_data
    return None, None

def display_media_info(info_dict, image_data):
    print("Current Media Info:")
    print(info_dict)
    
    if image_data:
        print("Thumbnail received")
        # image = Image.open(io.BytesIO(image_data))
        # image = image.resize((200, 200))
        # w, h = image.size
        # fmt = image.format
        # image.show()

async def main():
    ser = serial.Serial('COM3', 9600, timeout=0.1)
    time.sleep(2)  # wait for serial to initialize
    threading.Thread(target=serial_tx, args=(ser,), daemon=True).start()
    threading.Thread(target=serial_rx, args=(ser,), daemon=True).start()

    token, session = await setup_handler()
    if token:
        print("Media event listener active. Press Ctrl+C to exit.")
        try:
            while True:
                await asyncio.sleep(5)
        except KeyboardInterrupt:
            session.remove_media_properties_changed(token)
            print("Exiting...")

if __name__ == '__main__':
    asyncio.run(main())