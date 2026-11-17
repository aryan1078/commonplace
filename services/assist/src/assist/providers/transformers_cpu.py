"""Local CPU inference with Transformers, exposed by Assist over gRPC."""
import asyncio
import os
from .base import Provider, ProviderError


class TransformersCPUProvider(Provider):
    def __init__(self):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        torch.set_num_threads(int(os.getenv("ASSIST_THREADS", "4")))
        path = os.environ["ASSIST_MODEL_PATH"]
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        precision = os.getenv("ASSIST_DTYPE", "float32")
        if precision not in ("float32", "bfloat16"):
            raise ValueError("ASSIST_DTYPE must be float32 or bfloat16")
        dtype = torch.bfloat16 if precision == "bfloat16" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True, dtype=dtype).eval()
        self.lock = asyncio.Lock()

    def generate(self, messages, temperature, json_mode):
        import torch
        if json_mode:
            messages = [dict(message) for message in messages]
            messages[0]["content"] += "\nReturn only the requested JSON object."
        tokens = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                                     tokenize=True, return_dict=True, return_tensors="pt")
        with torch.inference_mode():
            result = self.model.generate(**tokens, max_new_tokens=512, do_sample=False,
                                         pad_token_id=self.tokenizer.eos_token_id)
        return self.tokenizer.decode(result[0, tokens["input_ids"].shape[1]:], skip_special_tokens=True)

    async def complete(self, task, messages, *, json_mode=False, fast=False, timeout=None, temperature=None):
        async with self.lock:
            work = asyncio.create_task(asyncio.to_thread(self.generate, messages, temperature, json_mode))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await work
                raise
            except Exception as error:
                raise ProviderError(str(error)) from error

    async def stream(self, task, messages, *, fast=False, timeout=None):
        yield await self.complete(task, messages, fast=fast, timeout=timeout)
