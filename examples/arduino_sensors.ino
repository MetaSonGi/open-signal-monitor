// Numeric JSON Lines at 115200 baud. Replace A0 with your own sensor input.
void setup() {
  Serial.begin(115200);
}

void loop() {
  const int adc = analogRead(A0);
  const float voltage = adc * (5.0f / 1023.0f); // Example: 5 V, 10-bit ADC board.
  Serial.print("{\"values\":{\"adc\":");
  Serial.print(adc);
  Serial.print(",\"voltage\":");
  Serial.print(voltage, 4);
  Serial.println("}}");
  delay(500);
}
