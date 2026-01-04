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

last_track = None

async def handle_playback_changed(current_session):
    """Callback handler for media playback changes"""
    global last_track
    
    try:
        print("Media change detected...")
        info_dict, image_data = await get_media_info(current_session)
        if info_dict:
            if info_dict == last_track: # Prevent duplicates, weird behavior
                return
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
        image = Image.open(io.BytesIO(image_data))
        image.show()

async def main():
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