// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include <GxEPD2_3C.h>
#include <SPI.h>
#include "utf8_text.h"
#include <string.h>

#include "config.h"
#include "pages.h"

using Panel = GxEPD2_420c_GDEY042Z98;
GxEPD2_3C<Panel, Panel::HEIGHT> display(Panel(PIN_CS, PIN_DC, PIN_RST, PIN_BUSY));


namespace {

constexpr uint16_t SCREEN_W = 400;
constexpr uint16_t SCREEN_H = 300;
constexpr uint16_t MARGIN = 18;

void line(uint16_t y, uint16_t x1 = MARGIN, uint16_t x2 = SCREEN_W - MARGIN) {
  display.drawLine(x1, y, x2, y, GxEPD_BLACK);
}

void text(uint16_t x, uint16_t y, const char* value, uint8_t size = 1,
          uint16_t color = GxEPD_BLACK) {
  display.setTextColor(color);
  display.setTextSize(size);
  display.setCursor(x, y);
  display.print(value);
}

void centered(uint16_t y, const char* value, uint8_t size = 1,
              uint16_t color = GxEPD_BLACK) {
  const int16_t width = static_cast<int16_t>(strlen(value)) * 6 * size;
  const int16_t x = (SCREEN_W - width) / 2;
  text(x < 0 ? 0 : x, y, value, size, color);
}

uint8_t fittedTextSize(const char* value, uint8_t preferredSize,
                       uint16_t maxWidth = SCREEN_W) {
  if (value == nullptr || preferredSize == 0) return 1;
  const size_t length = strlen(value);
  if (length == 0) return preferredSize;
  uint8_t size = preferredSize;
  while (size > 1 && length * 6U * size > maxWidth) {
    --size;
  }
  return size;
}

void centeredFitted(uint16_t y, const char* value, uint8_t preferredSize,
                    uint16_t color = GxEPD_BLACK,
                    uint16_t maxWidth = SCREEN_W) {
  centered(y, value, fittedTextSize(value, preferredSize, maxWidth), color);
}

void checkbox(uint16_t x, uint16_t y, const char* label, bool checked,
              const uint8_t* pixels = nullptr) {
  display.drawRect(x, y - 10, 12, 12, GxEPD_BLACK);
  if (checked) {
    display.drawLine(x + 2, y - 4, x + 5, y - 1, GxEPD_BLACK);
    display.drawLine(x + 5, y - 1, x + 10, y - 8, GxEPD_BLACK);
  }
  if (pixels) display.drawBitmap(x + 20, y - 12, pixels, TITLE_BITMAP_WIDTH, TITLE_BITMAP_HEIGHT, GxEPD_BLACK);
  else text(x + 20, y, label);
}

void sectionLabel(uint16_t y, const char* value) {
  text(MARGIN, y, value, 1);
}

void drawLogo(uint16_t x = 345, uint16_t y = 19) {
  // Compact, one-colour rendering of the user's handwritten "hi." mark.
  display.drawLine(x + 2, y + 24, x + 7, y + 13, GxEPD_BLACK);
  display.drawLine(x + 7, y + 13, x + 13, y + 5, GxEPD_BLACK);
  display.drawLine(x + 13, y + 5, x + 19, y + 3, GxEPD_BLACK);
  display.drawLine(x + 19, y + 3, x + 15, y + 26, GxEPD_BLACK);
  display.drawLine(x + 15, y + 26, x + 22, y + 18, GxEPD_BLACK);
  display.drawLine(x + 22, y + 18, x + 27, y + 15, GxEPD_BLACK);
  display.drawLine(x + 27, y + 15, x + 26, y + 27, GxEPD_BLACK);
  display.drawLine(x + 26, y + 27, x + 32, y + 29, GxEPD_BLACK);
  display.fillCircle(x + 39, y + 27, 2, GxEPD_BLACK);
}

void drawCloud(uint16_t x, uint16_t y) {
  display.fillCircle(x + 12, y + 16, 12, GxEPD_BLACK);
  display.fillCircle(x + 28, y + 10, 15, GxEPD_BLACK);
  display.fillCircle(x + 45, y + 19, 11, GxEPD_BLACK);
  display.fillRect(x + 10, y + 19, 48, 12, GxEPD_BLACK);
}

void drawRadarIcon(uint16_t x, uint16_t y) {
  display.drawCircle(x + 19, y + 19, 18, GxEPD_BLACK);
  display.drawCircle(x + 19, y + 19, 12, GxEPD_BLACK);
  display.drawCircle(x + 19, y + 19, 5, GxEPD_BLACK);
  display.drawLine(x + 19, y + 19, x + 31, y + 7, GxEPD_BLACK);
  display.fillCircle(x + 33, y + 6, 4, GxEPD_RED);
}

void drawTodos(const Scene& scene, uint16_t firstY, uint16_t rowHeight, uint16_t firstX = MARGIN) {
  for (uint8_t index = 0; index < scene.todoCount; ++index) {
    checkbox(firstX, firstY + index * rowHeight, scene.todos[index].title, scene.todos[index].done,
             scene.utf8.present[index] ? scene.utf8.pixels[index] : nullptr);
  }
}

void drawHome(const Scene& scene) {
  drawLogo();
  if (scene.stale) {
    text(292, 18, "STALE", 1, GxEPD_RED);
  }
  text(MARGIN, 41, scene.date, 2);
  line(56);

  drawCloud(21, 79);
  char temperature[8];
  if (scene.weatherAvailable) {
    snprintf(temperature, sizeof(temperature), "%d", scene.temperature);
  } else {
    strlcpy(temperature, "--", sizeof(temperature));
  }
  text(92, 104, temperature, 4);
  text(152, 103, "o", 1);
  // Keep the weather description below the four-times scaled temperature.
  text(94, 141, scene.condition, 1);
  display.drawLine(206, 77, 206, 134, GxEPD_BLACK);

  drawRadarIcon(230, 80);
  text(278, 83, "RADAR", 1);
  text(278, 99, radarStatusText(scene.radarStatus), 1,
       scene.radarStatus == RadarStatus::Failed ? GxEPD_RED : GxEPD_BLACK);
  text(230, 122, scene.details.radarDate, 1);
  text(230, 137, scene.details.radarFresh ? "TODAY / VERIFIED" : "CACHED / UNVERIFIED", 1);
  text(MARGIN, 153, scene.details.weatherFresh ? "WEATHER FRESH" : "WEATHER UNKNOWN / STALE", 1);
  line(164);

  sectionLabel(175, "TODAY");
  drawTodos(scene, 205, 26);
  if (scene.details.todoRemaining) {
    char more[24];
    snprintf(more, sizeof(more), "+%u MORE IN HUB", scene.details.todoRemaining);
    text(MARGIN, 271, more);
  }

  display.fillRect(MARGIN, 281, 17, 2, GxEPD_RED);
  text(44, 287, "A CALMER, BRIGHTER YOU", 1);
}

void drawWorkspace(const Scene& scene) {
  text(MARGIN, 20, "WORKSPACE");
  if (scene.stale) text(330, 20, "STALE", 1, GxEPD_RED);
  text(MARGIN, 44, scene.details.project,
       fittedTextSize(scene.details.project, 2, SCREEN_W - 2 * MARGIN));
  text(MARGIN, 69, "CURRENT");
  if (scene.utf8.present[MAX_TODOS]) display.drawBitmap(MARGIN, 72, scene.utf8.pixels[MAX_TODOS], TITLE_BITMAP_WIDTH, TITLE_BITMAP_HEIGHT, GxEPD_BLACK);
  else text(MARGIN, 84, scene.details.currentItem);
  line(97);
  text(MARGIN, 112, "NEXT / USER ORDER");
  drawTodos(scene, 135, 19);
  if (scene.details.todoRemaining) {
    char more[24];
    snprintf(more, sizeof(more), "+%u MORE IN HUB", scene.details.todoRemaining);
    text(258, 112, more);
  }
  line(186);
  text(MARGIN, 202, "GROK BOT SUGGESTION");
  text(MARGIN, 219, scene.details.suggestion);
  line(232);
  char five[12], seven[12], row[64];
  if (scene.quota5hRemaining < 0) strlcpy(five, "UNKNOWN", sizeof(five));
  else snprintf(five, sizeof(five), "%d%%", scene.quota5hRemaining);
  if (scene.quotaTotalRemaining < 0) strlcpy(seven, "UNKNOWN", sizeof(seven));
  else snprintf(seven, sizeof(seven), "%d%%", scene.quotaTotalRemaining);
  if (scene.details.showFiveHour) snprintf(row, sizeof(row), "CODEX 5H %s   7D %s", five, seven);
  else snprintf(row, sizeof(row), "CODEX 7D REMAINING %s", seven);
  text(MARGIN, 249, row);
  snprintf(row, sizeof(row), "VALUE SAMPLE UTC %s", scene.details.quotaObserved);
  text(MARGIN, 269, row);
}

void drawTibo(const Scene& scene) {
  text(MARGIN, 20, "TIBO RESET WATCH", 2);
  if (scene.stale) text(330, 20, "STALE", 1, GxEPD_RED);
  line(43);
  char row[64];
  snprintf(row, sizeof(row), "EVENT FEED: %s", scene.tibo.status);
  text(MARGIN, 57, row);
  snprintf(row, sizeof(row), "LAST RECORD: %s", scene.tibo.kind);
  text(MARGIN, 80, row);
  snprintf(row, sizeof(row), "POST UTC %s", scene.tibo.announcedAt);
  text(MARGIN, 100, row);
  text(MARGIN, 120, scene.tibo.pending);
  line(140);
  snprintf(row, sizeof(row), "EXPERIMENTAL FORECAST: %s", scene.tibo.forecastStatus);
  text(MARGIN, 154, row);
  const int chances[] = {scene.tibo.p24, scene.tibo.p48, scene.tibo.p72};
  for (int i = 0; i < 3; ++i) {
    const int x = MARGIN + i * 122;
    snprintf(row, sizeof(row), "%dH", (i + 1) * 24);
    text(x, 178, row);
    if (chances[i] < 0) strlcpy(row, "--", sizeof(row));
    else snprintf(row, sizeof(row), "%d%%", chances[i]);
    text(x, 198, row, 2);
  }
  line(228);
  text(MARGIN, 241, "Data: codex-resets.com / nextreset.ai");
  text(MARGIN, 259, "Community estimate; not an official promise.");
  text(MARGIN, 278, "Account quota is separate. Details in Hub.");
}

void drawInterrupt(const Scene& scene) {
  if (scene.stale) {
    text(324, 18, "STALE", 1, GxEPD_RED);
  }
  display.fillTriangle(172, 33, 228, 33, 200, 87, GxEPD_RED);
  text(195, 73, "!", 3, GxEPD_WHITE);
  display.drawLine(158, 48, 146, 38, GxEPD_RED);
  display.drawLine(242, 48, 254, 38, GxEPD_RED);
  display.drawLine(154, 64, 139, 64, GxEPD_RED);
  display.drawLine(246, 64, 261, 64, GxEPD_RED);

  centeredFitted(122, scene.interruptTitle, 2, GxEPD_BLACK, SCREEN_W - 2 * MARGIN);
  centeredFitted(176, scene.interruptMessage, 5, GxEPD_RED, SCREEN_W - 2 * MARGIN);
  centeredFitted(211, scene.interruptDetail, 1, GxEPD_BLACK, SCREEN_W - 2 * MARGIN);
  centered(233, "ACTION REQUIRED", 1);
  display.fillRoundRect(104, 251, 192, 30, 4, GxEPD_RED);
  centered(272, "ACK IN HUB WEB", 1, GxEPD_WHITE);
}

void draw(const Scene& scene) {
  display.fillScreen(GxEPD_WHITE);
  switch (scene.page) {
    case Page::Home:
      drawHome(scene);
      break;
    case Page::Workspace:
      drawWorkspace(scene);
      break;
    case Page::Tibo:
      drawTibo(scene);
      break;
    case Page::Interrupt:
      drawInterrupt(scene);
      break;
  }
  if (scene.details.simulated) text(145, 8, "SIMULATED", 1, GxEPD_RED);
}

}  // namespace

const char* pageName(Page page) {
  switch (page) {
    case Page::Home: return "HOME";
    case Page::Workspace: return "WORKSPACE";
    case Page::Interrupt: return "INTERRUPT";
    case Page::Tibo: return "TIBO";
  }
  return "UNKNOWN";
}

void initDisplay() {
  display.init(SERIAL_BAUD);
  display.setRotation(0);

}

void renderPage(const Scene& scene) {
  display.setFullWindow();
  display.firstPage();
  do {
    draw(scene);
  } while (display.nextPage());
}
