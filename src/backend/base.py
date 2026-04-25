from contextlib import nullcontext
from functools import wraps

import dspy


class Program(dspy.Module):
    def __init__(self, lm: dspy.LM | None = None):
        super().__init__()
        self.lm = lm

    def _lm_context(self):
        return dspy.context(lm=self.lm) if self.lm is not None else nullcontext()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "forward" in cls.__dict__:
            forward = cls.__dict__["forward"]

            @wraps(forward)
            def wrapped_forward(self, *args, __forward=forward, **kwargs):
                with self._lm_context():
                    return __forward(self, *args, **kwargs)

            cls.forward = wrapped_forward

        if "aforward" in cls.__dict__:
            aforward = cls.__dict__["aforward"]

            @wraps(aforward)
            async def wrapped_aforward(self, *args, __aforward=aforward, **kwargs):
                with self._lm_context():
                    return await __aforward(self, *args, **kwargs)

            cls.aforward = wrapped_aforward
