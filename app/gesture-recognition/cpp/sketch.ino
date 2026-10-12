#include <Arduino_RouterBridge.h>
#include <Modulino.h>

ModulinoMovement movement;
float x_accel, y_accel, z_accel;
unsigned long previousMillis = 0;
const long interval = 16; // Inteval at which to read (16ms), corresponding to sampling rate of 62.5Hz
int has_movement = 0;

void setup() {
    Bridge.begin();
    Modulino.begin(Wire1);
    while (!movement.begin()) {
        delay(1000);
    }
}

void loop() {
    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= interval) {
        previousMillis = currentMillis;
        has_movement = movement.update();

        if (has_movement == 1) {
            x_accel = movement.getX();
            y_accel = movement.getY();
            z_accel = movement.getZ();

            Bridge.notify("record_sensor_movement", x_accel, y_accel, z_accel);
        }
    }
}