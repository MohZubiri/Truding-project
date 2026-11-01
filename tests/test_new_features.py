import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import main
import processed_messages_store
import signals_store
from schedule_utils import next_scan_at, parse_scan_times, start_of_today_utc
from trade_analyzer import analyze_trade


class TradeAnalyzerTests(unittest.TestCase):
    def test_calculates_profit_risk_and_ratio(self):
        signal = {
            "entry": [100, 110],
            "targets": [120, 130],
            "stop_loss": 95,
        }
        result = analyze_trade(signal, current_price=108)

        self.assertEqual(result["reference_entry"], 105.0)
        self.assertEqual(result["risk_percent"], 9.52)
        self.assertEqual(result["targets"][0]["profit_percent"], 14.29)
        self.assertEqual(result["targets"][0]["risk_reward"], 1.5)

    def test_uses_current_price_when_entry_is_missing(self):
        result = analyze_trade(
            {"entry": [], "targets": [210], "stop_loss": 190},
            current_price=200,
        )
        self.assertEqual(result["reference_entry"], 200)
        self.assertTrue(result["warnings"])


class ScheduleTests(unittest.TestCase):
    def test_next_scan_uses_riyadh_time(self):
        scan_times = parse_scan_times(["08:00", "14:00", "20:00"])
        now = datetime(2026, 11, 1, 9, 30, tzinfo=ZoneInfo("Asia/Riyadh"))
        next_run = next_scan_at(scan_times, "Asia/Riyadh", now)
        self.assertEqual(next_run.hour, 14)
        self.assertEqual(next_run.date(), now.date())

    def test_day_start_is_converted_to_utc(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
        start = start_of_today_utc("Asia/Riyadh", now)
        self.assertEqual(start, datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc))


class StorageDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_signals_file = signals_store.SIGNALS_FILE
        self.old_processed_file = processed_messages_store.PROCESSED_MESSAGES_FILE
        signals_store.SIGNALS_FILE = os.path.join(self.temp_dir.name, "signals.json")
        processed_messages_store.PROCESSED_MESSAGES_FILE = os.path.join(
            self.temp_dir.name, "processed_messages.json"
        )

    def tearDown(self):
        signals_store.SIGNALS_FILE = self.old_signals_file
        processed_messages_store.PROCESSED_MESSAGES_FILE = self.old_processed_file
        self.temp_dir.cleanup()

    def test_same_telegram_message_is_saved_once(self):
        signal = {
            "coin": "BTC",
            "pair": "BTC/USDT",
            "entry": [100],
            "targets": [110],
            "stop_loss": 95,
            "raw_text": "BTC/USDT Entry 100 TP1 110 SL 95",
        }
        halal = {"is_halal": True, "status": "مباحة"}

        first, first_created = signals_store.save_signal_once(
            signal, halal, "@channel", source_chat_id=-1001, source_message_id=77
        )
        second, second_created = signals_store.save_signal_once(
            signal, halal, "@channel", source_chat_id=-1001, source_message_id=77
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(signals_store.load_signals()), 1)

        updated = signals_store.update_signal(first["id"], telegram_sent=True)
        self.assertTrue(updated["telegram_sent"])
        self.assertTrue(signals_store.load_signals()[0]["telegram_sent"])

    def test_processed_message_ledger(self):
        key = processed_messages_store.build_message_key(-1001, 88)
        self.assertFalse(processed_messages_store.is_message_processed(key))
        processed_messages_store.mark_message_processed(key)
        self.assertTrue(processed_messages_store.is_message_processed(key))


class ProcessingPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_signals_file = signals_store.SIGNALS_FILE
        self.old_processed_file = processed_messages_store.PROCESSED_MESSAGES_FILE
        signals_store.SIGNALS_FILE = os.path.join(self.temp_dir.name, "signals.json")
        processed_messages_store.PROCESSED_MESSAGES_FILE = os.path.join(
            self.temp_dir.name, "processed_messages.json"
        )

    def tearDown(self):
        signals_store.SIGNALS_FILE = self.old_signals_file
        processed_messages_store.PROCESSED_MESSAGES_FILE = self.old_processed_file
        self.temp_dir.cleanup()

    async def test_approved_message_is_not_notified_twice(self):
        message = "BTC/USDT Entry: 100 TP1: 110 SL: 95"
        halal = {
            "is_halal": True,
            "status": "مباحة",
            "notes": "اختبار",
            "verified_by": "اختبار",
        }
        with (
            patch.object(main, "verify_coin", new=AsyncMock(return_value=halal)),
            patch.object(main, "get_binance_spot_price", return_value=101.0),
            patch.object(main, "send_telegram_alert", return_value=True) as telegram,
        ):
            first = await main.process_signal_message(
                message,
                "@channel",
                source_chat_id=-1001,
                source_message_id=99,
                message_date=datetime.now(timezone.utc),
            )
            second = await main.process_signal_message(
                message,
                "@channel",
                source_chat_id=-1001,
                source_message_id=99,
                message_date=datetime.now(timezone.utc),
            )

        self.assertEqual(first["status"], "approved")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(telegram.call_count, 1)
        self.assertTrue(signals_store.load_signals()[0]["telegram_sent"])

    async def test_failed_notification_is_retried_on_next_scan(self):
        message = "ETH/USDT Entry: 2000 TP1: 2200 SL: 1900"
        halal = {
            "is_halal": True,
            "status": "مباحة",
            "notes": "اختبار",
            "verified_by": "اختبار",
        }
        with (
            patch.object(main, "verify_coin", new=AsyncMock(return_value=halal)),
            patch.object(main, "get_binance_spot_price", return_value=2010.0),
            patch.object(
                main,
                "send_telegram_alert",
                side_effect=[False, True],
            ) as telegram,
        ):
            first = await main.process_signal_message(
                message, "@channel", -1001, 100, datetime.now(timezone.utc)
            )
            second = await main.process_signal_message(
                message, "@channel", -1001, 100, datetime.now(timezone.utc)
            )

        self.assertEqual(first["delivery"]["telegram"], "failed")
        self.assertEqual(second["delivery"]["telegram"], "sent")
        self.assertEqual(telegram.call_count, 2)
        self.assertTrue(signals_store.load_signals()[0]["telegram_sent"])

    async def test_daily_scan_streams_today_messages_oldest_first(self):
        threshold = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)
        messages = [
            SimpleNamespace(
                id=1,
                message="BTC/USDT Entry: 100 TP1: 110",
                date=datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=2,
                message="ETH/USDT Entry: 2000 TP1: 2200",
                date=datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc),
            ),
        ]

        class FakeClient:
            def __init__(self):
                self.iter_kwargs = None

            async def get_entity(self, identifier):
                return SimpleNamespace(username="channel", title="Channel")

            def iter_messages(self, entity, **kwargs):
                self.iter_kwargs = kwargs

                async def generate():
                    for message in messages:
                        yield message

                return generate()

        fake_client = FakeClient()
        process = AsyncMock(
            side_effect=[
                {"status": "approved", "delivery": {"telegram": "failed"}},
                {"status": "approved", "delivery": {"telegram": "sent"}},
            ]
        )
        main._daily_scan_running = False
        with (
            patch.object(main, "client", fake_client),
            patch.object(main, "load_channels", return_value=[{"identifier": "@channel"}]),
            patch.object(main, "get_peer_id", return_value=-1001),
            patch.object(main, "start_of_today_utc", return_value=threshold),
            patch.object(main, "process_signal_message", new=process),
        ):
            stats = await main.scan_today_signals()

        self.assertEqual(stats["messages"], 2)
        self.assertEqual(stats["new_signals"], 2)
        self.assertEqual(stats["notification_failures"], 1)
        self.assertEqual([call.kwargs["source_message_id"] for call in process.await_args_list], [1, 2])
        self.assertTrue(fake_client.iter_kwargs["reverse"])
        self.assertEqual(fake_client.iter_kwargs["offset_date"], threshold)

    async def test_daily_scan_falls_back_to_identifier_when_chat_id_is_uncached(self):
        threshold = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)

        class FakeClient:
            def __init__(self):
                self.lookups = []

            async def get_entity(self, identifier):
                self.lookups.append(identifier)
                if identifier == -1001:
                    raise ValueError("Could not find the input entity")
                return SimpleNamespace(username="channel", title="Channel")

            def iter_messages(self, entity, **kwargs):
                async def generate():
                    if False:
                        yield None

                return generate()

        fake_client = FakeClient()
        main._daily_scan_running = False
        with (
            patch.object(main, "client", fake_client),
            patch.object(
                main,
                "load_channels",
                return_value=[{"identifier": "@channel", "chat_id": -1001}],
            ),
            patch.object(main, "get_peer_id", return_value=-1001),
            patch.object(main, "start_of_today_utc", return_value=threshold),
        ):
            stats = await main.scan_today_signals()

        self.assertEqual(fake_client.lookups, [-1001, "@channel"])
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["notification_failures"], 0)


if __name__ == "__main__":
    unittest.main()
