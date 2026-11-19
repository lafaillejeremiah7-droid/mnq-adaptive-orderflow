import time
import unittest
from unittest.mock import patch

import pump_scanner as p
from company import initial, process


class PumpTests(unittest.TestCase):
    def test_discovery_requires_stage_and_origin(self):
        now = 1000
        row = dict(
            chain_id=p.NETWORK,
            program="pump",
            protocol="pump",
            initialized=True,
            hidden=False,
            is_banned=False,
            nsfw=False,
            complete=False,
            base_decimals=6,
            token_program=next(iter(p.TOKEN_PROGRAMS)),
            transfer_fee_bps=0,
            mint="1" * 32,
            bonding_curve="2" * 32,
            pool_address="3" * 32,
            created_timestamp=now * 1000,
        )
        self.assertIn(row["mint"], p.candidates([row], "launch", now))
        for changes in (
            {"program": "other"},
            {"complete": True},
            {"transfer_hook_program": "hook"},
            {"created_timestamp": 0},
        ):
            self.assertFalse(p.candidates([{**row, **changes}], "launch", now))
        self.assertFalse(p.candidates([row], "graduated", now))
        self.assertIn(
            row["mint"], p.candidates([{**row, "complete": True}], "graduated", now)
        )

    def test_alternate_feed_derives_pump_curve_and_checks_graduation(self):
        mint = "ryBYEgsEQLypy8WuyS5feoxnLCQEgX5gUwwENmUpump"
        curve = "FXhKHkZaWASMJ28ojtQT8ARG9AsqfppnCZfVVujFQTK6"
        row = {
            "id": mint,
            "launchpad": "pump.fun",
            "decimals": 6,
            "tokenProgram": next(iter(p.TOKEN_PROGRAMS)),
            "audit": {"freezeAuthorityDisabled": True},
            "createdAt": "1970-01-01T00:00:10Z",
        }
        with patch.object(
            p, "fetch", side_effect=[ValueError("primary unavailable"), ([row], 12)]
        ):
            found, count, source = p.discover("launch", 12)
        self.assertEqual(
            (found[mint]["bonding_curve"], count, source),
            (curve, 1, "Jupiter Tokens V2"),
        )
        self.assertFalse(p.jupiter_candidates([row], "graduated", 12))
        self.assertFalse(
            p.jupiter_candidates([{**row, "launchpad": "other"}], "launch", 12)
        )
        grad = {**row, "graduatedPool": "1" * 32, "graduatedAt": "1970-01-01T00:00:12Z"}
        self.assertIn(mint, p.jupiter_candidates([grad], "graduated", 13))
        self.assertFalse(p.jupiter_candidates([grad], "launch", 13))

    def test_malformed_jupiter_rows_do_not_abort_discovery(self):
        mint = "ryBYEgsEQLypy8WuyS5feoxnLCQEgX5gUwwENmUpump"
        good = {
            "id": mint,
            "launchpad": "pump.fun",
            "decimals": 6,
            "tokenProgram": next(iter(p.TOKEN_PROGRAMS)),
            "audit": {"freezeAuthorityDisabled": True},
            "createdAt": "1970-01-01T00:00:10Z",
        }
        broken = [
            None,
            [],
            {**good, "id": None},
            {**good, "audit": None},
            {**good, "tokenProgram": []},
            {**good, "createdAt": 10},
            {**good, "createdAt": "not a date"},
            {**good, "createdAt": "1970-01-01T00:00:10"},
            {**good, "graduatedPool": ["bad"]},
        ]
        expected = p.jupiter_candidates([good], "launch", 12)
        self.assertEqual(
            p.jupiter_candidates([*broken, good], "launch", 12), expected
        )
        graduate = {**good, "graduatedPool": "1" * 32, "graduatedAt": "ok"}
        bad_graduates = [
            {**graduate, "graduatedPool": []},
            {**graduate, "graduatedAt": 100},
            {**graduate, "audit": []},
        ]
        self.assertEqual(
            p.jupiter_candidates([*bad_graduates, graduate], "graduated", 12),
            p.jupiter_candidates([graduate], "graduated", 12),
        )

    def test_orphaned_position_is_reported_stale(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            with (
                patch.object(p, "discover", return_value=({}, 0, "test")),
                patch.object(
                    p, "account_report",
                    return_value={"position": {"asset": "unlisted-mint"}},
                ),
            ):
                _, report = p.scan(Path(temporary), "launch", 1000)
            self.assertTrue(report["position_mark_stale"])
            self.assertIn("position_quote_unavailable", report)

    def test_reject_wrong_pool_and_split(self):
        meta = {"pool_address": "pool", "bonding_curve": "curve"}
        step = {
            "label": "Pump.fun Amm",
            "ammKey": "pool",
            "inputMint": "SOL",
            "outputMint": "m",
        }
        response = dict(
            inputMint=p.USDC,
            outputMint="m",
            inAmount="10",
            swapMode="ExactIn",
            slippageBps=30,
            otherAmountThreshold="5",
            outAmount="6",
            contextSlot=10,
            routePlan=[{"swapInfo": step}],
        )
        with patch.object(p, "fetch", return_value=(response, 4)):
            self.assertEqual(
                p.leg(p.USDC, "m", 10, "m", meta, ("graduated",)), (5, 10, 4)
            )
            with self.assertRaises(ValueError):
                p.leg(p.USDC, "m", 10, "m", meta, ("launch",))
            response["routePlan"].append({"swapInfo": {**step, "ammKey": "wrong"}})
            with self.assertRaises(ValueError):
                p.leg(p.USDC, "m", 10, "m", meta, ("graduated",))

    def test_buy_needs_sell_quote_and_new_slot(self):
        stamp = int(time.time())
        with patch.object(
            p, "leg", side_effect=[(99, 90, stamp), ValueError("no exit")]
        ):
            with self.assertRaises(ValueError):
                p.quote("m", {}, "launch", None)
        with patch.object(p, "leg", side_effect=[(99, 90, stamp), (88, 91, stamp)]):
            with self.assertRaises(ValueError):
                p.quote("m", {"last_slot": 90}, "launch", None)

    def test_held_launch_can_sell_on_graduation(self):
        now = int(time.time())
        pos = {"asset": "m", "qty": "2", "entry": "1"}
        cfg = dict(p.CONFIG, tokens={"m": 6}, signal_horizon_seconds=120)
        s = initial(cfg)
        s.update(position=pos, pending={"asset": "m", "side": "sell", "ts": now - 20})
        with patch.object(p, "leg", return_value=(2200000, 91, now)) as leg:
            _, q = p.quote("m", {}, "launch", pos)
        self.assertEqual(
            leg.call_args.args, ("m", p.USDC, 2000000, "m", {}, ("launch", "graduated"))
        )
        event = process(s, q, cfg, now, live=True)
        self.assertEqual(event["action"], "paper_sell")
        self.assertIsNone(event["ask"])
        self.assertIsNone(s["position"])
        self.assertIsNone(s["pending"])
