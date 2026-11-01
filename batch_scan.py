"""Run one Telegram channel scan, then disconnect and exit.

This entry point is intended for cron. It reuses the processing pipeline from
``main.py`` without starting the real-time listener, web dashboard, or any
long-running worker.
"""

import asyncio
import logging

from channel_manager import load_channels
from main import client, join_channel, retry_pending_notifications, scan_today_signals


logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_BOT_SESSION = 2
EXIT_UNAUTHORIZED_SESSION = 3
EXIT_PARTIAL_FAILURE = 4


def disable_realtime_handlers() -> int:
    """Remove handlers registered by ``main.py`` from this batch-only process."""
    handlers = list(client.list_event_handlers())
    for callback, event in handlers:
        client.remove_event_handler(callback, event)
    return len(handlers)


async def sync_channel_joins_once() -> dict:
    """Validate saved channel ids and resolve stale or missing ones once."""
    stats = {
        "channels": 0,
        "already_resolved": 0,
        "resolved": 0,
        "unresolved": 0,
        "errors": 0,
    }

    for channel in load_channels():
        stats["channels"] += 1
        identifier = channel.get("identifier", "<unknown>")

        chat_id = channel.get("chat_id")
        if chat_id:
            try:
                await client.get_entity(chat_id)
            except Exception as exc:
                logger.warning(
                    "Saved chat id %s for %s is not usable; retrying via identifier: %s",
                    chat_id,
                    identifier,
                    exc,
                )
            else:
                stats["already_resolved"] += 1
                continue

        try:
            title = await join_channel(channel)
            if title:
                stats["resolved"] += 1
                logger.info("Channel resolved: %s (%s)", identifier, title)
            else:
                stats["unresolved"] += 1
                logger.warning("Channel could not be resolved to a chat id: %s", identifier)
        except Exception as exc:
            stats["errors"] += 1
            logger.warning("Could not join or resolve channel %s: %s", identifier, exc)

    return stats


async def run_batch_scan() -> int:
    """Execute one complete batch run and return a process exit code."""
    try:
        removed_handlers = disable_realtime_handlers()
        if removed_handlers:
            logger.info(
                "Disabled %s real-time Telegram handler(s) for batch mode",
                removed_handlers,
            )

        # ``connect`` deliberately avoids an interactive login prompt in cron.
        # The user session must have been created before scheduling this script.
        await client.connect()

        if not await client.is_user_authorized():
            logger.error(
                "The Telethon session is not authorized. Create the session once "
                "with the Telegram user account before running cron."
            )
            return EXIT_UNAUTHORIZED_SESSION

        account = await client.get_me()
        if getattr(account, "bot", False):
            logger.error(
                "crypto_listener_session.session belongs to a bot. "
                "A Telegram user-account session is required to read channel history."
            )
            return EXIT_BOT_SESSION

        join_stats = await sync_channel_joins_once()
        retry_stats = await retry_pending_notifications()
        scan_stats = await scan_today_signals()

        logger.info(
            "Batch scan completed. channels=%s resolved=%s join_errors=%s "
            "join_unresolved=%s pending=%s sent=%s retry_failed=%s messages=%s "
            "new_signals=%s duplicates=%s notification_failures=%s scan_errors=%s",
            join_stats.get("channels", 0),
            join_stats.get("resolved", 0),
            join_stats.get("errors", 0),
            join_stats.get("unresolved", 0),
            retry_stats.get("pending", 0),
            retry_stats.get("sent", 0),
            retry_stats.get("failed", 0),
            scan_stats.get("messages", 0),
            scan_stats.get("new_signals", 0),
            scan_stats.get("duplicates", 0),
            scan_stats.get("notification_failures", 0),
            scan_stats.get("errors", 0),
        )

        partial_failure = any(
            (
                join_stats.get("errors", 0),
                join_stats.get("unresolved", 0),
                retry_stats.get("failed", 0),
                scan_stats.get("errors", 0),
                scan_stats.get("notification_failures", 0),
            )
        )
        if partial_failure:
            logger.error("Batch scan completed with partial failures")
            return EXIT_PARTIAL_FAILURE
        return EXIT_OK
    except Exception:
        logger.exception("Batch scan failed")
        return EXIT_RUNTIME_ERROR
    finally:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            logger.exception("Could not disconnect the Telethon client cleanly")


def main() -> int:
    """Synchronous CLI wrapper."""
    return asyncio.run(run_batch_scan())


if __name__ == "__main__":
    raise SystemExit(main())
