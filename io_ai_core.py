
import torch
import sys
import os
from typing import Optional, List, Dict, Any
import tiktoken

# Add the directory containing the model to the path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "public/GIGA/Aethyr One Ai"))

from hst_v8_pytorch_closed_if import HSTv8Crystalline, HSTv8Config, CachedPagedKVCache

class IoAICore:
    def __init__(self, checkpoint_path: Optional[str] = None, device: str = 'cpu'):
        self.device = torch.device(device)
        self.config = HSTv8Config(
            vocab_size=50257,
            d_model=256,  # Smaller for efficiency in this environment
            n_heads=8,
            n_layers=4,
            d_ffn=1024,
            lattice_depth=32,
            block_size=16
        )
        self.model = HSTv8Crystalline(self.config).to(self.device)
        if checkpoint_path and os.path.exists(checkpoint_path):
            self.model.load_state_dict(torch.load(checkpoint_path, map_location=self.device))
        self.model.eval()

    @torch.no_grad()
    def generate(self, prompt: str, max_tokens: int = 50, temperature: float = 0.8) -> str:
        # Simplified tokenization for this prototype
        # In a real scenario, we'd use a proper tokenizer like tiktoken or transformers
        input_ids = self._tokenize(prompt).to(self.device)

        # Ensure input_ids is [B, S]
        if input_ids.dim() == 1:
            input_ids = input_ids.unsqueeze(0)

        generated_ids = self.model.generate(
            input_ids,
            max_new_tokens=max_tokens,
            temperature=temperature
        )

        return self._detokenize(generated_ids[0])

    def _tokenize(self, text: str) -> torch.Tensor:
        # Use tiktoken (GPT-2 encoding matches VOCAB_SIZE=50257)
        enc = tiktoken.get_encoding("gpt2")
        tokens = enc.encode(text)
        return torch.tensor(tokens)

    def _detokenize(self, ids: torch.Tensor) -> str:
        # Use tiktoken
        enc = tiktoken.get_encoding("gpt2")
        # Ensure ids is a list of ints
        if isinstance(ids, torch.Tensor):
            ids = ids.tolist()
        return enc.decode(ids)

    def get_status(self) -> Dict[str, Any]:
        return {
            "model": "Io v2 Sacred (HST v8.2 Crystalline)",
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "device": str(self.device),
            "status": "online",
            "features": ["Closed IF Set", "Pell-Lucas Time Spine", "Hyper-Lattice"]
        }
