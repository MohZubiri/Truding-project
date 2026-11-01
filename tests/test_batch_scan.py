import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import batch_scan


class FakeClient:
    def __init__(self, *, authorized=True, bot=False, calls=None):
        self.authorized = authorized
        self.bot = bot
        self.connected = False
        self.calls = calls if calls is not None else []
        self.handlers = []

    def list_event_handlers(self):
        self.calls.append("list_handlers")
        return list(self.handlers)

    def remove_event_handler(self, callback, event):
        self.handlers.remove((callback, event))

    async def connect(self):
        self.calls.append("connect")
        self.connected = True

    async def is_user_authorized(self):
        self.calls.append("authorize")
        return self.authorized

    async def get_me(self):
        self.calls.append("get_me")
        return SimpleNamespace(bot=self.bot)

    def is_connected(self):
        return self.connected

    async def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False


class BatchRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_run_uses_expected_order_and_disconnects(self):
        calls = []
        fake_client = FakeClient(calls=calls)

        async def joins():
            calls.append("joins")
            return {"channels": 2, "resolved": 1, "errors": 0}

        async def retry():
            calls.append("retry")
            return {"pending": 1, "sent": 1, "failed": 0}

        async def scan():
            calls.append("scan")
            return {
                "messages": 4,
                "new_signals": 1,
                "duplicates": 0,
                "errors": 0,
            }

        with (
            patch.object(batch_scan, "client", fake_client),
            patch.object(batch_scan, "sync_channel_joins_once", new=joins),
            patch.object(batch_scan, "retry_pending_notifications", new=retry),
            patch.object(batch_scan, "scan_today_signals", new=scan),
        ):
            exit_code = await batch_scan.run_batch_scan()

        self.assertEqual(exit_code, batch_scan.EXIT_OK)
        self.assertEqual(
            calls,
            [
                "list_handlers",
                "connect",
                "authorize",
                "get_me",
                "joins",
                "retry",
                "scan",
                "disconnect",
            ],
        )
        self.assertFalse(fake_client.connected)

    async def test_bot_session_is_rejected_before_any_work(self):
        fake_client = FakeClient(bot=True)
        joins = AsyncMock()
        retry = AsyncMock()
        scan = AsyncMock()

        with (
            patch.object(batch_scan, "client", fake_client),
            patch.object(batch_scan, "sync_channel_joins_once", new=joins),
            patch.object(batch_scan, "retry_pending_notifications", new=retry),
            patch.object(batch_scan, "scan_today_signals", new=scan),
        ):
            exit_code = await batch_scan.run_batch_scan()

        self.assertEqual(exit_code, batch_scan.EXIT_BOT_SESSION)
        joins.assert_not_awaited()
        retry.assert_not_awaited()
        scan.assert_not_awaited()
        self.assertFalse(fake_client.connected)

    async def test_unauthorized_session_is_rejected_without_prompting(self):
        fake_client = FakeClient(authorized=False)

        with (
            patch.object(batch_scan, "client", fake_client),
            patch.object(batch_scan, "sync_channel_joins_once", new=AsyncMock()) as joins,
            patch.object(batch_scan, "retry_pending_notifications", new=AsyncMock()) as retry,
            patch.object(batch_scan, "scan_today_signals", new=AsyncMock()) as scan,
        ):
            exit_code = await batch_scan.run_batch_scan()

        self.assertEqual(exit_code, batch_scan.EXIT_UNAUTHORIZED_SESSION)
        joins.assert_not_awaited()
        retry.assert_not_awaited()
        scan.assert_not_awaited()
        self.assertEqual(
            fake_client.calls,
            ["list_handlers", "connect", "authorize", "disconnect"],
        )

    async def test_runtime_failure_still_disconnects(self):
        fake_client = FakeClient()

        with (
            patch.object(batch_scan, "client", fake_client),
            patch.object(
                batch_scan,
                "sync_channel_joins_once",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                batch_scan,
                "retry_pending_notifications",
                new=AsyncMock(side_effect=RuntimeError("outbox unavailable")),
            ),
            patch.object(batch_scan, "scan_today_signals", new=AsyncMock()) as scan,
        ):
            exit_code = await batch_scan.run_batch_scan()

        self.assertEqual(exit_code, batch_scan.EXIT_RUNTIME_ERROR)
        scan.assert_not_awaited()
        self.assertFalse(fake_client.connected)

    async def test_realtime_handlers_are_removed_before_connecting(self):
        calls = []

        def callback():
            return None

        event = object()
        fake_client = FakeClient(calls=calls)
        fake_client.handlers = [(callback, event)]

        with (
            patch.object(batch_scan, "client", fake_client),
            patch.object(
                batch_scan,
                "sync_channel_joins_once",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                batch_scan,
                "retry_pending_notifications",
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                batch_scan,
                "scan_today_signals",
                new=AsyncMock(return_value={}),
            ),
        ):
            exit_code = await batch_scan.run_batch_scan()

        self.assertEqual(exit_code, batch_scan.EXIT_OK)
        self.assertEqual(fake_client.handlers, [])
        self.assertEqual(calls[0:2], ["list_handlers", "connect"])

    async def test_partial_failures_have_a_distinct_exit_code(self):
        cases = {
            "join error": ({"errors": 1}, {}, {}),
            "unresolved channel": ({"unresolved": 1}, {}, {}),
            "retry failure": ({}, {"failed": 1}, {}),
            "scan error": ({}, {}, {"errors": 1}),
            "notification failure": ({}, {}, {"notification_failures": 1}),
        }

        for label, (join_delta, retry_delta, scan_delta) in cases.items():
            with self.subTest(label=label):
                fake_client = FakeClient()
                join_stats = {
                    "channels": 1,
                    "resolved": 0,
                    "unresolved": 0,
                    "errors": 0,
                    **join_delta,
                }
                retry_stats = {
                    "pending": 0,
                    "sent": 0,
                    "failed": 0,
                    **retry_delta,
                }
                scan_stats = {
                    "messages": 0,
                    "new_signals": 0,
                    "duplicates": 0,
                    "notification_failures": 0,
                    "errors": 0,
                    **scan_delta,
                }

                with (
                    patch.object(batch_scan, "client", fake_client),
                    patch.object(
                        batch_scan,
                        "sync_channel_joins_once",
                        new=AsyncMock(return_value=join_stats),
                    ),
                    patch.object(
                        batch_scan,
                        "retry_pending_notifications",
                        new=AsyncMock(return_value=retry_stats),
                    ),
                    patch.object(
                        batch_scan,
                        "scan_today_signals",
                        new=AsyncMock(return_value=scan_stats),
                    ),
                ):
                    exit_code = await batch_scan.run_batch_scan()

                self.assertEqual(exit_code, batch_scan.EXIT_PARTIAL_FAILURE)
                self.assertFalse(fake_client.connected)

    async def test_channel_sync_validates_saved_ids_and_isolates_failures(self):
        channels = [
            {"identifier": "@ready", "chat_id": -1001},
            {"identifier": "@stale", "chat_id": -1002},
            {"identifier": "Text channel"},
            {"identifier": "@broken"},
        ]
        join = AsyncMock(
            side_effect=["Recovered channel", "", RuntimeError("Telegram error")]
        )
        entity_client = SimpleNamespace(
            get_entity=AsyncMock(
                side_effect=[object(), ValueError("missing access hash")]
            )
        )

        with (
            patch.object(batch_scan, "client", entity_client),
            patch.object(batch_scan, "load_channels", return_value=channels),
            patch.object(batch_scan, "join_channel", new=join),
        ):
            stats = await batch_scan.sync_channel_joins_once()

        self.assertEqual(
            stats,
            {
                "channels": 4,
                "already_resolved": 1,
                "resolved": 1,
                "unresolved": 1,
                "errors": 1,
            },
        )
        self.assertEqual(
            [call.args[0]["identifier"] for call in join.await_args_list],
            ["@stale", "Text channel", "@broken"],
        )
        self.assertEqual(
            [call.args[0] for call in entity_client.get_entity.await_args_list],
            [-1001, -1002],
        )


class BatchShellScriptTests(unittest.TestCase):
    def test_shell_runner_is_foreground_and_locked(self):
        script = (
            Path(__file__).resolve().parents[1] / "run_batch_scan.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("flock -n", script)
        self.assertIn('"$SCRIPT_DIR/batch_scan.py"', script)
        self.assertNotIn("noh" + "up ", script)
        self.assertNotIn(" &\n", script)


if __name__ == "__main__":
    unittest.main()
