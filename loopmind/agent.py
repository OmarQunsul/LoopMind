from litellm import completion
import os
import json

class Agent:
    def __init__(self, model, system, prompt = None, connectors = [], events = None, json = False):
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
                response_format = { "type": "json_object" } if self.json else None
            )
            # response_format= { "type": "json_object" } if self.json else None) LmStudio only accepts json_schema but it was causing problems before

            message = response.choices[0].message
            await self.events.emit("message", message)


            # Make sure to preserve the thinking content. And add a method to clear all the previous thinking contents
            # for example to clean it up every time a user sends a new prompt. Maybe something that can be done automatically on the #user() method
            self.messages.append({
                "role": message.role,        # "assistant"
                # "response_format": { "type": "json_schema" },
                "content": message.content,   # the text response
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments  # JSON string
                        }
                    }
                    for tc in message.tool_calls or []
                ]
            })

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    arguments = json.loads(tool_call.function.arguments) # Arguments is for some reason a string
                    object = {"function": tool_call.function.name, "arguments": arguments, "id": tool_call.id}
                    self.recent_tool_calls.append(object)
                    await self.events.emit("tool_call", object)
                    data = await self.execute_tool_call(tool_call.function.name, arguments)
                    await self.events.emit("tool_answer", {"tool_call": object, "data": data})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,    # must match the tool_call id above
                        "name": tool_call.function.name,
                        "content": data   # must be a string
                    })
            else:
                return message.content
