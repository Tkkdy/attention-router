// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstring>
#include <ctime>
#include <iostream>
#include <string>

#include "../firmware/esp32_dashboard/radar_adapter.h"

FakeSerial Serial;
unsigned long fakeNow = 0;
int fakeWeatherStatus = 200;
int fakeRadarStatus = 200;
int fakeWeatherCalls = 0;
int fakeRadarCalls = 0;
std::string fakeRadarRunDate;
std::string fakeRadarDetail = "First error";
std::string fakeRadarPayloadStatus = "FAILED";

int main() {
  const time_t singaporeNow = time(nullptr) + 8 * 60 * 60;
  const tm* calendar = gmtime(&singaporeNow);
  char date[11]{};
  assert(calendar && strftime(date, sizeof(date), "%Y-%m-%d", calendar) == 10);
  fakeRadarRunDate = date;

  RadarAdapter radar;
  radar.begin(fakeNow);
  assert(radar.tick(fakeNow, true, true, true));
  assert(radar.verified());
  assert(radar.sample().status == RadarStatus::Failed);
  assert(std::strcmp(radar.sample().detail, "First error") == 0);

  fakeNow = 5UL * 60UL * 1000UL;
  fakeRadarDetail = "Second error";
  assert(radar.tick(fakeNow, true, true, true));
  assert(std::strcmp(radar.sample().detail, "Second error") == 0);
  assert(fakeRadarCalls == 2);

  std::cout << "Radar detail passed: same-date/status content updates remain observable\n";
}
