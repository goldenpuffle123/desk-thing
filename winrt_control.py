import asyncio
import threading
import time
import datetime
import queue
import serial
import functools
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionMediaProperties as MediaProperties
)
    
from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSession as Session
from winrt.windows.storage.streams import DataReader
from packet_encoder import encode_art, encode_meta, ArtFormat

# --- CONFIGURATION ---
SERIAL_PORT = 'COM3'  
BAUD_RATE = 921600    
# ---------------------

# serial_tx_queue = queue.Queue()

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

class MediaController:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.session_manager: SessionManager = None
        self.current_session: Session = None

        self.session_token = None
        self.media_token = None
        self.playback_token = None
        self.timeline_token = None

        self.timeline_task = None
        self.last_time = None

        self.last_track_id = None
        self.last_playback_status = None


    async def setup(self, session_manager: SessionManager):
        self.session_manager = session_manager
        while(self.current_session is None):
            print("Finding media session...")
            self.current_session = self.session_manager.get_current_session()
            await asyncio.sleep(1)
        print(f"Found session: {self.current_session.source_app_user_model_id}")
        self.session_token = self.session_manager.add_current_session_changed(
            lambda sender, args: asyncio.run_coroutine_threadsafe(
                self.handle_current_session_changed(), 
                self.loop
            )
        )
        self.media_token = self.current_session.add_media_properties_changed(
            lambda sender, args: asyncio.run_coroutine_threadsafe(
                self.handle_media_properties_changed(), 
                self.loop
            )
        )
        self.playback_token = self.current_session.add_playback_info_changed(
            lambda sender, args: self.handle_playback_info_changed()
        )

        self.timeline_token = self.current_session.add_timeline_properties_changed(
            lambda sender, args: self.handle_timeline_changed()
        )
        if not self.timeline_task:
            self.timeline_task = self.loop.create_task(self._timeline_worker())

    async def _timeline_worker(self):
        print("Timeline worker started.")
        while True:
            try:
                if not self.current_session:
                    await asyncio.sleep(1)
                    continue
                try:
                    curr_playback = self.current_session.get_playback_info()
                    if curr_playback.playback_status.name == 'PLAYING':
                        curr_time = time.time()
                        shift = curr_time - (self.last_time or 1)
                        timeline = self.current_session.get_timeline_properties()
                        current_seconds = timeline.position
                        total_seconds = timeline.end_time
                        
                        # SEND TO SERIAL HERE
                        print(f"Timeline: Position={current_seconds}, Duration={total_seconds}")
                except Exception as e:
                    # Session might be invalidated during poll
                    pass

                await asyncio.sleep(1) # Poll every 1 second

            except asyncio.CancelledError:
                print("Timeline worker cancelled.")
                break

    def handle_timeline_changed(self): # Keep this for instant updates, use polling for regular
        try:
            if not self.current_session:
                return
            timeline = self.current_session.get_timeline_properties()
            self.last_time = time.time()
            print(f"Timeline changed: Position={timeline.position}, Duration={timeline.end_time}")
        except Exception as e:
            print(f"Error handling timeline change: {e}")

    def update_time(self): # For arduino
        pass

    def metadata_ready(self, info: MediaProperties):
        return bool(info.title or info.artist)

    def track_changed(self, info):
        curr = make_track_id(info)
        if curr != self.last_track_id:
            self.last_track_id = curr
            return True
        return False
    
    def playback_status_changed(self, status):
        if status != self.last_playback_status:
            self.last_playback_status = status
            return True
        return False

    async def handle_current_session_changed(self):
        try:
            if self.current_session and self.media_token:
                self.current_session.remove_media_properties_changed(self.media_token)
                self.media_token = None
            if self.current_session and self.playback_token:
                self.current_session.remove_playback_info_changed(self.playback_token)
                self.playback_token = None
            if self.current_session and self.timeline_token:
                self.current_session.remove_timeline_properties_changed(self.timeline_token)
                self.timeline_token = None
                
            self.current_session = self.session_manager.get_current_session()
            self.last_track_id = None # Reset track ID on session change
            self.last_playback_status = None # Reset playback status on session change

            if self.current_session:
                print(f"\nCurrent session changed to: {self.current_session.source_app_user_model_id}")
                self.media_token = self.current_session.add_media_properties_changed(
                    lambda sender, args: asyncio.run_coroutine_threadsafe(
                        self.handle_media_properties_changed(), 
                        self.loop
                    )
                )
                self.playback_token = self.current_session.add_playback_info_changed(
                    lambda sender, args: self.handle_playback_info_changed()
                )
                self.timeline_token = self.current_session.add_timeline_properties_changed(
                    lambda sender, args: self.handle_timeline_changed()
                )
                await self.handle_media_properties_changed()
                
            else:
                print("\nNo active media session.")
        except Exception as e:
            print(f"Error handling session change: {e}")

    async def handle_media_properties_changed(self):
        try:
            # PHASE 1: FAST TEXT
            if not self.current_session:
                print("No current session.")
                return
            info = await self.current_session.try_get_media_properties_async()
            if not self.metadata_ready(info):
                print("Metadata not ready.")
                return
            # Always print, but only send if changed
            if self.track_changed(info):
                
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
                print("Current session is "+self.current_session.source_app_user_model_id)
                for key, value in info_dict.items():
                    print(f"{key}: {value}")
                # serial_tx_queue.put(encode_meta(info.title, info.artist, info.album_title))

                # self.handle_playback_info_changed()   #!!!!!!!!!!!!!!!!
                
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

    def handle_playback_info_changed(self):
        try:
            if not self.current_session:
                return
            curr_playback_status = self.current_session.get_playback_info().playback_status
            if self.playback_status_changed(curr_playback_status):
                print(f"Playback status changed: {curr_playback_status.name}")
        except Exception as e:
            print(f"Error handling playback info change: {e}")

    



def make_track_id(info: MediaProperties):
    t = info.title or ""
    a = info.artist or ""
    al = info.album_title or ""
    return (t.strip(), a.strip(), al.strip())

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


async def main():
    # Start Serial
    # threading.Thread(target=serial_manager, daemon=True).start()

    # Start Media Session Manager
    asyncio_loop = asyncio.get_running_loop()
    media_controller = MediaController(asyncio_loop)
    session_manager = await SessionManager.request_async()
    await media_controller.setup(session_manager)

    
    # 1. Run once immediately
    await media_controller.handle_media_properties_changed()
    
    print("Listening... (Ctrl+C to stop)")
    while True: 
        await asyncio.sleep(1)
        

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass