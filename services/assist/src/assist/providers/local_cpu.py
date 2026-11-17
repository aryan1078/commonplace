"""CPU inference inside Assist; all remote application traffic stays gRPC."""
import asyncio
import os
from .base import Provider, ProviderError

class LocalCPUProvider(Provider):
    def __init__(self):
        from llama_cpp import Llama
        self.model = Llama(model_path=os.environ["ASSIST_MODEL_PATH"], n_ctx=8192,
                           n_threads=int(os.getenv("ASSIST_THREADS", "4")), n_gpu_layers=0,
                           verbose=False, chat_format="chatml")
        self.lock = asyncio.Lock()

    async def complete(self, task, messages, *, json_mode=False, fast=False,
                       timeout=None, temperature=None):
        async with self.lock:
            arguments = dict(messages=messages, max_tokens=512,
                             temperature=0.2 if temperature is None else temperature)
            if json_mode:
                arguments["response_format"] = {"type": "json_object"}
            # Keep the lock until native inference ends, including cancellation.
            work = asyncio.create_task(asyncio.to_thread(self.model.create_chat_completion, **arguments))
            try:
                result = await asyncio.shield(work)
            except asyncio.CancelledError:
                await work
                raise
            except Exception as error:
                raise ProviderError(str(error)) from error
            return result["choices"][0]["message"]["content"] or ""

    async def stream(self, task, messages, *, fast=False, timeout=None):
        yield await self.complete(task, messages, fast=fast, timeout=timeout)
