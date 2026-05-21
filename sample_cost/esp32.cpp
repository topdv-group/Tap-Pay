#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid = "Wokwi-GUEST";
const char* password = "";
const char* serverName = "http://banker-goliath-humped.ngrok-free.dev/attendance";

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverName);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("bypass-tunnel-reminder", "true");
    
    String jsonData = "{\"uid\":\"TEST123\"}";
    int httpResponseCode = http.POST(jsonData);
    
    Serial.print("HTTP Response: ");
    Serial.println(httpResponseCode);
    
    if (httpResponseCode > 0) {
      Serial.println("Success: " + http.getString());
    } else {
      Serial.println("Error: " + http.errorToString(httpResponseCode));
    }
    
    http.end();
  }
  delay(10000);
}