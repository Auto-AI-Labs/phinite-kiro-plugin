"""Offline tests for hooks/env_guard.py, the hook that keeps .env values out of the chat.

    python -m unittest tests/test_env_guard.py
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

GUARD = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "env_guard.py"


def load():
    spec = importlib.util.spec_from_file_location("env_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(GUARD.is_file(), "this plugin has no hooks/env_guard.py")
class EnvGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load()

    def blocked(self, command):
        return self.g.check_command(command) is not None

    def test_commands_that_print_values_are_blocked(self):
        for cmd in ["cat .env", "cat /work/.env", "head -n 5 ./.env", "tail .env.local", "less .env",
                    "grep API_KEY .env", "rg TOKEN .env.production", "sed -n p .env", "awk '{print}' .env",
                    "cat .env | head", "sudo cat .env", "env FOO=1 cat .env", "cut -d= -f2 .env",
                    "python3 -c \"print(open('.env').read())\"", "node -e \"console.log(require('fs')"
                    ".readFileSync('.env','utf8'))\"", "bash -c 'cat .env'", "source .env && printenv",
                    ". ./.env; echo $SECRET", "Get-Content .env", "type .env", "cat .env*", "base64 .env",
                    "while read l; do echo $l; done < .env", "cat config/app.env"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd), cmd)

    def test_names_only_and_normal_work_are_allowed(self):
        for cmd in ["cut -d= -f1 .env", "awk -F= '{print $1}' .env", "sed 's/=.*//' .env",
                    "grep -c . .env", "grep -q '^API_KEY=' .env", "grep -o '^[^=]*' .env", "wc -l .env",
                    "ls -la", "ls -a .env", "test -f .env", "echo 'API_KEY=x' >> .env", "printf 'A=1\\n' > .env",
                    "cp .env.example .env", "cat .env.example", "cat .env.sample", "git status",
                    "python3 app.py --env-file .env", "docker compose --env-file .env up -d",
                    "python3 skills/phinite-project/scripts/phinite_project.py env-check ./uc",
                    "set -a; . ./.env; set +a; python3 app.py", "npm run dev", "cat README.md",
                    "grep -r env src/", "cat environment.yml"]:
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd), cmd)

    def test_file_reads_of_a_dotenv_are_blocked_but_writes_are_not(self):
        read = {"tool_name": "Read", "tool_input": {"file_path": "/work/.env"}}
        self.assertIsNotNone(self.g.decide(read))
        self.assertIsNone(self.g.decide({"tool_name": "Read", "tool_input": {"file_path": "/work/.env.example"}}))
        self.assertIsNone(self.g.decide({"tool_name": "Write", "tool_input": {"file_path": "/work/.env"}}))
        self.assertIsNone(self.g.decide({"tool_name": "Read", "tool_input": {"file_path": "/work/app.py"}}))

    def test_every_client_payload_shape(self):
        shapes = [
            {"tool_name": "Bash", "tool_input": {"command": "cat .env"}},                    # Claude, Codex
            {"tool_name": "Execute", "tool_input": {"command": "cat .env"}},                 # Factory
            {"tool_name": "exec", "tool_input": {"command": "cat .env"}},                    # Devin
            {"file_path": "/w/.env", "content": "A=1"},                                        # Cursor read
            {"command": "cat .env", "cwd": "/w"},                                              # Cursor shell
            {"toolName": "view", "toolArgs": json.dumps({"path": "/w/.env"})},                # Copilot
            {"toolName": "bash", "toolArgs": {"command": "cat .env"}},                         # Copilot
            {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/w/.env"}}},         # Antigravity
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "cat .env"}}},       # Antigravity
            {"tool_name": "read", "tool_input": {"filePath": "/w/.env"}},                     # OpenCode
        ]
        for event in shapes:
            with self.subTest(event=event):
                self.assertIsNotNone(self.g.decide(event))

    def run_guard(self, client, event, env=None):
        import os
        p = subprocess.run([sys.executable, str(GUARD), "--client", client], input=json.dumps(event),
                           capture_output=True, text=True, env=dict(os.environ, **(env or {})))
        return p.returncode, p.stdout, p.stderr

    def test_how_each_client_is_told(self):
        bad = {"tool_name": "Bash", "tool_input": {"command": "cat .env"}}
        good = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        code, out, err = self.run_guard("claude", bad)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cut -d= -f1", err)
        self.assertEqual(self.run_guard("claude", good)[:2], (0, ""))
        code, out, _ = self.run_guard("cursor", bad)
        self.assertEqual((code, json.loads(out)["permission"]), (0, "deny"))
        self.assertEqual(json.loads(self.run_guard("cursor", good)[1]), {"permission": "allow"})
        code, out, _ = self.run_guard("copilot", bad)
        self.assertEqual((code, json.loads(out)["permissionDecision"]), (2, "deny"))
        code, out, _ = self.run_guard("antigravity", bad)
        self.assertEqual((code, json.loads(out)["decision"]), (0, "deny"))
        self.assertEqual(self.run_guard("claude", bad, {"PHINITE_ALLOW_ENV_READ": "1"})[0], 0)

    def test_odd_input_never_blocks(self):
        for raw in ["", "not json", "[]", '{"tool_input": 5}']:
            p = subprocess.run([sys.executable, str(GUARD)], input=raw, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, raw)


if __name__ == "__main__":
    unittest.main()
