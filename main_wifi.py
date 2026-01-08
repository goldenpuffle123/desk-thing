import asyncio
import math
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
from winrt.windows.storage.streams import DataReader, IRandomAccessStreamReference
from packet_encoder import encode_art, encode_meta, encode_timeline, encode_playback, ArtFormat

# CONFIGURATION
SERIAL_PORT = 'COM3' # Fix hardcoding in the future
BAUD_RATE = 921600

serial_tx_queue = queue.Queue() # Global queue

def serial_manager():
    """Robust serial thread for transmitting and receiving data."""
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
            print(f"Connected to {SERIAL_PORT}")
            with serial_tx_queue.mutex: 
                serial_tx_queue.queue.clear()

            while True:
                # 1. TRANSMIT
                while not serial_tx_queue.empty():
                    msg = serial_tx_queue.get()
                    ser.write(msg)
                    
                    # Throttle: Small pause for header, tiny pause for chunks
                    if len(msg) < 50: 
                        time.sleep(0.05)
                    else: 
                        time.sleep(0.001)

                # 2. RECEIVE
                if ser.in_waiting:
                    try:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if line: 
                            print(f"[ESP32] {line}")
                    except: 
                        pass
                
                time.sleep(0.001)

        except Exception as e:
            print(f"Serial Error: {e}")
            time.sleep(2)
        finally:
            try:
                if 'ser' in locals() and ser.is_open: ser.close()
            except: pass

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
        self.time_anchor = 0
        self.timeline_anchor = None

        self.current_track_id = None
        self.last_album_title = None
        self.album_art_sent = False
        self.artwork_in_flight = False

        self.last_playback_status = None
        self.is_playing = False


    async def setup(self, session_manager: SessionManager):
        self.session_manager = session_manager
        while(self.current_session is None):
            print("Finding media session...")
            self.current_session = self.session_manager.get_current_session()
            await asyncio.sleep(2)
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

    def _refresh_timeline_anchor(self):
        """Snapshots the current Windows timeline state to our local anchor."""
        try:
            if not self.current_session: return

            # Get fresh properties from Windows
            props = self.current_session.get_timeline_properties()
            
            if self.timeline_changed(props):
                # Update our local anchors
                self.timeline_anchor = props
                self.time_anchor = time.monotonic() # Reset the clock!
                
                serial_tx_queue.put(
                    encode_timeline(
                        int(self.timeline_anchor.position.total_seconds()), 
                        int(self.timeline_anchor.end_time.total_seconds())
                    )
                )
        except Exception as e:
            print(f"Refresh error: {e}")

    async def _timeline_worker(self):
        """Background task to periodically update timeline position."""

        print("Timeline worker started.")
        while True:
            try:
                if self.current_session and self.timeline_anchor and self.is_playing:

                    if self.is_playing:
                        elapsed = time.monotonic() - self.time_anchor
                        current_pos = self.timeline_anchor.position.total_seconds() + elapsed
                        total_dur = self.timeline_anchor.end_time.total_seconds()
                        # Clamp
                        if current_pos > total_dur:
                            current_pos = total_dur
                        if current_pos < 0:
                            current_pos = 0
                        # Send time to serial
                        serial_tx_queue.put(
                            encode_timeline(
                                int(current_pos),
                                int(total_dur)
                            )
                        )
                        # print(f"Timeline: Position={current_pos}, Duration={total_dur}")

                await asyncio.sleep(1) # Poll every 1 second

            except asyncio.CancelledError:
                print("Timeline worker cancelled.")
                break
            except Exception as e:
                print(f"Error in timeline worker: {e}")
                await asyncio.sleep(1)  # Wait before retrying on error

    def handle_timeline_changed(self):
        """Handles timeline property changes from Windows. Used for instant updates (seeking/skip/etc.)."""
        self._refresh_timeline_anchor()

    def metadata_ready(self, info: MediaProperties):
        """Check if metadata is ready (title or artist present)."""
        return bool(info.title or info.artist)
    
    def playback_status_changed(self, status):
        if status != self.last_playback_status:
            return True
        return False
    
    def timeline_changed(self, timeline):
        return (not self.timeline_anchor or timeline.position != self.timeline_anchor.position)


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
                self.timeline_anchor = None
                
            self.current_session = self.session_manager.get_current_session() # Get new session
            self.current_track_id = None # Reset track ID on session change
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
                self.handle_playback_info_changed() # Fire once to sync status
                self.handle_timeline_changed() # Fire once to sync timeline
            else:
                print("\nNo active media session.")
        except Exception as e:
            print(f"Error handling session change: {e}")

    async def handle_media_properties_changed(self):
        try:
            if not self.current_session:
                print("No current session.")
                return
            info = await self.current_session.try_get_media_properties_async()
            if not self.metadata_ready(info):
                return
            
            track_id = make_track_id(info)
            album_id = track_id[2]

            # Any metadata change
            if track_id != self.current_track_id:
                self.current_track_id = track_id
                print(f"\nNow Playing: {info.title} - {info.artist}")
                serial_tx_queue.put(
                    encode_meta(info.title, info.artist, info.album_title)
                )
                self._refresh_timeline_anchor()
            
            # Album change
            album_changed = (not album_id or album_id != self.last_album_title)
            if album_changed:
                self.album_art_sent = False
                self.last_album_title = album_id
            
            # Send album art only once, if available
            if info.thumbnail and not self.album_art_sent and not self.artwork_in_flight:
                self.artwork_in_flight = True # Processing flag (get_artwork and encode_art take some time)
                try:
                    image_data = await get_artwork(info.thumbnail)
                    if image_data:
                        print(f"Image data received.")
                        try:
                            art_packets = await self.loop.run_in_executor(
                                None, 
                                functools.partial(encode_art, image_data, ArtFormat.RGB565)
                            )
                            print(f"Sending art...")
                            for packet in art_packets:
                                serial_tx_queue.put(packet)
                            print("Art sent to queue.")
                            self.album_art_sent = True # Mark as sent for current song/album
                        except Exception as art_err:
                            print(f"Error encoding art: {art_err}")
                    else:
                        print(f"Failed to get image data from thumbnail")
                finally:
                    self.artwork_in_flight = False # Clear processing flag
        except Exception as e:
            print(f"Error handling media properties change: {e}")

    def handle_playback_info_changed(self):
        try:
            if not self.current_session:
                return
            status = self.current_session.get_playback_info().playback_status
            if self.playback_status_changed(status):
                self.last_playback_status = status
                self.is_playing = (status.name == 'PLAYING')
                print(f"Playback status: {status.name}")
                serial_tx_queue.put(encode_playback(status.value)) # Send update (other device decides what to do)
                
                # Reset the clock if playback just started.
                if self.is_playing:
                    self._refresh_timeline_anchor()
                    
        except Exception as e:
            print(f"Error handling playback info change: {e}")

    



def make_track_id(info: MediaProperties):
    """Makes unique track identifier."""
    return (info.title or "", info.artist or "", info.album_title or "")

async def get_artwork(thumbnail_ref: IRandomAccessStreamReference):
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
    threading.Thread(target=serial_manager, daemon=True).start()

    # Start Media Session Manager
    asyncio_loop = asyncio.get_running_loop()
    media_controller = MediaController(asyncio_loop)
    session_manager = await SessionManager.request_async()
    await media_controller.setup(session_manager)

    # Run once immediately
    await media_controller.handle_media_properties_changed()
    
    print("Listening... (Ctrl+C to stop)")
    while True: 
        await asyncio.sleep(1)
        

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass