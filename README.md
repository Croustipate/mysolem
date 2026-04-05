# Solem Irrigation — Home Assistant Integration

Unofficial Home Assistant custom integration for **Solem LRMB10 + LRIS6** irrigation systems using the [mysolem.com](https://mysolem.com) cloud API.

> This integration was reverse-engineered from the official Solem iPhone app using Proxyman. It is not affiliated with or endorsed by SOLEM.

---

## Hardware supported

| Device | Model | Role |
|--------|-------|------|
| LRMB10 | `lr-mb-10` | WiFi gateway — connects to cloud via HTTPS |
| LRIS6  | `lr-is`    | 6-zone irrigation controller — communicates via LoRa radio to the LRMB10 |

Other Solem LoRa controllers (LRIS4, LRIS12…) may work if they share the same API — untested.

---

## Architecture

```
Home Assistant → HTTPS REST → mysolem.com cloud
                                    ↓ long-polling
                              LRMB10 relay (WiFi)
                                    ↓ LoRa radio
                              LRIS6 controller
                                    ↓
                              Solenoid valves
```

Commands sent via `POST /api/module/{relay_sn}/manual/{controller_suffix}` reach the controller in **real-time** (no queuing delay).

---

## Features

- **Zone switches** — one switch per irrigation zone (manual start/stop)
- **Program switches** — one switch per watering program (A/B/C)
- **Zone duration** — configurable per-zone watering duration (number entity, 1–240 min)
- **Rain delay** — suspend all automatic watering for N days
- **Sensors**:
  - Watering state (Idle / Zone N active / Program N running)
  - Currently running zone
  - Currently running program
  - Last LoRa radio communication timestamp

---

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Install **Solem Irrigation**
3. Restart Home Assistant

### Manual

Copy the `custom_components/solem/` folder into your HA config directory:

```
config/
└── custom_components/
    └── solem/
        ├── __init__.py
        ├── manifest.json
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── api.py
        ├── switch.py
        ├── sensor.py
        ├── number.py
        └── translations/
            └── fr.json
```

Restart Home Assistant.

---

## Configuration

Go to **Settings → Devices & Services → Add Integration → Solem Irrigation**.

You will need two values from your mysolem.com session, captured via a proxy tool (e.g. [Proxyman](https://proxyman.io/) on iPhone):

| Field | Where to find it | Validity |
|-------|-----------------|----------|
| **Bearer Token** | Value after `Bearer ` in the `Authorization` request header | ~60 days |
| **Session Cookie** | Value of `solem-irrigation-platform.sid` in the `Cookie` request header | Session-based |

### How to capture these values

1. Install **Proxyman** on your iPhone and enable SSL proxying for `mysolem.com`
2. Open the **mysolem** app and log in (or perform any action)
3. In Proxyman, open any request to `mysolem.com` → **Request → Headers**
4. Copy the `Authorization` header value (without the `Bearer ` prefix)
5. Copy the `solem-irrigation-platform.sid` cookie value

### Token renewal

When the token expires (~60 days), recapture it from Proxyman and update the integration via **Settings → Devices & Services → Solem Irrigation → Reconfigure**.

---

## API reference (reverse-engineered)

### Authentication
```
POST /oauth2/token
Content-Type: application/json
Accept: version=2.8

{"grant_type": "password", "username": "...", "password": "...", "scope": "email"}
```
> Note: authentication requires an active session cookie (`solem-irrigation-platform.sid`). The session is created by the mobile app; it cannot currently be initiated programmatically.

### Manual zone control
```
POST /api/module/{relay_serial}/manual/{controller_suffix}
Authorization: Bearer {token}
Cookie: solem-irrigation-platform.sid={cookie}

# Start zone N for duration
{"watering": {"action": 2, "station": N, "time": "HH:MM"}}

# Stop all watering
{"watering": {"action": 0}}

# Run program P (1–3) — unconfirmed
{"watering": {"action": 1, "program": P}}
```

`controller_suffix` = last 3 bytes of the controller MAC address without colons  
(e.g. `C8:B9:61:F0:3B:2D` → `F03B2D`)

Response is **real-time** from the controller via LoRa:
```json
{
  "dialogTimeStamp": "...",
  "temperature": 20,
  "watering": {"state": 0, "runningStation": 1, ...},
  "radio": ["cmd"]
}
```

### Status polling
```
GET /api/getModuleInventory?module={relay_id}&data=1
```
Returns programs and current watering status. Polled every 60 seconds.

Zone outputs (static) are fetched from:
```
GET /api/getUserWithHisModules
```

---

## Known limitations

- **Authentication cannot be automated** — the server requires an existing mobile app session cookie. Token renewal requires Proxyman capture.
- **Program run confirmation** — `action: 1` for running a program has not been confirmed via capture; it may require a different payload.
- **Rain delay control** — the exact API payload for rain delay has not been captured yet.
- **Single relay** — only the first LRMB10 relay in the account is used.

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install aiohttp

# Test API connectivity (use token from Proxyman)
SOLEM_TOKEN="your_token" SOLEM_COOKIE="your_cookie" python3 test_api.py
```

---

## Contributing

Contributions welcome — especially:
- Confirmation of `action: 1` (run program) payload
- Rain delay API payload capture
- Testing with other Solem LoRa controllers (LRIS4, LRIS12, LRMB4…)

---

## License

MIT
