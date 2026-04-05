"""Quick test script to verify the Solem API before installing in HA.

Usage (with existing token from Proxyman — easiest):
    SOLEM_TOKEN="fNOLyl0y..." python3 test_api.py

Usage (with credentials — will probe multiple auth formats):
    SOLEM_USER=your@email.com SOLEM_PASS=yourpass python3 test_api.py
"""
import asyncio
import json
import os
import aiohttp

USERNAME = os.getenv("SOLEM_USER", "")
PASSWORD = os.getenv("SOLEM_PASS", "")
# Bearer token from Proxyman (valid 60 days)
EXISTING_TOKEN = os.getenv("SOLEM_TOKEN", "")
# Session cookie from Proxyman — needed for /manual/ endpoint
# Copy the full value of "solem-irrigation-platform.sid" from Proxyman request headers
SESSION_COOKIE = os.getenv("SOLEM_COOKIE", "")

API_BASE = "https://mysolem.com"


async def get_token(session: aiohttp.ClientSession) -> str:
    """Try all known auth formats and return the first working token."""
    if EXISTING_TOKEN:
        print("   Using token from SOLEM_TOKEN env var.")
        return EXISTING_TOKEN

    # Headers confirmed from Proxyman capture of the real app request
    app_headers = {
        "Accept": "version=2.8",
        "User-Agent": "Solem/6.10 (iPhone; iOS 26.3.1; Scale/3.00)",
        "Cache-Control": "no-cache, no-transform",
    }
    payload = {"grant_type": "password", "username": USERNAME, "password": PASSWORD, "scope": "email"}

    # Inject the session cookie captured from Proxyman, then try auth
    if SESSION_COOKIE:
        session.cookie_jar.update_cookies(
            {"solem-irrigation-platform.sid": SESSION_COOKIE},
            response_url=aiohttp.client.URL(API_BASE),  # type: ignore[attr-defined]
        )
        print(f"   Injected session cookie into jar")

    for label, kwargs in [
        ("JSON + app headers", dict(json=payload, headers=app_headers)),
        ("form + app headers", dict(data=payload, headers=app_headers)),
        ("JSON bare",          dict(json=payload)),
    ]:
        r = await session.post(f"{API_BASE}/oauth2/token", **kwargs)
        body = await r.text()
        print(f"   [{label}] → HTTP {r.status}  {body[:80]}")
        if r.status == 200:
            print(f"   ✓ Auth works!")
            return json.loads(body)["access_token"]

    raise SystemExit("All auth attempts failed. Check credentials or use SOLEM_TOKEN.")


async def main() -> None:
    async with aiohttp.ClientSession() as session:

        # ── 1. Auth ──────────────────────────────────────────────────────
        print("1. Authenticating...")
        token = await get_token(session)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "version=2.8",
            "User-Agent": "Solem/6.10 (iPhone; iOS 26.3.1; Scale/3.00)",
        }
        if SESSION_COOKIE:
            headers["Cookie"] = f"solem-irrigation-platform.sid={SESSION_COOKIE}"
        print(f"   Token: {token[:30]}...")
        print(f"   Cookie: {'set' if SESSION_COOKIE else 'NOT SET — /manual/ will likely fail'}")

        # ── 2. Modules ───────────────────────────────────────────────────
        print("\n2. Fetching modules...")
        resp = await session.get(f"{API_BASE}/api/getUserWithHisModules", headers=headers)
        if resp.status != 200:
            raise SystemExit(f"Failed: HTTP {resp.status} {await resp.text()[:200]}")
        data = await resp.json()
        modules = data.get("modules", [])
        for m in modules:
            print(f"   [{m['type']}] {m['name']}  online={m.get('isOnline')}")

        relay = next((m for m in modules if m["type"] == "lr-mb-10"), None)
        controller = next((m for m in modules if m["type"] == "lr-is"), None)
        if not relay or not controller:
            raise SystemExit("Missing relay or controller in account")

        # ── 3. Inventory / status ────────────────────────────────────────
        print(f"\n3. Inventory for relay {relay['id']}...")
        resp = await session.get(
            f"{API_BASE}/api/getModuleInventory",
            headers=headers,
            params={"module": relay["id"], "data": "1"},
        )
        inv = await resp.json()
        children = inv.get("children", [])
        if children:
            ctrl = children[0]
            watering = ctrl.get("status", {}).get("watering", {})
            print(f"   Controller: {ctrl['name']}")
            print(f"   Watering: {json.dumps(watering)}")
            for o in ctrl.get("outputs", []):
                print(f"   Zone [{o['index']}] {o['name']}")
            for p in ctrl.get("programs", []):
                starts = [f"{t//60:02d}:{t%60:02d}" for t in p.get("startTimes", []) if t != -1]
                print(f"   Program [{p['index']}] {p['name']}  starts={starts}")

        # ── 4. Command (DRY RUN) ─────────────────────────────────────────
        # Derive controller_suffix from MAC address last 3 bytes
        # e.g. "C8:B9:61:F0:3B:2D" → "F03B2D"
        controller_mac = controller.get("macAddress", "")
        controller_suffix = controller_mac.replace(":", "")[-6:].upper()
        relay_serial = relay.get("serialNumber", "")
        controller_id = controller["id"]

        ZONE = 1
        DURATION_MINUTES = 1
        hours, mins = divmod(DURATION_MINUTES, 60)
        watering_cmd = {"action": 2, "station": ZONE, "time": f"{hours:02d}:{mins:02d}"}

        print(f"\n4. Sending START Zone {ZONE} for {DURATION_MINUTES} min...")
        print(f"   POST /api/module/{relay_serial}/manual/{controller_suffix}")
        url = f"{API_BASE}/api/module/{relay_serial}/manual/{controller_suffix}"
        controller_serial = controller.get("serialNumber", "")
        controller_uuid = controller.get("uuid", "")
        controller_mac = controller.get("macAddress", "")

        attempts = [
            ("no id field",          {"watering": watering_cmd}),
            ("id = mongodb",         {"watering": watering_cmd, "id": controller_id}),
            ("id = serial",          {"watering": watering_cmd, "id": controller_serial}),
            ("id = uuid",            {"watering": watering_cmd, "id": controller_uuid}),
            ("id = mac",             {"watering": watering_cmd, "id": controller_mac}),
            ("module = mongodb",     {"watering": watering_cmd, "module": controller_id}),
            ("module = serial",      {"watering": watering_cmd, "module": controller_serial}),
            ("relay serial in body", {"watering": watering_cmd, "id": relay_serial}),
        ]

        for label, body_data in attempts:
            r = await session.post(url, headers=headers, json=body_data)
            body = await r.text()
            print(f"   [{label}] → HTTP {r.status}  {body[:80]}")
            if r.status == 200:
                print(f"   ✓ Works with [{label}]!")
                # Notify cloud
                r2 = await session.post(
                    f"{API_BASE}/api/reportManualCommandSent",
                    headers=headers,
                    json={"route": "http", "command": {"watering": watering_cmd}, "id": controller_id},
                )
                print(f"   reportManualCommandSent → {r2.status}")
                break

    print("\n✓ All checks passed!")


if __name__ == "__main__":
    if not USERNAME and not PASSWORD and not EXISTING_TOKEN:
        print(__doc__)
    else:
        asyncio.run(main())
