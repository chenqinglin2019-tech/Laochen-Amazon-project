"""Shared fixtures for the V8 tests (never shipped in the release package)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def isolated_env(temp, *, bypass_auth=True):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LC_TEMPLATE_LIBRARY_DIR=str(Path(temp) / "library"),
               LC_AMAZON_STUDIO_CACHE=str(Path(temp) / "cache"), LC_AMAZON_STUDIO_HOME=str(Path(temp) / "home"))
    if bypass_auth:
        env["LC_SKIP_AUTH_PASS_FOR_TESTS"] = "1"
    else:
        env.pop("LC_SKIP_AUTH_PASS_FOR_TESTS", None)
    return env


def cli(env, *args):
    run = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "studio.py"), *map(str, args)],
                         capture_output=True, text=True, encoding="utf-8", env=env)
    lines = [line for line in run.stdout.strip().splitlines() if line.startswith("{")]
    data = json.loads(lines[-1]) if lines else {"ok": False, "error": run.stderr[-800:]}
    return run.returncode, data


def product_photo(path, *, size=2400, background=(250, 250, 250), colour=(40, 90, 160), lifestyle=False):
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    if lifestyle:
        for y in range(0, size, 40):
            draw.line((0, y, size, y + 300), fill=(150 + y % 80, 120, 90), width=18)
    draw.rounded_rectangle((size * 0.3, size * 0.2, size * 0.7, size * 0.8), int(size * 0.03), fill=colour)
    draw.rectangle((size * 0.38, size * 0.33, size * 0.62, size * 0.37), fill=(240, 200, 40))
    image.save(path, quality=92)
    return path


def fake_model_image(path, size, *, backdrop=(230, 225, 215), product=(40, 90, 160), product_box=(0.3, 0.2, 0.7, 0.85),
                     text=True):
    width, height = size
    image = Image.new("RGB", (width, height), backdrop)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = product_box
    draw.rounded_rectangle((width * x0, height * y0, width * x1, height * y1), int(width * 0.02), fill=product)
    if text:
        draw.text((width * 0.08, height * 0.06), "A Tidy Desk", fill=(20, 20, 20))
    image.save(path)
    return path


def basic_plan(catalog, slots, *, template=None, skip=()):
    family = next(f for f in catalog["families"] if f["templates"])
    template = template or family["templates"][0]["id"]
    plan = {"version": 1, "family": family["id"], "people": False,
            "product": {"name": "Blue desk organizer", "look": "Rounded blue box with a yellow front band",
                        "scale": "About 30 cm tall", "keep": ["yellow front band"], "facts": ["30 cm tall", "3 compartments"]},
            "slots": {"01_main": {"route": "auto"}}}
    for slot in slots:
        if slot["id"] == "01_main":
            continue
        plan["slots"][slot["id"]] = {"skip": True} if slot["id"] in skip else {
            "template": template, "message": "Keeps the desk tidy",
            "copy": {"headline": "A Tidy Desk", "subline": "Three compartments"}}
    return plan
