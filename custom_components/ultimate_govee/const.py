"""Constants for the Ultimate Govee integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ultimate_govee"
MANUFACTURER: Final = "Govee"
NAME: Final = "Ultimate Govee"

CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_TOKEN_EXPIRES_AT: Final = "token_expires_at"
CONF_CLIENT_ID: Final = "client_id"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_ACCOUNT_TOPIC: Final = "account_topic"
CONF_ENABLE_LAN: Final = "enable_lan"
CONF_ENABLE_IOT: Final = "enable_iot"
CONF_ENABLE_EFFECTS: Final = "enable_effects"
CONF_ENABLE_TAP_TO_RUNS: Final = "enable_tap_to_runs"
CONF_IGNORED_DEVICES: Final = "ignored_devices"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_LAN_SCAN_INTERVAL: Final = "lan_scan_interval"

DEFAULT_ENABLE_LAN: Final = True
DEFAULT_ENABLE_IOT: Final = True
DEFAULT_ENABLE_EFFECTS: Final = True
DEFAULT_ENABLE_TAP_TO_RUNS: Final = False
DEFAULT_POLL_INTERVAL: Final = 60
DEFAULT_LAN_SCAN_INTERVAL: Final = 60

MIN_POLL_INTERVAL: Final = 15
MAX_POLL_INTERVAL: Final = 3600

PLATFORMS: Final = [
    "binary_sensor",
    "button",
    "fan",
    "humidifier",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
]

UPDATE_INTERVAL: Final = timedelta(seconds=DEFAULT_POLL_INTERVAL)

# Cloud API endpoints (the same ones the Govee Home app uses).
AUTH_URL: Final = "https://app2.govee.com/account/rest/account/v1/login"
REFRESH_URL: Final = "https://app2.govee.com/account/rest/v1/first/refresh-tokens"
IOT_CERT_URL: Final = "https://app2.govee.com/app/v1/account/iot/key"
DEVICE_LIST_URL: Final = "https://app2.govee.com/device/rest/devices/v1/list"
EFFECT_LIBRARY_URL: Final = "https://app2.govee.com/appsku/v1/light-effect-libraries"
TAP_TO_RUN_URL: Final = "https://app2.govee.com/bff-app/v1/exec-plat/home"

APP_VERSION: Final = "5.6.01"
USER_AGENT: Final = (
    "GoveeHome/5.6.01 (com.ihoment.GoVeeSensor; build:2; iOS 16.5.0) Alamofire/5.6.4"
)

# Amazon Root CA 1, used by the AWS IoT broker.
AMAZON_ROOT_CA1: Final = """-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
"""
