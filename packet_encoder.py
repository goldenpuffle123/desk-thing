from PIL import Image
import io
from enum import IntEnum
import numpy as np

SOF = 0x7E
META = 0x01
PLAYBACK_STATE = 0x02
TIMELINE = 0x03
ART_BEGIN = 0x10
ART_CHUNK = 0x11
ART_END = 0x12

def _crc(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c

def encode(msg_type: int, payload: bytes) -> bytes:
    length = len(payload)
    frame = bytearray()
    frame.append(SOF)
    frame.append(msg_type)
    frame.append(length & 0xFF)        # LEN_L
    frame.append((length >> 8) & 0xFF) # LEN_H
    frame.extend(payload)
    crc_value = _crc(frame)
    frame.append(crc_value)

    return bytes(frame)

def encode_meta(title: str, artist: str, album: str) -> bytes:
    t = title.encode('utf-8')[:255]
    a = artist.encode('utf-8')[:255]
    al = album.encode('utf-8')[:255]

    meta = bytearray()
    meta.append(len(t))
    meta.extend(t)
    meta.append(len(a))
    meta.extend(a)
    meta.append(len(al))
    meta.extend(al)
    return encode(META, bytes(meta))

# Format:
# [title_length][title_bytes][artist_length][artist_bytes][album_length][album_bytes]
    
# Metadatas available:
# 'album_artist': 'LE SSERAFIM'
# 'album_title': 'FEARLESS'
# 'album_track_count': 0
# 'artist': 'LE SSERAFIM'
# 'genres': []
# 'subtitle': ''
# 'title': 'The Great Mermaid'
# 'track_number': 4

class ArtFormat(IntEnum):
    JPEG = 0
    PNG = 1
    RGB565 = 2

def convert_image_to_rgb565(image_data: bytes, size: tuple) -> bytes:
    image = Image.open(io.BytesIO(image_data)).convert("RGB")
    
    # Crop to match target aspect ratio
    target_aspect = size[0] / size[1]
    current_aspect = image.width / image.height
    
    if current_aspect > target_aspect:
        # Image is wider than target, crop width
        new_width = int(image.height * target_aspect)
        left = (image.width - new_width) // 2
        image = image.crop((left, 0, left + new_width, image.height))
    elif current_aspect < target_aspect:
        # Image is taller than target, crop height
        new_height = int(image.width / target_aspect)
        top = (image.height - new_height) // 2
        image = image.crop((0, top, image.width, top + new_height))
    
    # Now resize to exact target size
    image = image.resize(size)
    arr = np.asarray(image, dtype=np.uint8)
    r = (arr[:,:,0] >> 3).astype(np.uint16)
    g = (arr[:,:,1] >> 2).astype(np.uint16)
    b = (arr[:,:,2] >> 3).astype(np.uint16)
    rgb565 = (r << 11) | (g << 5) | b
    return rgb565.tobytes()

def encode_art(image_data: bytes, format: int, chunk_size: int = 3072, size: tuple = (240,200)) -> list[bytes]:
    # FORMAT NOT IMPLEMENTED YET!!!
    image_data_rgb565 = convert_image_to_rgb565(image_data, size)

    packets: list[bytes] = []
    total_size = len(image_data_rgb565)

    

    begin_payload = bytearray()
    begin_payload.extend(total_size.to_bytes(4, 'little'))

    begin_payload.extend(size[0].to_bytes(2, 'little'))
    begin_payload.extend(size[1].to_bytes(2, 'little'))
    begin_payload.append(format)

    packets.append(
        encode(ART_BEGIN, bytes(begin_payload))
    )

    chunk_payload = bytearray()
    offset = 0
    while offset < total_size:
        chunk = image_data_rgb565[offset:offset+chunk_size]
        chunk_payload = bytearray()
        chunk_payload.extend(offset.to_bytes(4, 'little'))
        chunk_payload.extend(chunk)
        packets.append(
            encode(ART_CHUNK, bytes(chunk_payload))
        )
        offset += len(chunk)
    
    packets.append(
        encode(ART_END, b"")
    )
    return packets

def encode_timeline(position_s: int, duration_s: int) -> bytes:
    payload = bytearray()
    pos = min(position_s, 4294967295) # 4 bytes max
    dur = min(duration_s, 4294967295) # 4 bytes max
    payload.extend(pos.to_bytes(4, 'little'))
    payload.extend(dur.to_bytes(4, 'little'))
    return encode(TIMELINE, bytes(payload))

# From winrt:
# Closed 	0
# Opened 	1
# Changing 	2
# Stopped 	3
# Playing 	4
# Paused 	5

def encode_playback(state: int) -> bytes:
    payload = bytearray()
    payload.append(state & 0xFF) # 1 byte
    return encode(PLAYBACK_STATE, bytes(payload))

if __name__ == '__main__':
    pass