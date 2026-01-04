import asyncio
import threading
import time

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

def serial_tx(port="COM3", baud=9600):
    while True:
        try:
            ser = serial.Serial(port, baud, timeout=0.1)
            time.sleep(2)  # ESP32 reset
            print("Serial connected")
            while True:
                msg = serial_tx_queue.get()
                print("Sending to serial:", msg)
                ser.write((msg + "\n").encode())

        except Exception as e:
            print("Serial error:", e)
            time.sleep(2)  # retry

def format_media_for_serial(info_dict):
    return f"META|{info_dict['artist']}|{info_dict['title']}"

async def handle_playback_changed(current_session):
    """Callback handler for media playback changes"""
    global last_track
    global serial_tx_queue
    try:
        print("\nMedia change detected...")
        info_dict, image_data = await get_media_info(current_session)
        if info_dict:
            if info_dict == last_track: # Prevent duplicates, weird behavior
                return
            serial_tx_queue.put(format_media_for_serial(info_dict))
            display_media_info(info_dict, image_data)
            last_track = info_dict
    except Exception as e:
        print(f"Error handling playback change: {e}")

async def setup_handler():
    loop = asyncio.get_running_loop()
    sessions = await SessionManager.request_async()
    current_session = sessions.get_current_session()
    if current_session:
        def handler(sender, args):
            asyncio.run_coroutine_threadsafe(handle_playback_changed(current_session), loop)
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
        # image.show()

async def main():
    threading.Thread(target=serial_tx, daemon=True).start()
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