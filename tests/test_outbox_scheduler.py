import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import main
import processed_messages_store
import signals_store
from schedule_utils import resolve_timezone_name


class FeatureFilesMixin:
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_signals_file = signals_store.SIGNALS_FILE
        self.old_processed_file = processed_messages_store.PROCESSED_MESSAGES_FILE
        signals_store.SIGNALS_FILE = os.path.join(self.temp_dir.name, "signals.json")
        processed_messages_store.PROCESSED_MESSAGES_FILE = os.path.join(
            self.temp_dir.name, "processed_messages.json"
        )
        main._processing_keys.clear()
        main._daily_scan_running = False

    def tearDown(self):
        signals_store.SIGNALS_FILE = self.old_signals_file
        processed_messages_store.PROCESSED_MESSAGES_FILE = self.old_processed_file
        self.temp_dir.cleanup()


class SchedulerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_timezone_falls_back_to_riyadh(self):
        self.assertEqual(
            resolve_timezone_name("Invalid/Timezone"),
            "Asia/Riyadh",
        )

    async def test_startup_service_scans_once_then_starts_scheduler(self):
        with (
            patch.object(main, "scan_today_signals", new=AsyncMock(return_value={})) as scan,
            patch.object(main, "daily_scan_scheduler", new=AsyncMock()) as scheduler,
        ):
            await main.daily_scan_service()
        scan.assert_awaited_once()
        scheduler.assert_awaited_once()


class OutboxAndVerdictTests(FeatureFilesMixin, unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _signal(coin="BTC"):
        return {
            "coin": coin,
            "pair": f"{coin}/USDT",
            "entry": [100],
            "targets": [110],
            "stop_loss": 95,
            "raw_text": f"{coin}/USDT Entry: 100 TP1: 110 SL: 95",
        }

    async def test_outbox_retries_without_rescanning_telegram(self):
        record, _ = signals_store.save_signal_once(
            self._signal(),
            {"is_halal": True, "status": "مباحة"},
            "@channel",
            source_chat_id=-1001,
            source_message_id=1,
            telegram_required=True,
        )
        self.assertFalse(record["telegram_sent"])

        with (
            patch.object(main, "send_telegram_alert", return_value=True) as send,
        ):
            stats = await main.retry_pending_notifications()

        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["sent"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(signals_store.load_signals()[0]["telegram_sent"])

    async def test_delivery_lock_prevents_two_workers_sending_same_record(self):
        record, _ = signals_store.save_signal_once(
            self._signal(),
            {"is_halal": True, "status": "مباحة"},
            "@channel",
            source_chat_id=-1001,
            source_message_id=11,
            telegram_required=True,
        )
        with (
            patch.object(main, "send_telegram_alert", return_value=True) as send,
        ):
            await asyncio.gather(
                main.deliver_trade_notifications(dict(record)),
                main.deliver_trade_notifications(dict(record)),
            )
        self.assertEqual(send.call_count, 1)

    def test_legacy_firebase_only_record_is_not_pending(self):
        signals_store._write_signals_unlocked([{
            "id": "legacy-firebase",
            "telegram_required": False,
            "firebase_required": True,
            "firebase_sent": False,
        }])
        self.assertEqual(signals_store.load_pending_signals(), [])

    def test_legacy_records_are_not_replayed_as_pending(self):
        signals_store._write_signals_unlocked([{
            "id": "legacy",
            "is_halal": True,
            "pair": "BTC/USDT",
        }])
        self.assertEqual(signals_store.load_pending_signals(), [])

    async def test_processed_key_without_record_is_not_reprocessed(self):
        key = processed_messages_store.build_message_key(-1001, 2)
        processed_messages_store.mark_message_processed(key)
        halal = {
            "is_halal": True,
            "status": "مباحة",
            "notes": "اختبار",
            "verified_by": "اختبار",
        }
        with (
            patch.object(
                main,
                "verify_coin",
                new=AsyncMock(return_value=halal),
            ) as verify,
            patch.object(main, "get_binance_spot_price", return_value=101),
            patch.object(main, "send_telegram_alert", return_value=True) as send,
        ):
            result = await main.process_signal_message(
                self._signal()["raw_text"],
                "@channel",
                -1001,
                2,
                datetime.now(timezone.utc),
            )

        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(len(signals_store.load_signals()), 0)
        verify.assert_not_awaited()
        send.assert_not_called()

    async def test_unresolved_verdict_is_rechecked_and_updated_to_halal(self):
        unresolved = {
            "is_halal": False,
            "status": "غير محسومة",
            "notes": "انتهت المهلة",
            "verified_by": "@checker",
        }
        halal = {
            "is_halal": True,
            "status": "مباحة",
            "notes": "تم التحقق",
            "verified_by": "@checker",
        }
        key = processed_messages_store.build_message_key(-1001, 3)
        verify = AsyncMock(side_effect=[unresolved, halal])
        with (
            patch.object(main, "verify_coin", new=verify),
            patch.object(main, "get_binance_spot_price", return_value=101),
            patch.object(main, "send_telegram_alert", return_value=True) as send,
        ):
            first = await main.process_signal_message(
                self._signal("ETH")["raw_text"], "@channel", -1001, 3,
                datetime.now(timezone.utc),
            )
            self.assertFalse(processed_messages_store.is_message_processed(key))
            second = await main.process_signal_message(
                self._signal("ETH")["raw_text"], "@channel", -1001, 3,
                datetime.now(timezone.utc),
            )

        records = signals_store.load_signals()
        self.assertEqual(first["record"]["halal_status"], "غير محسومة")
        self.assertEqual(second["status"], "approved")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["halal_status"], "مباحة")
        self.assertTrue(processed_messages_store.is_message_processed(key))
        self.assertEqual(verify.await_count, 2)
        self.assertEqual(send.call_count, 1)

    def test_pending_record_is_retained_beyond_recent_limit(self):
        records = [
            {
                "id": str(index),
                "telegram_required": False,
            }
            for index in range(signals_store.MAX_SIGNALS)
        ]
        records.append({
            "id": "pending",
            "telegram_required": True,
            "telegram_sent": False,
        })
        signals_store._write_signals_unlocked(records)
        stored = signals_store.load_signals()
        self.assertEqual(len(stored), signals_store.MAX_SIGNALS + 1)
        self.assertEqual(stored[-1]["id"], "pending")


if __name__ == "__main__":
    unittest.main()
