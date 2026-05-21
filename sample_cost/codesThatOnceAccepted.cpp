#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>

const char* ssid = "Wokwi-GUEST";
const char* password = "";

const char* serverURL = "http://banker-goliath-humped.ngrok-free.dev/attendance";

// Changed pins for Wokwi
#define SS_PIN   21  // Changed from 5
#define RST_PIN  22

MFRC522 rfid(SS_PIN, RST_PIN);

unsigned long lastWiFiCheck = 0;
unsigned long wifiCheckInterval = 5000;
String lastUID = "";
unsigned long lastScanTime = 0;
const unsigned long debounceTime = 5000;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  
  Serial.println("\nConnecting to WiFi...");
  WiFi.begin(ssid, password);
  
  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 15000) {
    Serial.print(".");
    delay(500);
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi Connection Failed");
  }
}

String getUID() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

bool sendAttendance(String uid) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected");
    return false;
  }
  
  HTTPClient http;
  http.begin(serverURL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("bypass-tunnel-reminder", "true");
  http.setTimeout(5000);
  
  String jsonData = "{\"uid\":\"" + uid + "\"}";
  Serial.println("Sending UID: " + uid);
  Serial.println("JSON: " + jsonData);
  
  int responseCode = http.POST(jsonData);
  
  if (responseCode > 0) {
    String response = http.getString();
    Serial.print("HTTP Response Code: ");
    Serial.println(responseCode);
    Serial.print("Server Response: ");
    Serial.println(response);
    http.end();
    return true;
  } else {
    Serial.print("HTTP Error: ");
    Serial.println(http.errorToString(responseCode));
    http.end();
    return false;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n\nStarting RFID Attendance System...");
  
  SPI.begin();
  Serial.println("SPI initialized");
  
  rfid.PCD_Init();
  Serial.println("RFID initialized");
  
  // Test if RFID is working
  rfid.PCD_DumpVersionToSerial();
  
  connectWiFi();
  Serial.println("Setup complete, entering main loop...");
}

void loop() {
  // WiFi reconnection check
  if (millis() - lastWiFiCheck > wifiCheckInterval) {
    lastWiFiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi lost. Reconnecting...");
      connectWiFi();
    }
  }
  
  // Check for new card
  if (!rfid.PICC_IsNewCardPresent()) {
    delay(100);  // Small delay to prevent overwhelming Serial
    return;
  }
  
  Serial.println("✓ New card detected!");
  
  if (!rfid.PICC_ReadCardSerial()) {
    Serial.println("✗ Failed to read card serial");
    return;
  }
  
  Serial.println("✓ Card read successful!");
  
  String currentUID = getUID();
  Serial.print("📇 Card UID: ");
  Serial.println(currentUID);
  
  // Debounce check
  if (currentUID == lastUID && millis() - lastScanTime < debounceTime) {
    Serial.println("⏱️ Duplicate scan ignored (debounce)");
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return;
  }
  
  lastUID = currentUID;
  lastScanTime = millis();
  
  Serial.println("📤 Sending to server...");
  bool success = sendAttendance(currentUID);
  
  if (success) {
    Serial.println("✅ Attendance Sent Successfully!");
  } else {
    Serial.println("❌ Attendance Failed!");
  }
  
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}