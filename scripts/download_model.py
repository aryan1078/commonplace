"""Download the official CPU model files before running Assist."""
import argparse
from pathlib import Path
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--gguf", action="store_true")
parser.add_argument("--size", choices=["0.5b", "1.5b"], default="0.5b")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "models"
root.mkdir(exist_ok=True)
if args.gguf:
    files = ["qwen2.5-0.5b-instruct-q4_k_m.gguf"]
    repo = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
else:
    files = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
             "vocab.json", "merges.txt", "model.safetensors"]
    repo = "Qwen/Qwen2.5-" + args.size.upper() + "-Instruct"
    root = root / ("qwen-1.5b" if args.size == "1.5b" else "qwen-transformers")
    root.mkdir(exist_ok=True)
for name in files:
    target = root / ("qwen.gguf" if args.gguf else name)
    temporary = target.with_suffix(target.suffix + ".part")
    print("Downloading", name, flush=True)
    urllib.request.urlretrieve(f"https://huggingface.co/{repo}/resolve/main/{name}", temporary)
    temporary.replace(target)
print("Model directory", root)
