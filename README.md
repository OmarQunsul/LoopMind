# LoopMind

A lightweight Python SDK for building tool-calling AI agents. It provides an agentic loop built on [LiteLLM](https://github.com/BerriAI/litellm), with pluggable
tool sources ("connectors") — either remote [MCP](https://modelcontextprotocol.io) servers or local Python tool sets.

## Features

- **Agent** — runs an autonomous tool-calling loop: sends messages to the LLM, executes any requested tool calls, feeds results back, and repeats until a final answer is produced.
- **Connectors** — a unified interface (`get_tools()`, `tool_names()`, `call_tool()`, `close()`) implemented by both `McpClient` and `ToolSet`, so remote and local tools are interchangeable.
- **McpClient** — connects to any MCP server over HTTP and exposes its tools to the agent.
- **ToolSet + `@tool` decorator** — define local tools as plain Python methods; the docstring becomes the tool description and type hints are converted into a JSON input schema automatically.
- **FileTools + FileSystem** — a ready-made `ToolSet` providing file read/write/append/delete/find and anchor-based block editing operations. All changes are held in an in-memory overlay (`FileSystem`) on top of the real file system, so nothing is written to disk until explicitly committed. A unified diff of all pending changes can be generated at any time.
- **EventEmitter** — async event bus for observing the agent in real time (`message`, `tool_call`, `tool_answer` events), supporting both sync and async handlers.

## Installation

```bash
pip install -e .
```

The agent uses LiteLLM under the hood, so any provider it supports works. The default setup targets a local [LM Studio](https://lmstudio.ai) server (the agent sets `LM_STUDIO_API_BASE` to `http://localhost:1234/v1`), e.g. model name `lm_studio/qwen3.8-27b`.

## Quick Start

### Basic example

```python
import asyncio
from loopmind import Agent, EventEmitter


async def main():
    events = EventEmitter()
    events.subscribe("tool_call", lambda tc: print(f"Tool call: {tc}"))

    agent = Agent(
        model="lm_studio/qwen3.8-27b",
        system="You are a helpful assistant",
        prompt="Say hello in one sentence.",
        connectors=[],           # no tools needed for a plain chat answer
        events=events,
    )
    await agent.loadTools()
    result = await agent.execute()
    print(result)


asyncio.run(main())
```

### Example with tools

```python
import asyncio
from loopmind import Agent, EventEmitter, ToolSet, tool

class MathTools(ToolSet):
    @tool
    def add(self, a: float, b: float) -> float:
        """Add two numbers together."""
        return a + b

    @tool
    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers together."""
        return a * b


async def main():
    events = EventEmitter()
    connectors = [MathTools()]

    agent = Agent(
        model="lm_studio/qwen3.8-27b",
        system="You are a math assistant.",
        prompt="What is 4 * (3 + 5)?",
        connectors=connectors,
        events=events,
    )

    await agent.loadTools()
    result = await agent.execute()
    print("Answer:", result)

    for connector in connectors:
        await connector.close()


asyncio.run(main())
```

> Note: the agent sets the LM Studio environment variables (`LM_STUDIO_API_BASE` and `LM_STUDIO_API_KEY`) internally when `execute()` runs, so a local LM Studio server on `localhost:1234` is the default target.

## Using the Agent

The `Agent` class lives in [`loopmind/agent.py`](loopmind/agent.py) and is re-exported from the package root, so `from loopmind import Agent` and `from loopmind.agent import Agent` are equivalent.

It runs an autonomous tool-calling loop: it sends your messages to the LLM, executes any tool calls the model requests via your connectors, feeds the results back, and repeats until the model returns a final answer (no more tool calls). It is fully async.

### Constructor

```python
Agent(model, system, prompt, connectors, events, json=True)
```

| Parameter    | Type                                          | Description                                                                   |
| ------------ | --------------------------------------------- | ----------------------------------------------------------------------------- |
| `model`      | `str`                                         | LiteLLM model identifier, e.g. `lm_studio/qwen3.8-27b`                        |
| `system`     | `str`                                         | System prompt                                                                 |
| `prompt`     | `str`                                         | Initial user prompt                                                           |
| `connectors` | `list`                                        | Tool sources (`McpClient`, `ToolSet` subclasses, ...)                         |
| `events`     | `EventEmitter`                                | Event bus used to observe `message`, `tool_call`, `tool_answer` events        |
| `json`       | `bool`                                        | Reserved for future use (JSON response format is currently disabled)          |

### Lifecycle methods

| Method                                  | Description                                                                   |
| --------------------------------------- | ----------------------------------------------------------------------------- |
| `await agent.loadTools()`               | Loads tool definitions from all connectors. **Must be called before `execute()`.** |
| `await agent.execute()`                 | Runs the agentic loop and returns `{"content", "total_cost", "average_cost_per_call"}`. |
| `await agent.execute_tool_call(name, arguments)` | Directly invokes a named tool on the matching connector and returns its JSON result. |

The attribute `agent.recent_tool_calls` accumulates every tool call made during execution as `{"function", "arguments", "id"}` dicts.


## Core components

### `Agent(model, system, prompt, connectors, events, json=True)`

| Parameter    | Description                                                        |
| ------------ | ------------------------------------------------------------------ |
| `model`      | LiteLLM model identifier (e.g. `lm_studio/qwen3.8-27b`)            |
| `system`     | System prompt                                                      |
| `prompt`     | Initial user prompt                                                |
| `connectors` | List of connectors (`McpClient`, `ToolSet` subclasses, ...)        |
| `events`     | An `EventEmitter` used to broadcast lifecycle events               |
| `json`       | Reserved for future use (JSON response format is currently disabled) |

Methods:

- `await agent.loadTools()` — loads tool definitions from all connectors. Must be called before `execute()`.
- `await agent.execute()` — runs the agentic loop and returns `{"content", "total_cost", "average_cost_per_call"}`.
- `agent.recent_tool_calls` — list of all tool calls made during execution (`{"function", "arguments", "id"}`).

### `McpClient(url)`

Connector for a remote MCP server. Lazily opens the connection on first use.

```python
client = McpClient("https://example.com/mcp")
connectors = [client]
# ... after running the agent:
await client.close()
```

### `ToolSet` and `@tool`

Subclass `ToolSet` and decorate methods with `@tool` to expose them as agent tools:

- Tool **name** = method name
- Tool **description** = method docstring
- Tool **input schema** = derived from type hints (`str`, `int`, `float`, `bool`, `list`, `dict`); parameters without defaults are marked required, parameters with defaults get a `"default"` value in the schema

Both sync and async methods are supported.

### `EventEmitter`

```python
events = EventEmitter()
events.subscribe("message", handler)      # sync or async handler
events.unsubscribe("message", handler)
await events.emit("message", payload)     # awaits async handlers concurrently
events.emit_nowait("message", payload)    # fire-and-forget background task
```

Events emitted by the agent:

| Event          | Payload                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------- |
| `model_called` | There is a call to the LLM                                                                |
| `message`      | Each LLM response message                                                                 |
| `tool_call`    | `{"function", "arguments", "id"}` per call                                                |
| `tool_answer`  | `{"tool_call": tool_call object, "data": The tool's result (JSON string)}`                |

