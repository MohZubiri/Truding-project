import unittest
from unittest.mock import patch

import requests

import main


class TelegramAlertSecurityTests(unittest.TestCase):
    def test_network_error_does_not_log_bot_token_or_request_url(self):
        secret = "SECRET_BOT_TOKEN"
        error = requests.ConnectionError(
            f"https://api.telegram.org/bot{secret}/sendMessage"
        )
        with (
            patch.object(main.requests, "post", side_effect=error),
            patch.object(main.logger, "error") as log_error,
        ):
            sent = main.send_telegram_alert("test")

        self.assertFalse(sent)
        logged = " ".join(
            str(value)
            for call in log_error.call_args_list
            for value in (*call.args, *call.kwargs.values())
        )
        self.assertNotIn(secret, logged)
        self.assertNotIn("api.telegram.org", logged)


if __name__ == "__main__":
    unittest.main()
