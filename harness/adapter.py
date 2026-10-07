"""Adapter: provider-backed agent loop around the Orchestrator.

No HTTP calls, API keys, or shell tools in this module.
The caller supplies a client object that implements send(system_prompt, messages).
"""

from typing import Any

from harness.orchestrator import Orchestrator


class RunResult:
    """Result class for Adapter.run()."""

    def __init__(
        self,
        messages: list[dict[str, Any]],
        completed: bool,
        turn_limit_reached: bool,
    ):
        self.messages = messages
        self.completed = completed
        self.turn_limit_reached = turn_limit_reached


class Adapter:
    def __init__(self, orchestrator: Orchestrator, client, max_turns: int = 50):
        self.orch = orchestrator
        self.client = client
        self.max_turns = max_turns
        self.messages: list[dict[str, Any]] = []
        self.system_prompt: str | None = None

    def run(self, system_prompt: str, task_prompt: str) -> RunResult:
        self.system_prompt = system_prompt
        self.messages = [{"role": "user", "content": task_prompt}]

        completed = False
        turn_limit_reached = False

        for _ in range(self.max_turns):
            response = self.client.send(self.system_prompt, self.messages)

            if not response.tool_uses:
                self.messages.append(
                    {"role": "assistant", "content": response.text or ""}
                )
                completed = True
                break

            assistant_content = []
            for tu in response.tool_uses:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                )
            self.messages.append(
                {"role": "assistant", "content": assistant_content}
            )

            tool_results = []
            pause_triggered_this_turn = False

            for tu in response.tool_uses:
                if pause_triggered_this_turn:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": "not executed because requirements changed",
                            "is_error": True,
                        }
                    )
                    continue

                was_paused = self.orch.pause_injected
                result = self.orch.run_step(tu["name"], **tu["input"])
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": str(result),
                    }
                )

                if not was_paused and self.orch.pause_injected:
                    pause_triggered_this_turn = True

            user_content: list[dict[str, Any]] = tool_results.copy()
            if pause_triggered_this_turn:
                user_content.append(
                    {"type": "text", "text": self.orch.change_event}
                )

            self.messages.append({"role": "user", "content": user_content})

        else:
            turn_limit_reached = True

        return RunResult(
            messages=self.messages,
            completed=completed,
            turn_limit_reached=turn_limit_reached,
        )
