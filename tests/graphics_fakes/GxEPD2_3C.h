// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once
#include <Arduino.h>
#include <sstream>
#include <vector>
#include <algorithm>
constexpr int GxEPD_BLACK=0, GxEPD_RED=1, GxEPD_WHITE=2;
extern std::vector<std::string> drawCalls;
extern int hardwareRefreshes;
template<typename A, typename B, typename C>
auto constrain(A a, B lo, C hi) { return std::max<A>(lo, std::min<A>(a, hi)); }
struct GxEPD2_420c_GDEY042Z98 {
 static constexpr int HEIGHT = 300;
 GxEPD2_420c_GDEY042Z98(int, int, int, int) {}
};
template<typename P, int H> struct GxEPD2_3C {
 explicit GxEPD2_3C(P) {}
 template<typename... T> void log(const char* name, T... args) {
  std::ostringstream out; out << name; ((out << ':' << args), ...); drawCalls.push_back(out.str());
 }
 #define METHOD(name) template<typename... T> void name(T... args) { log(#name,args...); }
 METHOD(drawLine) METHOD(drawRect) METHOD(fillRect) METHOD(drawCircle) METHOD(fillCircle)
 METHOD(fillTriangle) METHOD(fillRoundRect) METHOD(fillScreen) METHOD(setTextColor)
 METHOD(setTextSize) METHOD(setCursor) METHOD(print) METHOD(init) METHOD(setRotation)
 METHOD(setFullWindow)
 #undef METHOD
 void drawBitmap(int x, int y, const uint8_t* bits, int width, int height, int color) {
  uint32_t hash=2166136261U;
  for(int i=0;i<((width+7)/8)*height;++i) { hash^=bits[i]; hash*=16777619U; }
  log("drawBitmap",x,y,width,height,color,hash);
 }
 void firstPage() { ++hardwareRefreshes; }
 bool nextPage() { return false; }
};
