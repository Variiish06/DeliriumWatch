#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <TFT_eSPI.h>

// ─── CONFIGURATION ─────────────────────────────────────────────
const char* WIFI_SSID = "Network";
const char* WIFI_PASS = "Password";

const char* MQTT_BROKER_MDNS = "Rogue-Macbook-Pro"; 
const char* PAGER_ID         = "doc3";
const char* PAGER_ZONE       = "Bay C";
const int   MQTT_PORT        = 1883;

// ─── HARDWARE & STATE ──────────────────────────────────────────
TFT_eSPI tft = TFT_eSPI();
WiFiClient espClient;
PubSubClient mqtt(espClient);

const int BL_PIN = 38;
const int ENC_A = 2;
const int ENC_B = 1;
const int ENC_BTN_1 = 0;
const int ENC_BTN_2 = 21;

unsigned long lastHeartbeat = 0;
unsigned long alertReceivedAt = 0;
unsigned long lastInteractionAt = 0;
const unsigned long CLEAR_AFTER_MS = 300000; 
const unsigned long DIM_AFTER_MS   = 30000;  

bool isAlertActive = false;
bool isCriticalAlert = false;
int currentBrightness = 255;
unsigned long lastFlashTime = 0;
bool flashState = false;

// ─── UI MODES & ENCODER ────────────────────────────────────────
// 0 = Standby/Alert, 1 = Ward Heatmap, 2 = Alert History
int uiMode = 0; 
volatile int encoderCount = 0;
int lastEncoderCount = 0;
volatile int lastEncoded = 0;
unsigned long lastButtonPress = 0;

void IRAM_ATTR encoderISR() {
  int MSB = digitalRead(ENC_A);
  int LSB = digitalRead(ENC_B);
  int encoded = (MSB << 1) | LSB;
  int sum = (lastEncoded << 2) | encoded;
  if (sum == 0b1101 || sum == 0b0100 || sum == 0b0010 || sum == 0b1011) encoderCount++;
  if (sum == 0b1110 || sum == 0b0111 || sum == 0b0001 || sum == 0b1000) encoderCount--;
  lastEncoded = encoded;
}

// ─── DATA CACHES ───────────────────────────────────────────────
String currentPatient = "";
String currentBed = "";
String currentRiskStr = "";
String currentAction = "";
float currentRiskRaw = 0.0f;

struct BedInfo {
  String bed;
  String label;
  String risk;
};
BedInfo wardBeds[16]; // Max 16 for 4x4 grid
int numBeds = 0;

struct AlertInfo {
  String patient;
  String bed;
  String risk;
  String timestamp;
};
AlertInfo historyList[10];
int historyCount = 0;

// Custom Colors
#define COLOR_BG      0x0825 // Dark Navy
#define COLOR_ACCENT  0x051D // Cyber Blue
#define COLOR_TEXT    0xFFFF // White
#define COLOR_MUTED   0x8410 // Grey
#define COLOR_MED     0xFD20 // Orange
#define COLOR_CRIT    0xF800 // Red
#define COLOR_LOW     0x07E0 // Green

// ─── MQTT TOPICS ───────────────────────────────────────────────
String topicAlerts;
String topicZone;
String topicHeatmap;
String topicBroadcast;
String topicClear;
String topicStatus;
String topicRssi;

// ─── HELPER FUNCTIONS ──────────────────────────────────────────
void drawStandbyScreen();
void drawHeatmapScreen();
void drawHistoryScreen();
void renderAlertUI(bool isRedBg);
void drawAlertScreen(const char* patient, const char* bed, const char* label, const char* risk, const char* action, float risk_raw, const char* timestamp);

void setBacklight(int level) {
  if (currentBrightness == level) return;
  currentBrightness = level;
  analogWrite(BL_PIN, level);
}

void initBacklight() {
  pinMode(15, OUTPUT); digitalWrite(15, HIGH);
  pinMode(46, OUTPUT); digitalWrite(46, HIGH);
  delay(100);
  pinMode(BL_PIN, OUTPUT);
  setBacklight(255);
}

void handleButtonPress() {
  unsigned long now = millis();
  if (now - lastButtonPress < 300) return; // Debounce
  lastButtonPress = now;
  lastInteractionAt = now;
  setBacklight(255);
  
  uiMode = (uiMode + 1) % 3;
  if (isAlertActive && uiMode == 0) return; // Wait to redraw loop
  
  if (uiMode == 0) drawStandbyScreen();
  else if (uiMode == 1) drawHeatmapScreen();
  else if (uiMode == 2) drawHistoryScreen();
}

// ─── UI RENDERING ──────────────────────────────────────────────
void drawStandbyScreen() {
  if (uiMode != 0) return;
  tft.fillScreen(COLOR_BG);
  
  tft.fillRect(0, 0, tft.width(), 35, COLOR_ACCENT);
  tft.setTextColor(COLOR_TEXT);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("DELIRIUM WATCH", tft.width() / 2, 17, 2);
  
  tft.setTextColor(COLOR_TEXT);
  tft.drawString("STANDBY", tft.width() / 2, tft.height() / 2 - 10, 4);
  tft.setTextColor(COLOR_MUTED);
  tft.drawString(String("ZONE: ") + PAGER_ZONE, tft.width() / 2, tft.height() / 2 + 20, 2);
  
  tft.setTextDatum(BC_DATUM);
  uint16_t wifiColor = WiFi.status() == WL_CONNECTED ? TFT_GREEN : COLOR_CRIT;
  uint16_t mqttColor = mqtt.connected() ? TFT_GREEN : COLOR_CRIT;
  
  tft.setTextColor(wifiColor);
  tft.drawString("WiFi", tft.width() / 3, tft.height() - 10, 2);
  tft.setTextColor(mqttColor);
  tft.drawString("MQTT", 2 * (tft.width() / 3), tft.height() - 10, 2);
}

void drawHeatmapScreen() {
  if (uiMode != 1) return;
  tft.fillScreen(COLOR_BG);
  tft.fillRect(0, 0, tft.width(), 25, COLOR_ACCENT);
  tft.setTextColor(COLOR_TEXT);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("WARD HEATMAP", tft.width() / 2, 12, 2);
  
  if (numBeds == 0) {
    tft.setTextColor(COLOR_MUTED);
    tft.drawString("No Patients in Ward", tft.width()/2, tft.height()/2, 2);
    return;
  }
  
  // 4x4 Grid Layout
  int w = tft.width();
  int h = tft.height() - 25;
  int cellW = w / 4;
  int cellH = h / 4;
  
  for (int i = 0; i < numBeds; i++) {
    int row = i / 4;
    int col = i % 4;
    if (row > 3) break;
    
    int x = col * cellW;
    int y = 25 + (row * cellH);
    
    uint16_t color = COLOR_LOW;
    if (wardBeds[i].label == "HIGH") color = COLOR_CRIT;
    else if (wardBeds[i].label == "MEDIUM") color = COLOR_MED;
    
    tft.fillRect(x+2, y+2, cellW-4, cellH-4, color);
    
    tft.setTextColor(TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.drawString(wardBeds[i].bed, x + cellW/2, y + cellH/2 - 5, 2);
    tft.drawString(wardBeds[i].risk, x + cellW/2, y + cellH/2 + 5, 1);
  }
}

void drawHistoryScreen() {
  if (uiMode != 2) return;
  tft.fillScreen(COLOR_BG);
  tft.fillRect(0, 0, tft.width(), 25, COLOR_ACCENT);
  tft.setTextColor(COLOR_TEXT);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("ALERT HISTORY", tft.width() / 2, 12, 2);
  
  if (historyCount == 0) {
    tft.setTextColor(COLOR_MUTED);
    tft.drawString("No History", tft.width()/2, tft.height()/2, 2);
    return;
  }
  
  // Calculate scrolling offset based on encoder
  int enc = encoderCount / 4; // Detent division
  if (enc < 0) { encoderCount = 0; enc = 0; }
  int maxScroll = max(0, historyCount - 3);
  if (enc > maxScroll) { enc = maxScroll; encoderCount = enc * 4; }
  
  int y = 30;
  for (int i = enc; i < min(enc + 3, historyCount); i++) {
    tft.setTextColor(TFT_YELLOW);
    tft.setTextDatum(TL_DATUM);
    tft.drawString(historyList[i].timestamp + " | " + historyList[i].bed, 5, y, 2);
    
    tft.setTextColor(COLOR_TEXT);
    tft.drawString(historyList[i].patient, 5, y + 15, 2);
    tft.setTextColor(COLOR_CRIT);
    tft.drawString("Risk: " + historyList[i].risk, 200, y + 15, 2);
    
    tft.drawLine(5, y + 35, tft.width() - 5, y + 35, COLOR_MUTED);
    y += 40;
  }
}

void renderAlertUI(bool isRedBg) {
  if (uiMode != 0) return; // Don't flash over heatmap/history
  uint16_t bgColor = isRedBg ? COLOR_CRIT : TFT_BLACK;
  uint16_t fgColor = isRedBg ? TFT_BLACK : COLOR_CRIT;
  uint16_t textColor = isRedBg ? TFT_BLACK : TFT_WHITE;
  uint16_t detailsColor = isRedBg ? TFT_WHITE : TFT_YELLOW;

  tft.fillScreen(bgColor);
  
  tft.fillRect(0, 0, tft.width(), 40, fgColor);
  tft.setTextColor(bgColor);
  tft.setTextDatum(ML_DATUM);
  tft.drawString(isCriticalAlert ? "!! CRITICAL !!" : "! WARNING", 10, 20, 4);
  
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(textColor);
  tft.drawString(currentPatient, 10, 50, 4);
  tft.drawString(String("Bed: ") + currentBed, 10, 80, 2);
  tft.drawString(String("Risk: ") + currentRiskStr, 10, 105, 4);
  
  if (currentRiskRaw > 0.90f) {
    tft.setTextColor(detailsColor);
    tft.drawString("EXTREME RISK (>90%)", 10, 135, 2);
    tft.drawString(currentAction.substring(0, 30), 10, 155, 2);
  }
}

void drawAlertScreen(const char* patient, const char* bed, const char* label, 
                     const char* risk, const char* action, float risk_raw, const char* timestamp) {
  
  currentPatient = patient; currentBed = bed;
  currentRiskStr = risk; currentAction = action; currentRiskRaw = risk_raw;
  isCriticalAlert = (strcmp(label, "HIGH") == 0);
  
  // Add to history
  if (historyCount < 10) {
    for (int i = historyCount; i > 0; i--) historyList[i] = historyList[i-1];
    historyCount++;
  } else {
    for (int i = 9; i > 0; i--) historyList[i] = historyList[i-1];
  }
  historyList[0].patient = patient;
  historyList[0].bed = bed;
  historyList[0].risk = risk;
  historyList[0].timestamp = timestamp;
  
  lastInteractionAt = millis();
  alertReceivedAt = millis();
  isAlertActive = true;
  uiMode = 0; // Force switch to alert screen
  setBacklight(255);
  renderAlertUI(isCriticalAlert);
}

// ─── MQTT CALLBACK ─────────────────────────────────────────────
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String t = String(topic);
  String p = "";
  for (unsigned int i = 0; i < length; i++) p += (char)payload[i];
  
  if (t == topicHeatmap) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, p);
    if (!error) {
      JsonArray arr = doc.as<JsonArray>();
      numBeds = 0;
      for (JsonObject obj : arr) {
        if (numBeds >= 16) break;
        wardBeds[numBeds].bed = obj["b"] | "";
        wardBeds[numBeds].label = obj["l"] | "LOW";
        wardBeds[numBeds].risk = obj["r"] | "";
        numBeds++;
      }
      if (uiMode == 1) drawHeatmapScreen();
    }
    return;
  }
  
  if (t == topicClear || p == "CLEAR") {
    isAlertActive = false; isCriticalAlert = false;
    setBacklight(255); lastInteractionAt = millis();
    if (uiMode == 0) drawStandbyScreen();
    return;
  }
  
  JsonDocument doc;
  if (deserializeJson(doc, p)) return;
  
  drawAlertScreen(
    doc["patient"] | "UNKNOWN", doc["bed"] | "UNKNOWN", doc["label"] | "MEDIUM",
    doc["risk"] | "", doc["action"] | "", doc["risk_raw"] | 0.0f, doc["timestamp"] | ""
  );
}

// ─── SETUP ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  initBacklight();
  
  pinMode(ENC_A, INPUT_PULLUP);
  pinMode(ENC_B, INPUT_PULLUP);
  pinMode(ENC_BTN_1, INPUT_PULLUP);
  pinMode(ENC_BTN_2, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ENC_A), encoderISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_B), encoderISR, CHANGE);
  
  tft.init();
  tft.setRotation(3);
  uint8_t did3 = tft.readcommand8(0x04, 3);
  if (did3 == 0x93) {
    tft.invertDisplay(0); tft.writecommand(0x36); tft.writedata(0x20 | 0x40 | 0x80 | 0x08);
  } else if (did3 == 0x85) {
    tft.writecommand(0x26); tft.writedata(8); tft.writecommand(0x55); tft.writedata(0xB1);
  }
  
  drawStandbyScreen();
  
  topicAlerts    = String("deliriumwatch/pager/") + PAGER_ID + "/alerts";
  topicZone      = String("deliriumwatch/zone/") + PAGER_ZONE + "/alerts";
  topicHeatmap   = "deliriumwatch/ward/heatmap";
  topicBroadcast = "deliriumwatch/pager/broadcast";
  topicClear     = String("deliriumwatch/pager/") + PAGER_ID + "/clear";
  topicStatus    = String("deliriumwatch/pager/") + PAGER_ID + "/status";
  topicRssi      = String("deliriumwatch/pager/") + PAGER_ID + "/rssi";

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  
  if (MDNS.begin("esp32-pager")) {
    IPAddress brokerIP = MDNS.queryHost(MQTT_BROKER_MDNS);
    if (brokerIP.toString() != "0.0.0.0") mqtt.setServer(brokerIP, MQTT_PORT);
    else mqtt.setServer("10.92.9.50", MQTT_PORT);
  }
  
  mqtt.setCallback(onMqttMessage);
  drawStandbyScreen();
}

// ─── LOOP ──────────────────────────────────────────────────────
void loop() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  if (!mqtt.connected()) {
    if (mqtt.connect(PAGER_ID)) {
      mqtt.subscribe(topicAlerts.c_str());
      mqtt.subscribe(topicZone.c_str());
      mqtt.subscribe(topicHeatmap.c_str());
      mqtt.subscribe(topicBroadcast.c_str());
      mqtt.subscribe(topicClear.c_str());
      if (uiMode == 0) drawStandbyScreen();
    } else { delay(2000); return; }
  }
  mqtt.loop();
  
  unsigned long now = millis();
  
  // Handle Button Press
  if (digitalRead(ENC_BTN_1) == LOW || digitalRead(ENC_BTN_2) == LOW) {
    handleButtonPress();
  }
  
  // Handle Encoder Scroll for History Mode
  if (uiMode == 2 && (encoderCount / 4) != (lastEncoderCount / 4)) {
    lastInteractionAt = now;
    setBacklight(255);
    drawHistoryScreen();
    lastEncoderCount = encoderCount;
  }
  
  // Flashing Alert
  if (isAlertActive && isCriticalAlert && uiMode == 0) {
    if (now - lastFlashTime > 500) {
      lastFlashTime = now;
      flashState = !flashState;
      setBacklight(255);
      renderAlertUI(flashState);
    }
  } else {
    if (now - lastInteractionAt > DIM_AFTER_MS) {
      if (currentBrightness > 10) setBacklight(currentBrightness - 5);
      delay(10);
    } else { setBacklight(255); }
  }
  
  if (isAlertActive && (now - alertReceivedAt > CLEAR_AFTER_MS)) {
    isAlertActive = false; isCriticalAlert = false;
    lastInteractionAt = now;
    if (uiMode == 0) drawStandbyScreen();
  }
  
  if (now - lastHeartbeat > 10000) {
    lastHeartbeat = now;
    String statusPayload = String("{\"id\":\"") + PAGER_ID + "\",\"zone\":\"" + PAGER_ZONE + "\",\"status\":\"online\"}";
    mqtt.publish(topicStatus.c_str(), statusPayload.c_str(), true);
    long rssi = WiFi.RSSI();
    String rssiPayload = String("{\"id\":\"") + PAGER_ID + "\",\"rssi\": " + String(rssi) + "}";
    mqtt.publish(topicRssi.c_str(), rssiPayload.c_str());
  }
}
