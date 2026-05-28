import random

AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
VIEWPORTS = [(1920,1080),(1366,768),(1440,900),(1536,864),(1280,720),(1600,900)]
LOCALES = ["en-US","en-GB","en-IN","en-CA"]
TIMEZONES = ["America/New_York","America/Chicago","America/Los_Angeles","Europe/London","Asia/Kolkata"]

def browser_fingerprint() -> dict:
    w, h = random.choice(VIEWPORTS)
    return {
        "user_agent": random.choice(AGENTS),
        "viewport": {"width": w, "height": h},
        "locale": random.choice(LOCALES),
        "timezone_id": random.choice(TIMEZONES),
        "device_scale_factor": random.choice([1, 1.25, 1.5, 2]),
    }
