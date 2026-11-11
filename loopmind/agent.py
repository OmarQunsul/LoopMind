from litellm import completion, completion_cost
import os
import json
import logging

logger = logging.getLogger(__name__)

class Agent:
    def __init__(self, model, system, prompt=None, connectors=[], events=None, json=False,
                 input_cost_per_token=None, output_cost_per_token=None):
        self.model = model
        self.tools = []
        self.events = events
        self.connectors = connectors
        if prompt:
            self.messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        else:
            self.messages = [{"role": "system", "content": system}]
        self.json = json
        self.recent_tool_calls = []

        # Cost / usage tracking
        self.total_cost = 0.0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.call_count = 0
        # Optional custom pricing (useful for local models like LM Studio)
        self.input_cost_per_token = input_cost_per_token
        self.output_cost_per_token = output_cost_per_token

    def _track_cost(self, response):
        """Accumulate usage + cost from a completion response and print a debug line."""
        self.call_count += 1

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

        call_cost = 0.0
        try:
            if self.input_cost_per_token is not None or self.output_cost_per_token is not None:
                # Custom pricing override
                call_cost = (
                    prompt_tokens * (self.input_cost_per_token or 0)
                    + completion_tokens * (self.output_cost_per_token or 0)
                )
            else:
                call_cost = completion_cost(completion_response=response) or 0.0
        except Exception as e:
            # Unknown model pricing (e.g. LM Studio) -> treat as 0
            logger.debug(f"Could not compute cost for model {self.model}: {e}")

        self.total_cost += call_cost

        print(
            f"[DEBUG][cost] call #{self.call_count} | "
            f"tokens: {prompt_tokens} in / {completion_tokens} out | "
            f"call cost: ${call_cost:.6f} | "
            f"total cost: ${self.total_cost:.6f} "
            f"({self.total_prompt_tokens} in / {self.total_completion_tokens} out)"
        )

    def user(self, message):
        self.messages.append({"role": "user", "content": message})

    async def loadTools(self):
        for connector in self.connectors:
            self.tools = self.tools + await connector.get_tools()

    async def execute_tool_call(self, tool_name, arguments):
        for connector in self.connectors:
            if tool_name in await connector.tool_names():
                data = await connector.call_tool(tool_name, arguments)
                return json.dumps(data, ensure_ascii=False)

    async def execute(self):
        os.environ['LM_STUDIO_API_BASE'] = "http://localhost:1234/v1"
        os.environ['LM_STUDIO_API_KEY'] = "fake"

        tools = []
        for t in self.tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        while True:
            await self.events.emit("model_called")
            response = completion(
                model=self.model,
                tools=tools if tools else None,
                messages=self.messages,
                stream=False,
                response_format={"type": "json_object"} if self.json else None
            )

            self._track_cost(response)   # <-- new

            message = response.choices[0].message
            await self.events.emit("message", message)

            self.messages.append({
                "role": message.role,
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls or []
                ]
            })

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    arguments = json.loads(tool_call.function.arguments)
                    object = {"function": tool_call.function.name, "arguments": arguments, "id": tool_call.id}
                    self.recent_tool_calls.append(object)
                    await self.events.emit("tool_call", object)
                    data = await self.execute_tool_call(tool_call.function.name, arguments)
                    await self.events.emit("tool_answer", {"tool_call": object, "data": data})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": data
                    })
            else:
                print(f"[DEBUG][cost] FINAL total: ${self.total_cost:.6f} over {self.call_count} calls")
                average_cost_per_call = self.total_cost / self.call_count if self.call_count else 0.0
                return {
                    "content": message.content,
                    "total_cost": self.total_cost,
                    "average_cost_per_call": average_cost_per_call,
                }
