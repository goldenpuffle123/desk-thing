#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <WiFi.h>
#include <wifi_config.h>

// --- HARDWARE CONFIG ---
#define TFT_CS    10
#define TFT_DC    9
#define TFT_RST   6
// #define TFT_BLK   2  // <--- UNCOMMENT IF YOU HAVE A BACKLIGHT PIN
// -----------------------

Adafruit_ST7789 tft(TFT_CS, TFT_DC, TFT_RST);

#define ST77XX_GRAY 0xB5B6

const char* SSID = SECRET_SSID;
const char* PASS = SECRET_PASSWORD;
WiFiServer server(7777);
WiFiClient client;

// --- FUNCTION PROTOTYPES (Fixes "Not Declared" errors) ---
void parseByte(uint8_t b);
void handleMessage(uint8_t type, uint8_t* data, uint16_t len);
void handleMeta(uint8_t* data, uint16_t len);
void handleArtBegin(uint8_t* data, uint16_t len);
void handleArtChunk(uint8_t* data, uint16_t len);
void handleArtEnd();

enum ArtFormat : uint8_t { ART_FMT_JPEG = 0, ART_FMT_PNG = 1, ART_FMT_RGB565 = 2 };

struct ArtState {
  uint8_t* buf = nullptr;
  uint32_t total_size = 0;
  uint32_t received = 0;
  uint16_t width = 0;
  uint16_t height = 0;
  ArtFormat format;
  bool active = false;
};
ArtState art;

uint16_t timeline_width = 0;
bool is_playing = true;

enum ParseState { WAIT_SOF, READ_TYPE, READ_LEN_1, READ_LEN_2, READ_PAYLOAD, READ_CRC };
ParseState state = WAIT_SOF;
uint8_t msgType, crc;
uint16_t msgLen, bytesRead;

// Increased payload buffer for safety (fits 4096 chunks + header)
uint8_t payload[4096]; 

void setup() {
  Serial.begin(115200);
  
  
  
  // 2. Display Init (240x240)
  tft.init(240, 280); 
  tft.setRotation(2);
  
  // 3. Critical: High Speed SPI (80MHz)
  // This makes drawing 4x faster than default
  tft.setSPISpeed(80000000); 
      
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(2);
  
  if (psramFound()) {
    Serial.printf("PSRAM Free: %d\n", heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  } else {
    Serial.println("ERR: No PSRAM");
  }
  Serial.println("HARDWARE SETUP COMPLETE");

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, PASS);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWIFI SETUP COMPLETE");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
  tft.print("IP: ");
  tft.println(WiFi.localIP());

  server.begin();
}

void loop() {
  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("CLIENT CONNECTED!"); 
      tft.println("CLIENT CONNECTED!");
      delay(1000);
      tft.fillScreen(ST77XX_BLACK);
    }
    return;
  }

  while (client.available()) {
    uint8_t byte = client.read();
    // Feed directly into your existing packet parser
    parseByte(byte);
  }
}

void parseByte(uint8_t b) {
  switch (state) {
    case WAIT_SOF:
      if (b == 0x7E) { crc = b; state = READ_TYPE; }
      break;
    case READ_TYPE:
      msgType = b; crc ^= b; state = READ_LEN_1;
      break;
    case READ_LEN_1:
      msgLen = b; crc ^= b; state = READ_LEN_2;
      break;
    case READ_LEN_2:
      msgLen |= (b << 8); crc ^= b; bytesRead = 0;
      
      // Safety: Prevent buffer overflow
      if (msgLen > sizeof(payload)) {
        Serial.printf("ERR: Packet too big (%d)\n", msgLen);
        state = WAIT_SOF; return;
      }
      
      if (msgLen == 0) state = READ_CRC; 
      else state = READ_PAYLOAD;
      break;

    case READ_PAYLOAD:
      if (bytesRead < sizeof(payload)) payload[bytesRead] = b;
      bytesRead++; crc ^= b;
      if (bytesRead >= msgLen) state = READ_CRC;
      break;

    case READ_CRC:
      if (crc == b) handleMessage(msgType, payload, msgLen);
      state = WAIT_SOF;
      break;
  }
}

void handleMessage(uint8_t type, uint8_t* data, uint16_t len) {
  switch (type) {
    case 0x01: handleMeta(data, len); break;
    case 0x02: handlePlayback(data, len); break;
    case 0x03: handleTimeline(data, len); break;
    case 0x10: handleArtBegin(data, len); break;
    case 0x11: handleArtChunk(data, len); break; 
    case 0x12: handleArtEnd(); break;
  }
}

void handleMeta(uint8_t* data, uint16_t len) {
  uint16_t idx = 0;
  if(idx >= len) return; uint8_t tL = data[idx++]; String title = String((char*)&data[idx], tL); idx += tL;
  if(idx >= len) return; uint8_t aL = data[idx++]; String artist = String((char*)&data[idx], aL); idx += aL;
  if(idx >= len) return; uint8_t alL = data[idx++]; String album = String((char*)&data[idx], alL); idx += alL;
  
  Serial.print("META: "); Serial.println(title);
  
  // UI Update
  tft.fillRect(0,205, 240, 75, ST77XX_BLACK);
  tft.setCursor(0, 210);
  tft.println(title + " - " + artist);
  tft.print(album);
}

void handlePlayback(uint8_t* data, uint16_t len) {
  if (len!=1) return;
  uint8_t playback_state = data[0];
  is_playing = (playback_state == 4);
  Serial.print("PLAYBACK: "); Serial.println(playback_state);
  drawTimeline();
}

void handleTimeline(uint8_t* data, uint16_t len) {
  uint16_t idx = 0;
  if (len!=8) return;
  uint32_t pos; memcpy(&pos, data, 4);
  uint32_t dur; memcpy(&dur, data+4, 4);
  if(dur==0) return;

  

  uint32_t width = ((uint64_t)pos * 240) / dur;

  // 5. Clamp width just in case
  if (width > 240) width = 240;

  timeline_width = width;

  drawTimeline();
  
}

void drawTimeline(){
  // 6. Draw the Bar (Red part)
  tft.fillRect(0, 200, timeline_width, 5, is_playing ? ST77XX_RED : ST77XX_GRAY); // Moved to y=220 to not overlap text

  // 7. Clear the Rest (Black part) -> "Erases" the bar when seeking back
  if (timeline_width < 240) {
    tft.fillRect(timeline_width, 200, 240 - timeline_width, 5, ST77XX_BLACK);
  }
}

void handleArtBegin(uint8_t* data, uint16_t len) {
  if (art.buf) { free(art.buf); art.buf = nullptr; }
  if (len != 9) return;

  uint32_t total; memcpy(&total, data, 4);
  uint16_t w; memcpy(&w, data+4, 2);
  uint16_t h; memcpy(&h, data+6, 2);
  uint8_t fmt; memcpy(&fmt, data+8, 1);

  if (total > 1024 * 300) return;

  uint8_t* buf = (uint8_t*)heap_caps_malloc(total, MALLOC_CAP_SPIRAM);
  if (!buf) { Serial.println("ERR: MALLOC"); return; }

  art.buf = buf;
  art.total_size = total;
  art.received = 0;
  art.width = w; art.height = h;
  art.format = (ArtFormat)fmt;
  art.active = true;
}

void handleArtChunk(uint8_t* data, uint16_t len) {
  if (!art.active || !art.buf || len < 5) return;
  uint32_t offset; memcpy(&offset, data, 4);
  uint16_t chunk_len = len - 4;
  
  if (offset + chunk_len <= art.total_size) {
    memcpy(art.buf + offset, data + 4, chunk_len);
  }
}

void handleArtEnd() {
  if (!art.active || !art.buf) return;
  
  if (art.format == ART_FMT_RGB565) {
    tft.drawRGBBitmap((240-art.width)/2, 0, (uint16_t*)art.buf, art.width, art.height);
  }
  
  if (art.buf) { free(art.buf); art.buf = nullptr; }
  art.active = false;
  Serial.println("Done.");
}