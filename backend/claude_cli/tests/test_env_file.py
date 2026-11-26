"""The CLI API token: an explicit --env-file is used alone; otherwise MIROFISH_ENV_FILE, then the repository .env."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mirofish  # noqa: E402

TOKEN_REPO = "t0k3n-" + "a" * 40
TOKEN_INSTANCE = "t0k3n-" + "b" * 40
TOKEN_EXPLICIT = "t0k3n-" + "c" * 40


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TokenLookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.repo_env = os.path.join(root, ".env")
        _write(self.repo_env, f"MM_API_AUTH_TOKEN={TOKEN_REPO}\n")
        self.instance_env = os.path.join(root, ".env.codex")
        _write(self.instance_env, f'# second backend\nexport API_AUTH_TOKEN="{TOKEN_INSTANCE}"\n')
        self.explicit_env = os.path.join(root, ".env.explicit")
        _write(self.explicit_env, f"API_AUTH_TOKEN={TOKEN_EXPLICIT}\n")
        self.missing_env = os.path.join(root, "missing.env")
        self.token_free_env = os.path.join(root, ".env.no-token")
        _write(self.token_free_env, "# no token in this file\nLLM_POOL=claude_code:sonnet\n")
        self.commented_env = os.path.join(root, ".env.commented")
        _write(self.commented_env, "MM_API_AUTH_TOKEN=inline-token # instance backend\n")
        self.quoted_hash_env = os.path.join(root, ".env.quoted-hash")
        _write(self.quoted_hash_env, 'MM_API_AUTH_TOKEN="tok#en" # trailing comment\n')

        self.saved_tokens = {key: os.environ.pop(key, None) for key in mirofish.TOKEN_ENV_KEYS}
        self.saved_mirofish = os.environ.pop("MIROFISH_ENV_FILE", None)
        self.old_repo = mirofish.REPO_ENV_FILE
        self.old_cli = mirofish.CLI_ENV_FILE
        mirofish.REPO_ENV_FILE = self.repo_env
        mirofish.CLI_ENV_FILE = None

    def tearDown(self):
        mirofish.REPO_ENV_FILE = self.old_repo
        mirofish.CLI_ENV_FILE = self.old_cli
        for key, value in self.saved_tokens.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self.saved_mirofish is None:
            os.environ.pop("MIROFISH_ENV_FILE", None)
        else:
            os.environ["MIROFISH_ENV_FILE"] = self.saved_mirofish
        self.tmp.cleanup()

    def test_mirofish_env_file_wins_over_the_repo_env(self):
        os.environ["MIROFISH_ENV_FILE"] = self.instance_env
        self.assertEqual(mirofish.api_token(), TOKEN_INSTANCE)
        client = mirofish.Client("http://127.0.0.1:1")
        self.assertEqual(client.session.headers["Authorization"], f"Bearer {TOKEN_INSTANCE}")

    def test_missing_mirofish_env_file_falls_back_to_the_repo_env(self):
        os.environ["MIROFISH_ENV_FILE"] = self.missing_env
        self.assertEqual(mirofish.api_token(), TOKEN_REPO)

    def test_explicit_env_file_wins_over_both_files(self):
        os.environ["MIROFISH_ENV_FILE"] = self.instance_env
        self.assertEqual(mirofish.api_token(self.explicit_env), TOKEN_EXPLICIT)
        mirofish.CLI_ENV_FILE = self.explicit_env
        self.assertEqual(mirofish.api_token(), TOKEN_EXPLICIT)

    def test_missing_cli_env_file_does_not_fall_back(self):
        os.environ["MIROFISH_ENV_FILE"] = self.instance_env
        mirofish.CLI_ENV_FILE = self.missing_env
        self.assertEqual(mirofish.api_token(), "")

    def test_token_free_cli_env_file_does_not_fall_back(self):
        os.environ["MIROFISH_ENV_FILE"] = self.instance_env
        mirofish.CLI_ENV_FILE = self.token_free_env
        self.assertEqual(mirofish.api_token(), "")
        client = mirofish.Client("http://127.0.0.1:1")
        self.assertNotIn("Authorization", client.session.headers)

    def test_inline_comments_are_not_part_of_the_token(self):
        mirofish.CLI_ENV_FILE = self.commented_env
        self.assertEqual(mirofish.api_token(), "inline-token")
        self.assertEqual(mirofish.api_token(self.commented_env), "inline-token")

    def test_a_hash_inside_quotes_stays_part_of_the_token(self):
        mirofish.CLI_ENV_FILE = self.quoted_hash_env
        self.assertEqual(mirofish.api_token(), "tok#en")

    def test_the_environment_wins_over_every_file(self):
        os.environ["MIROFISH_ENV_FILE"] = self.instance_env
        os.environ["MM_API_AUTH_TOKEN"] = "from-env"
        self.assertEqual(mirofish.api_token(), "from-env")

    def test_env_file_option_is_global_and_reaches_the_client(self):
        self.assertEqual(mirofish.build_parser().parse_args(["--env-file", "x.env", "health"]).env_file, "x.env")
        self.assertEqual(mirofish.build_parser().parse_args(["health", "--env-file", "x.env"]).env_file, "x.env")

        seen = {}

        class FakeClient:
            def __init__(self, base_url, timeout=60, lang="en", token=None):
                seen["token"] = mirofish.api_token()

            def get(self, path, **kwargs):
                return {"status": "ok", "path": path}

        with patch.object(mirofish, "Client", FakeClient), redirect_stdout(io.StringIO()):
            self.assertEqual(mirofish.main(["--env-file", self.explicit_env, "health"]), 0)
        self.assertEqual(seen["token"], TOKEN_EXPLICIT)


if __name__ == "__main__":
    unittest.main()
