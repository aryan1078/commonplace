"""The CLI's demo and shell commands against the in-process stack."""

import asyncio

from collab_client.client import CollabClient
from collab_client.demo import run_demo
from collab_client.shell import Shell
from stack import running_stack


def test_demo_runs_every_step(capsys):
    async def main():
        async with running_stack() as stack:
            return await run_demo(stack.gateway)

    assert asyncio.run(main()) == 0
    out = capsys.readouterr().out
    for expected in ("INVALID_CREDENTIALS", "after 2 attempt(s)", "identical: True", "'i' -> 'I'",
                     "Summary:", "The document does not say.", "closed: UNAUTHENTICATED",
                     "old token -> UNAUTHENTICATED", "agree: True"):
        assert expected in out, expected


def test_shell_commands(capsys):
    async def main():
        async with running_stack() as stack:
            async with CollabClient(stack.gateway) as client:
                await client.login("alice", "alice123")
                shell = Shell(client)
                for line in ["open notes", "append so i went home.", "insert 0 Hi! ", "delete 0 3",
                             "cursor 2 5", "show", "history", "who", "docs", "grammar", "accept 1",
                             "enhance 0 5 formal", "summarize short", "complete", "ask Where did I go?"]:
                    assert await shell.run_command(line), line
                text = shell.view.text
                assert not await shell.run_command("logout")
                await shell.view.close()
                return text

    assert asyncio.run(main()) == "so I went home."
    out = capsys.readouterr().out
    assert "alice (you)" in out and "notes" in out and "'i' -> 'I'" in out and "so i went home." in out
