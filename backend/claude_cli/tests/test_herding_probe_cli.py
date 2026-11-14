"""CLI flags for the randomized herding probe on run / start, and what step_start sends."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402


class HerdingProbeFlagTests(unittest.TestCase):
    def arg(self, *extra):
        return mirofish.herding_probe_arg(mirofish.build_parser().parse_args(["start", "--simulation", "s", *extra]))

    def test_flags(self):
        self.assertIsNone(self.arg())
        self.assertEqual(self.arg("--herding-probe"), {"share": 0.5})
        self.assertEqual(self.arg("--herding-probe", "0.3", "--herding-probe-seed", "9"), {"share": 0.3, "seed": 9})
        self.assertIs(self.arg("--herding-probe", "0"), False)
        with self.assertRaises(mirofish.CLIError):
            self.arg("--herding-probe", "1.2")
        with self.assertRaises(mirofish.CLIError):
            self.arg("--herding-probe-seed", "4")
        run = mirofish.build_parser().parse_args(["run", "--seed", "a.md", "--requirement", "q", "--herding-probe", "0.4"])
        self.assertEqual(mirofish.herding_probe_arg(run), {"share": 0.4})

    def test_step_start_sends_the_probe_only_when_given(self):
        sent = []

        class Client:
            def data(self, method, path, json=None, timeout=None):
                sent.append(json)
                return {"runner_status": "running", **({"herding_probe": json["herding_probe"]} if "herding_probe" in json else {})}

        mirofish.step_start(Client(), "sim_x", wait=False)
        mirofish.step_start(Client(), "sim_x", wait=False, herding_probe={"share": 0.5})
        mirofish.step_start(Client(), "sim_x", wait=False, herding_probe=False)
        self.assertNotIn("herding_probe", sent[0])
        self.assertEqual(sent[1]["herding_probe"], {"share": 0.5})
        self.assertIs(sent[2]["herding_probe"], False)


if __name__ == "__main__":
    unittest.main()
