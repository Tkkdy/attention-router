// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once
#include "Arduino.h"
extern int probeCalls, probeStatus;
struct HTTPClient {
 void setConnectTimeout(int) {} void setTimeout(int) {}
 void collectHeaders(const char**, int) {}
 bool begin(const String&) { return true; }
 int GET() { ++probeCalls; return probeStatus; }
 String header(const char*) { return String(); }
 void end() {} String errorToString(int) { return String(); }
};
