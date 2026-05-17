// 4-way traffic junction display driven by PC (Python/SUMO).
// Serial protocol: send one line "P:<phase>"
// phase values:
// -1 -> all red (safety)
//  0 -> A_GREEN  (L1/L3 green, L2/L4 red)
//  1 -> A_YELLOW (L1/L3 yellow, L2/L4 red)
//  2 -> B_GREEN  (L2/L4 green, L1/L3 red)
//  3 -> B_YELLOW (L2/L4 yellow, L1/L3 red)

int G1 = 4,  Y1 = 3,  R1 = 2;
int G2 = 7,  Y2 = 6,  R2 = 5;
int G3 = 10, Y3 = 9,  R3 = 8;
int G4 = 13, Y4 = 12, R4 = 11;

int currentPhase = -1;
unsigned long lastMessageAt = 0;
const unsigned long failSafeMs = 2000;

void setup() {
  Serial.begin(9600);

  int pins[] = {G1,Y1,R1,G2,Y2,R2,G3,Y3,R3,G4,Y4,R4};
  for (int i = 0; i < 12; i++) {
    pinMode(pins[i], OUTPUT);
  }

  applyPhase(currentPhase);
  Serial.println("READY: send P:-1, P:0, P:1, P:2, P:3");
}

void loop() {
  readSerialPhase();

  // If PC communication is lost, force all-red.
  if (millis() - lastMessageAt > failSafeMs && currentPhase != -1) {
    currentPhase = -1;
    applyPhase(currentPhase);
  }
}

void setLight(int R, int Y, int G, int state) {
  // 0 = RED, 1 = GREEN, 2 = YELLOW
  if (state == 0) {
    digitalWrite(R, HIGH);
    digitalWrite(Y, LOW);
    digitalWrite(G, LOW);
  } else if (state == 1) {
    digitalWrite(R, LOW);
    digitalWrite(Y, LOW);
    digitalWrite(G, HIGH);
  } else {
    digitalWrite(R, LOW);
    digitalWrite(Y, HIGH);
    digitalWrite(G, LOW);
  }
}

void applyPhase(int phase) {
  if (phase == 0) {
    // A_GREEN: L1/L3 green, L2/L4 red
    setLight(R1, Y1, G1, 1);
    setLight(R2, Y2, G2, 0);
    setLight(R3, Y3, G3, 1);
    setLight(R4, Y4, G4, 0);
  } else if (phase == 1) {
    // A_YELLOW: L1/L3 yellow, L2/L4 red
    setLight(R1, Y1, G1, 2);
    setLight(R2, Y2, G2, 0);
    setLight(R3, Y3, G3, 2);
    setLight(R4, Y4, G4, 0);
  } else if (phase == 2) {
    // B_GREEN: L2/L4 green, L1/L3 red
    setLight(R1, Y1, G1, 0);
    setLight(R2, Y2, G2, 1);
    setLight(R3, Y3, G3, 0);
    setLight(R4, Y4, G4, 1);
  } else if (phase == 3) {
    // B_YELLOW: L2/L4 yellow, L1/L3 red
    setLight(R1, Y1, G1, 0);
    setLight(R2, Y2, G2, 2);
    setLight(R3, Y3, G3, 0);
    setLight(R4, Y4, G4, 2);
  } else {
    // all-red safety state
    setLight(R1, Y1, G1, 0);
    setLight(R2, Y2, G2, 0);
    setLight(R3, Y3, G3, 0);
    setLight(R4, Y4, G4, 0);
  }
}

void readSerialPhase() {
  if (Serial.available() <= 0) return;

  String line = Serial.readStringUntil('\n');
  line.trim();

  if (!line.startsWith("P:")) return;

  int phase = line.substring(2).toInt();
  if (phase < -1 || phase > 3) return;

  lastMessageAt = millis();
  if (phase != currentPhase) {
    currentPhase = phase;
    applyPhase(currentPhase);
    Serial.print("PHASE=");
    Serial.println(currentPhase);
  }
}
