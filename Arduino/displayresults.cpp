#include <SPI.h>
#include "epd2in13_V4.h"
#include "epdpaint.h"
#include "imagedata.h"
#include <RPC.h>
#include <SerialRPC.h>
#include <queue>

#define MAX_RESULT 5
#define COLORED     0
#define UNCOLORED   1

// LEDs
#define LED_GREEN 9
#define LED_RED   14

// Boutons
#define BUTTON_EXECUTE 25
#define BUTTON_MODE    30
unsigned char image[1050];
Paint paint(image, 0, 0);
Epd epd;

std::queue<String> results;
void displayAndLight(String message) {
    Serial.println("Display : " + message);

    //test success or error management
    if (message.startsWith("Error")) {
        digitalWrite(LED_RED, HIGH);
        digitalWrite(LED_GREEN, LOW);
    }
    else if (message.startsWith("Succes")) {
        digitalWrite(LED_GREEN, HIGH);
        digitalWrite(LED_RED, LOW);
    }

    //Add message to queue
    results.push(message);

    // If more than MAX_MESSAGES, remove the oldest
    if (results.size() > MAX_MESSAGES) {
        results.pop();
    }

    // Réinitialiser l'écran
    paint = Paint(image, epd.bufwidth * 8, epd.bufheight);
    paint.Clear(UNCOLORED);

    // Display messages on screen, 1 message per line
    int y = 5;
    std::queue<String> temp = results;  //copy to iterate without emptying the queue
    while (!temp.empty()) {
        String msg = temp.front();
        temp.pop();
        paint.DrawStringAt(5, y, msg.c_str(), &Font8, COLORED);
        y += 5;  
    }

    epd.Display1(image);

  
    if (message.startsWith("end of test:")) {
        delay(3000);
        paint.Clear(UNCOLORED);
        epd.Display1(image);
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, LOW);
    }
}


void rpc_displaymessage(JsonVariant arg) {
  String msg = arg.as<String>();
  Serial.println("Message received via RPC : " + msg);
  displayAndLight(msg);
}

JsonVariant rpc_get_buttons() {
    JsonDocument doc;
    doc["execute"] = digitalRead(BUTTON_EXECUTE) == LOW ? "pressed" : "released";
    doc["mode"] = digitalRead(BUTTON_MODE) == LOW ? "traction" : "direction";
    return doc.as<JsonVariant>();
}


void setup() {
  Serial.begin(115200);
  while (!Serial);  

  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);

  if (epd.Init(FULL) != 0) {
    Serial.println("e-Paper initialization error");
    return;
  }

   displayMessage("Ready...");
   RPC.begin()
   RPC.bind("displaymessage", rpc_displaymessage);
   RPC.bind("get_buttons", rpc_get_buttons);

}

void loop() {
    RPC.update()


}
