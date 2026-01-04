from PIL import Image
import io
from enum import IntEnum

SOF = 0x7E
META = 0x01
PLAYBACK_STATE = 0x02
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
    meta = bytearray()
    meta.append(len(title))
    meta.extend(title.encode('utf-8'))
    meta.append(len(artist))
    meta.extend(artist.encode('utf-8'))
    meta.append(len(album))
    meta.extend(album.encode('utf-8'))
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
    JPEG = 0x01
    PNG = 0x02
    RGB565 = 0x03

def encode_art(image_data: bytes, format: int, chunk_size: int = 512, size: tuple = (240,240)) -> list[bytes]:
    packets: list[bytes] = []
    total_size = len(image_data)

    image = Image.open(io.BytesIO(image_data))
    image = image.resize(size) #width, height

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
        chunk = image_data[offset:offset+chunk_size]
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
