import inspect

def tool(func):
    """
    Decorate a method/function so its metadata is exposed to the agent as a tool.

    The docstring becomes the tool description and the signature (excluding
    ``self``/``cls``) is turned into the JSON input schema, mirroring the shape
    that McpClient.get_tools() returns.
    """
    properties = {}
    required = []
    json_types = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}

    for name, param in inspect.signature(func).parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        prop = {"type": json_types.get(annotation, "string")}
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(name)
        properties[name] = prop

    func._tool = {
        "name": func.__name__,
        "description": inspect.getdoc(func) or "",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
    return func


class ToolSet:
    def __init__(self):
        self._tools = {}
        for name in dir(self):
            attr = getattr(self, name)
            if callable(attr) and getattr(attr, "_tool", None):
                self._tools[name] = attr

    async def get_tools(self):
        return [dict(attr._tool) for attr in self._tools.values()]

    async def tool_names(self):
        return list(self._tools.keys())

    async def call_tool(self, name, arguments):
        method = self._tools.get(name)
        if method is None:
            return f"ERROR: unknown tool '{name}'"
        result = method(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def close(self):
        pass

