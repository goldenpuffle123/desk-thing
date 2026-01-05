import asyncio
import threading
import time
import queue
import serial
import functools
from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSession as Session
from winrt.windows.storage.streams import DataReader
from packet_encoder import encode_art, encode_meta, ArtFormat

# --- CONFIGURATION ---
SERIAL_PORT = 'COM3'  
BAUD_RATE = 921600    
# ---------------------

serial_tx_queue = queue.Queue()
last_track_id = None

# def serial_manager():
#     """Robust Serial Thread"""
#     while True:
#         try:
#             ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
#             print(f"Connected to {SERIAL_PORT}")
#             with serial_tx_queue.mutex: 
#                 serial_tx_queue.queue.clear()

#             while True:
#                 # 1. TRANSMIT
#                 while not serial_tx_queue.empty():
#                     msg = serial_tx_queue.get()
#                     ser.write(msg)
                    
#                     # Throttle: Small pause for header, tiny pause for chunks
#                     if len(msg) < 50: 
#                         time.sleep(0.05) 
#                     else: 
#                         time.sleep(0.002)

#                 # 2. RECEIVE
#                 if ser.in_waiting:
#                     try:
#                         line = ser.readline().decode('utf-8', errors='ignore').strip()
#                         if line: 
#                             print(f"[ESP32] {line}")
#                     except: 
#                         pass
                
#                 time.sleep(0.001)

#         except Exception as e:
#             print(f"Serial Error: {e}")
#             time.sleep(2)
#         finally:
#             try:
#                 if 'ser' in locals() and ser.is_open: ser.close()
#             except: pass

async def get_artwork(thumbnail_ref):
    if not thumbnail_ref: return None
    try:
        stream = await thumbnail_ref.open_read_async()
        reader = DataReader(stream)
        await reader.load_async(stream.size)
        image_data = bytearray(stream.size)
        reader.read_bytes(image_data)
        return image_data
    except:
        return None

async def handle_media_properties_changed(current_session: Session):
    global last_track_id
    try:
        # PHASE 1: FAST TEXT
        info = await current_session.try_get_media_properties_async()
        track_id = f"{info.title}-{info.artist}"
        
        # Always print, but only send if changed
        if track_id != last_track_id:
            last_track_id = track_id
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
            print("\nNow Playing: ")
            print("Current session is "+current_session.source_app_user_model_id)
            for key, value in info_dict.items():
                print(f"{key}: {value}")
            # serial_tx_queue.put(encode_meta(info.title, info.artist, info.album_title))

            # PHASE 2: SLOW ART
            # Only fetch art if the track actually changed
            if info.thumbnail:
                image_data = await get_artwork(info.thumbnail)
                if image_data:
                    # loop = asyncio.get_running_loop()
                    # art_packets = await loop.run_in_executor(
                    #     None, 
                    #     functools.partial(encode_art, image_data, ArtFormat.RGB565)
                    # )
                    # print(f"Sending Art ({len(art_packets)} chunks)...")
                    # for packet in art_packets:
                    #     serial_tx_queue.put(packet)
                    print("Image received.")
                        
    except Exception as e:
        print(f"Error: {e}")

async def handle_current_session_changed(sessions: SessionManager):
    global last_track_id
    try:
        current_session = sessions.get_current_session()
        if current_session:
            print(f"\nCurrent session changed to: {current_session.source_app_user_model_id}")
            last_track_id = None  # Reset last track to force update
            await handle_media_properties_changed(current_session)
        else:
            print("\nNo active media session.")
    except Exception as e:
        print(f"Error handling session change: {e}")

async def main():
    # Start Serial
    # threading.Thread(target=serial_manager, daemon=True).start()

    # Start Media Session Manager
    sessions = await SessionManager.request_async()
    current_session = sessions.get_current_session()

    loop = asyncio.get_running_loop() # Capture the event loop here

    def handler_current_session_changed(sender, args):
        asyncio.run_coroutine_threadsafe(
            handle_current_session_changed(sessions), 
            loop
        )

    sessions.add_current_session_changed(handler_current_session_changed)
    
    while(current_session is None):
        print("No active media session found.")
        current_session = sessions.get_current_session()
        await asyncio.sleep(1)

    print(f"Attached to: {current_session.source_app_user_model_id}")
    
    # 1. Run once immediately
    await handle_media_properties_changed(current_session)
    
    # 2. Setup Background Listener
    # CRITICAL FIX: Capture the loop HERE, before defining the lambda
    
    
    def handler_media_properties_changed(sender, args):
        # Use the captured 'loop' variable to safely schedule the coroutine
        asyncio.run_coroutine_threadsafe(
            handle_media_properties_changed(current_session), 
            loop
        )

    current_session.add_media_properties_changed(handler_media_properties_changed)
    
    print("Listening... (Ctrl+C to stop)")
    while True: 
        await asyncio.sleep(1)
        

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass