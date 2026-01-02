# Source - https://stackoverflow.com/a
# Posted by tameTNT, modified by community. See post 'Timeline' for change history
# Retrieved 2026-01-02, License - CC BY-SA 4.0

import asyncio

from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.storage.streams import \
    DataReader, Buffer, InputStreamOptions
import matplotlib.pyplot as plt
from PIL import Image
import io


async def get_media_info():
    sessions = await SessionManager.request_async()

    # This source_app_user_model_id check and if statement is optional
    # Use it if you want to only get a certain player/program's media
    # (e.g. only chrome.exe's media not any other program's).

    # To get the ID, use a breakpoint() to run sessions.get_current_session()
    # while the media you want to get is playing.
    # Then set TARGET_ID to the string this call returns.

    current_session = sessions.get_current_session()
    if current_session:  # there needs to be a media session running
        # if current_session.source_app_user_model_id == TARGET_ID:
            info = await current_session.try_get_media_properties_async()

            # song_attr[0] != '_' ignores system attributes
            # list is ['album_artist', 'album_title', 'album_track_count', 'artist', 'as_', 'genres', 'playback_type', 'subtitle', 'thumbnail', 'title', 'track_number']
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

            stream = await info.thumbnail.open_read_async()
            reader = DataReader(stream)
            await reader.load_async(stream.size)
            image_data = bytearray(stream.size)
            reader.read_bytes(image_data)

            return info_dict, image_data

if __name__ == '__main__':
    current_media_info, current_media_image = asyncio.run(get_media_info())
    print(current_media_info)
    image = Image.open(io.BytesIO(current_media_image))
    plt.imshow(image)
    plt.axis('off')  # Hide axes
    plt.show()