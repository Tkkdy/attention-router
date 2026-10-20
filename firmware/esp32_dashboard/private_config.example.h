// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once
// Copy to private_config.h locally. Never commit that file or compiled firmware.
#define DASHBOARD_WIFI_SSID "YOUR_2_4_GHZ_WIFI"
#define DASHBOARD_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
// Windows private LAN IPv4; match the port in config.local.json.
#define DASHBOARD_HUB_URL "http://192.168.1.10:8765"
// Optional outbound network services: empty means unconfigured.
#define DASHBOARD_INTERNET_CHECK_URL ""
// Match the expected response of your own optional connectivity endpoint.
#define DASHBOARD_INTERNET_CHECK_STATUS 0
#define DASHBOARD_INTERNET_CHECK_LOCATION ""
#define DASHBOARD_TIMEZONE ""
#define DASHBOARD_NTP_SERVER_1 ""
#define DASHBOARD_NTP_SERVER_2 ""
#define DASHBOARD_WEATHER_LATITUDE ""
#define DASHBOARD_WEATHER_LONGITUDE ""
#define DASHBOARD_RADAR_URL ""
