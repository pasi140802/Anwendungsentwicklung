"""Einfacher Lasttest für NFA-01: 50 gleichzeitige Nutzer laden den Wochenkalender.

Voraussetzung: laufende Anwendung mit Demo-Daten (docker compose up).
Aufruf: python docs/lasttest/lasttest.py [Basis-URL] [Dauer in s] [Denkzeit in s]

Ohne Denkzeit (0) schickt jeder Nutzer sofort die nächste Anfrage (Stresstest).
Mit Denkzeit (z. B. 1) wartet jeder Nutzer zwischen zwei Seitenaufrufen im Mittel so
lange (zufällig zwischen 50 und 150 %), und die Nutzer starten versetzt. Sonst
liefen alle 50 im Gleichtakt und schickten jede Sekunde 50 Anfragen auf einmal.
"""

import asyncio
import random
import re
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 30
THINK = float(sys.argv[3]) if len(sys.argv) > 3 else 0
USERS = 50


async def login(email: str) -> httpx.Cookies:
    """Meldet sich einmal an und gibt das Sitzungs-Cookie zurück.

    Die Nutzer teilen sich die Sitzung je Adresse, weil die Anwendung
    Anmeldeversuche je Adresse und IP begrenzt (Schutz vor Passwortraten).
    """
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        page = await client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        await client.post("/login", data={"email": email, "password": "demo-courtslot",
                                          "csrf_token": token})
        return client.cookies


async def user(cookies: httpx.Cookies, latencies: list[float], errors: list[int]) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=10, cookies=cookies) as client:
        if THINK:
            await asyncio.sleep(random.uniform(0, THINK))  # versetzter Start
        end = time.perf_counter() + DURATION
        while time.perf_counter() < end:
            start = time.perf_counter()
            r = await client.get("/kalender")
            latencies.append((time.perf_counter() - start) * 1000)
            if r.status_code != 200:
                errors.append(r.status_code)
            if THINK:
                await asyncio.sleep(THINK * random.uniform(0.5, 1.5))


async def main() -> None:
    emails = ["admin@tc-isartal.de", "lena.hofmann@tc-isartal.de"]
    latencies: list[float] = []
    errors: list[int] = []
    sessions = [await login(email) for email in emails]
    await asyncio.gather(*(user(sessions[i % 2], latencies, errors) for i in range(USERS)))
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    print(f"{USERS} gleichzeitige Nutzer, Denkzeit {THINK:g} s, {DURATION:.0f} s, "
          f"{len(latencies)} Anfragen, "
          f"{len(latencies) / DURATION:.0f} Anfragen/s, Fehler: {len(errors)}")
    print(f"Median {statistics.median(latencies):.0f} ms, p95 {p95:.0f} ms, "
          f"max {latencies[-1]:.0f} ms")
    print("NFA-01 (p95 < 500 ms):", "erfüllt" if p95 < 500 and not errors else "nicht erfüllt")


if __name__ == "__main__":
    asyncio.run(main())
