"""Un modelo de IA falso para probar el sistema sin gastar API."""
import copy
import json
import types


def respuesta(texto=None, llamadas=None):
    """llamadas: [(nombre, args_dict_o_str), ...]"""
    tcs = []
    for i, (nombre, args) in enumerate(llamadas or []):
        if not isinstance(args, str):
            args = json.dumps(args)
        tcs.append(types.SimpleNamespace(id=f"call_{i}", function=types.SimpleNamespace(name=nombre, arguments=args)))
    msg = types.SimpleNamespace(content=texto, tool_calls=tcs or None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class ErrorAPI(Exception):
    def __init__(self, status_code, texto="error"):
        super().__init__(texto)
        self.status_code = status_code
        self.response = None


class ModeloFalso:
    """`guion` es una función (mensajes, kwargs) -> respuesta | Exception, o una lista de respuestas en orden."""

    def __init__(self, guion):
        self.guion = guion
        self.llamadas = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        kwargs = copy.deepcopy(kwargs)  # foto del momento (la lista real sigue creciendo)
        self.llamadas.append(kwargs)
        if callable(self.guion):
            r = self.guion(kwargs["messages"], kwargs)
        else:
            r = self.guion.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
