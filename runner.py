# -*- coding: utf-8 -*-
"""Runner for Koyeb/containers.

- Keeps bot.py logic intact.
- Builds aiogram Bot with an AiohttpSession configured in a version-tolerant way.
- Prefers IPv4 (some environments have flaky IPv6 to Telegram).

Usage:
  python runner.py
"""

import asyncio
import os
import socket
import inspect

from aiohttp import web

import bot as app  # your original single-file bot


async def _build_bot():
    """Create a Bot instance compatible with the original module, but with safer networking defaults."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.client.session.aiohttp import AiohttpSession

    token = os.getenv("BOT_TOKEN") or getattr(app, "API_TOKEN", None)
    if not token:
        raise RuntimeError("BOT_TOKEN (or API_TOKEN in bot.py) topilmadi")

    # Build aiohttp connector preferring IPv4
    connector = None
    try:
        import aiohttp
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
    except Exception:
        connector = None

    # Instantiate AiohttpSession without passing unsupported kwargs (aiogram version differences)
    kwargs = {}
    try:
        params = inspect.signature(AiohttpSession.__init__).parameters
        if connector is not None and "connector" in params:
            kwargs["connector"] = connector
        # Some aiogram versions DON'T accept trust_env in BaseSession; only pass if supported.
        if "trust_env" in params:
            kwargs["trust_env"] = True
    except Exception:
        # If signature introspection fails, fall back to no kwargs.
        kwargs = {}

    session = AiohttpSession(**kwargs)

    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


async def main():
    bot = await _build_bot()

    # --- Koyeb Web Service compatibility ---
    # If your Koyeb Service is configured as a Web Service, it will run a TCP health check on $PORT.
    # Your bot is a long-lived polling worker and doesn't listen on a port by default, so we expose
    # a tiny HTTP endpoint to satisfy health checks without changing your bot logic.
    port = int(os.getenv("PORT", "8000"))

    health_app = web.Application()

    async def _health(_request):
        return web.Response(text="ok")

    health_app.router.add_get("/", _health)
    health_app.router.add_get("/health", _health)

    health_runner = web.AppRunner(health_app)
    await health_runner.setup()
    health_site = web.TCPSite(health_runner, host="0.0.0.0", port=port)
    await health_site.start()

    # Patch the module-level bot so handlers that reference `bot` keep working.
    try:
        app.bot = bot
    except Exception:
        pass

    # Ensure router is included once (best-effort)
    try:
        included = getattr(app, "_KOYEB_ROUTER_INCLUDED", False)
        if not included:
            try:
                app.dp.include_router(app.router)
            except Exception:
                pass
            app._KOYEB_ROUTER_INCLUDED = True
    except Exception:
        pass

    # Startup hooks (if defined)
    try:
        if hasattr(app, "on_startup"):
            try:
                app.dp.startup.register(app.on_startup)
            except Exception:
                pass
    except Exception:
        pass

    try:
        await app.dp.start_polling(bot)
    finally:
        try:
            await health_runner.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
