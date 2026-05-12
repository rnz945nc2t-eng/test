"""
Io v2 Sacred (HST v8.2 Crystalline) - "THE BEST AI"
Official Google Colab Training Script (MEMORY OPTIMIZED)
Optimized for T4 GPU (16GB VRAM)

Key Fix:
- Implemented Iterative Lattice Processing in HyperLatticeBlock to prevent OOM.
- Optimized D_MODEL and MAX_SEQ_LEN for stable training.
"""

# ==================== RESILIENT SETUP ====================
import os
import sys
import gc
import math
import time
import numpy as np
from typing import Dict, Optional, Tuple, List

# Set CUDA allocator config
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'backend:cudaMallocAsync,expandable_segments:True,max_split_size_mb:32'

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.cuda.amp import autocast, GradScaler
    from torch.utils.data import DataLoader, Dataset
except ImportError:
    print("Installing base dependencies...")
    os.system('pip install torch transformers datasets tiktoken -q')
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.cuda.amp import autocast, GradScaler
    from torch.utils.data import DataLoader, Dataset

try:
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    from datasets import load_dataset
    import tiktoken
except ImportError:
    os.system('pip install transformers datasets tiktoken -q')
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    from datasets import load_dataset
    import tiktoken

# CUDA Safety Check
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Device: {device}")

if torch.cuda.is_available():
    try:
        gpu_name = torch.cuda.get_device_name(0)
        print(f"GPU: {gpu_name}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"VRAM: {vram:.1f} GB")
    except Exception as e:
        print(f"CUDA Error: {e}")
        torch.cuda.init()

# ==================== HYPERPARAMETERS (REFINED) ====================
D_MODEL = 512 # Optimized for VRAM stability
N_HEADS = 8
N_LAYERS = 16
LATTICE_DEPTH = 64
MAX_SEQ_LEN = 512 # Optimized for VRAM stability
HORIZON = 16
VOCAB_SIZE = 50257
BATCH_SIZE = 1
GRADIENT_ACCUMULATION_STEPS = 16
MAX_TRAINING_STEPS = 10000
INITIAL_LR = 2e-4
WARMUP_STEPS = 1000

# ==================== CORE ARCHITECTURE ====================

class PagedKVCache:
    def __init__(self, head_dim, num_heads, block_size=16, device='cpu'):
        self.head_dim = head_dim
        self.num_heads = num_heads
        self.block_size = block_size
        self.device = device
        self.key_blocks = []
        self.value_blocks = []
        self.current_length = 0

    def get_length(self):
        return self.current_length

    def append(self, k, v):
        if k.dim() == 4:
            k = k.squeeze(0)
            v = v.squeeze(0)
        seq_len = k.size(0)
        tokens_written = 0
        while tokens_written < seq_len:
            if not self.key_blocks or self.key_blocks[-1].size(0) == self.block_size:
                self.key_blocks.append(torch.tensor([], device=self.device))
                self.value_blocks.append(torch.tensor([], device=self.device))
            space_left = self.block_size - self.key_blocks[-1].size(0)
            to_write = min(space_left, seq_len - tokens_written)
            k_chunk = k[tokens_written : tokens_written + to_write]
            v_chunk = v[tokens_written : tokens_written + to_write]
            if self.key_blocks[-1].numel() == 0:
                self.key_blocks[-1] = k_chunk
                self.value_blocks[-1] = v_chunk
            else:
                self.key_blocks[-1] = torch.cat([self.key_blocks[-1], k_chunk], dim=0)
                self.value_blocks[-1] = torch.cat([self.value_blocks[-1], v_chunk], dim=0)
            tokens_written += to_write
        self.current_length += seq_len

    def get_all(self):
        if not self.key_blocks: return None, None
        return torch.cat(self.key_blocks, dim=0).unsqueeze(0), torch.cat(self.value_blocks, dim=0).unsqueeze(0)

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size, d_model, curvature=1.0):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, d_model)
        self.c = curvature
        nn.init.normal_(self.embed.weight, 0, 0.01)

    def forward(self, x):
        x = self.embed(x)
        norm = x.norm(dim=-1, keepdim=True)
        max_norm = (1 - 1e-3) / math.sqrt(self.c)
        scale = torch.clamp(norm / max_norm, max=1.0)
        return x / (scale + 1e-8)

class DiamondMixer(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.split_proj = nn.Linear(d_model, d_model * 2)
        self.merge_proj = nn.Linear(d_model * 2, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, u):
        xy = self.split_proj(u)
        x, y = xy.chunk(2, dim=-1)
        z, w = F.gelu(x + y), F.gelu(y - x)
        return self.norm(u + self.merge_proj(torch.cat([z, w], dim=-1)))

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model, lambda_decay=0.95):
        super().__init__()
        self.lambda_decay = lambda_decay
        self.qkv = nn.Linear(d_model, d_model * 3, bias=False)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x):
        B, S, D = x.shape
        q, k, v = self.qkv(x).reshape(B, S, 3, D).unbind(2)
        kv = torch.einsum('bsd,bse->bde', k, v) * self.lambda_decay
        out = torch.einsum('bsd,bde->bse', q, kv)
        lr = torch.sigmoid((q * k).sum(dim=-1, keepdim=True))
        return self.norm(x + out * lr)

class HyperLatticeBlock(nn.Module):
    def __init__(self, d_model, lattice_depth=64):
        super().__init__()
        self.lattice_depth = lattice_depth
        self.gate = nn.Linear(d_model, lattice_depth, bias=False)
        self.lattice_weights = nn.Parameter(torch.randn(lattice_depth, d_model, d_model) * 0.02)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x):
        B, S, D = x.shape
        logits = self.gate(x)
        scores = F.softmax(logits, dim=-1)
        k = max(1, int(self.lattice_depth * 0.1))
        top_scores, indices = torch.topk(scores, k, dim=-1)

        # MEMORY OPTIMIZATION: Iterative processing to avoid large [B, S, k, D, D] tensors
        output = torch.zeros_like(x)
        for i in range(k):
            idx = indices[:, :, i]
            score = top_scores[:, :, i].unsqueeze(-1)
            w = self.lattice_weights[idx]
            trans = torch.matmul(x.unsqueeze(2), w).squeeze(2)
            output += trans * score

        return self.norm(x + output)

class CrystallineAttention(nn.Module):
    def __init__(self, d_model, n_heads):
        super().__init__()
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        self.qkv = nn.Linear(d_model, d_model * 3, bias=False)
        self.out_proj = nn.Linear(d_model, d_model)

    def forward(self, x, past=None):
        B, S, D = x.shape
        q, k, v = self.qkv(x).reshape(B, S, 3, self.n_heads, self.head_dim).permute(2, 0, 3, 1, 4).unbind(0)
        if past is not None:
            pk, pv = past
            k, v = torch.cat([pk, k], dim=2), torch.cat([pv, v], dim=2)
        present = (k, v)
        out = F.scaled_dot_product_attention(q, k, v, is_causal=(past is None))
        return self.out_proj(out.transpose(1, 2).reshape(B, S, D)), present

class CrystallineBlock(nn.Module):
    def __init__(self, d_model, n_heads):
        super().__init__()
        self.attn = CrystallineAttention(d_model, n_heads)
        self.mixer = DiamondMixer(d_model)
        self.hebbian = HebbianFastWeights(d_model)
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)

    def forward(self, x, past=None):
        a_out, present = self.attn(self.ln1(x), past)
        x = x + a_out
        x = self.mixer(x)
        x = self.hebbian(self.ln2(x))
        return x, present

class HSTv8Crystalline(nn.Module):
    def __init__(self, vocab_size, d_model, n_heads, n_layers, lattice_depth=64):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.embedding = HyperbolicEmbedding(vocab_size, d_model)
        self.pos_encoding = nn.Parameter(torch.randn(1, 8192, d_model) * 0.02)
        self.blocks = nn.ModuleList([CrystallineBlock(d_model, n_heads) for _ in range(n_layers)])
        self.lattice = HyperLatticeBlock(d_model, lattice_depth)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        self.ln_f = nn.LayerNorm(d_model)
        self.lm_head.weight = self.embedding.embed.weight

    def forward(self, x, cache=None):
        B, S = x.shape
        past_len = cache[0].get_length() if cache else 0
        pos_emb = self.pos_encoding[:, past_len:past_len+S, :]
        x = self.embedding(x) + pos_emb

        for i, block in enumerate(self.blocks):
            layer_past = None
            if cache:
                pk, pv = cache[i].get_all()
                if pk is not None:
                    layer_past = (pk.permute(0, 2, 1, 3), pv.permute(0, 2, 1, 3))

            x, present = block(x, layer_past)

            if cache:
                new_k = present[0][:, :, -S:, :].permute(0, 2, 1, 3)
                new_v = present[1][:, :, -S:, :].permute(0, 2, 1, 3)
                cache[i].append(new_k, new_v)

        x = self.lattice(x)
        return {'logits': self.lm_head(self.ln_f(x))}

    @torch.no_grad()
    def generate(self, prompt_ids, max_new_tokens, temperature=1.0, top_k=50):
        self.eval()
        device = prompt_ids.device
        head_dim = self.d_model // self.n_heads
        cache = [PagedKVCache(head_dim, self.n_heads, device=device) for _ in range(len(self.blocks))]

        out = self(prompt_ids, cache=cache)
        logits = out['logits'][:, -1, :]

        generated_ids = prompt_ids.clone()

        start_time = time.time()
        for _ in range(max_new_tokens):
            if top_k > 0:
                v, _ = torch.topk(logits, top_k)
                logits[logits < v[:, -1].unsqueeze(-1)] = -float('Inf')

            probs = F.softmax(logits / temperature, dim=-1)
            next_token = torch.multinomial(probs, 1)
            generated_ids = torch.cat([generated_ids, next_token], dim=1)

            out = self(next_token, cache=cache)
            logits = out['logits'][:, -1, :]

        end_time = time.time()
        tps = max_new_tokens / (end_time - start_time)
        return generated_ids, tps

# ==================== DATA & TRAINING ====================

def train():
    print("Building model...")
    model = HSTv8Crystalline(VOCAB_SIZE, D_MODEL, N_HEADS, N_LAYERS, LATTICE_DEPTH).to(device)

    print(f"Params: {sum(p.numel() for p in model.parameters())/1e6:.1f}M")

    optimizer = torch.optim.AdamW(model.parameters(), lr=INITIAL_LR, weight_decay=0.01)
    scaler = GradScaler()

    print("Loading FineWeb-Edu (Sample)...")
    dataset = load_dataset("HuggingFaceFW/fineweb-edu", "sample-10BT", split="train", streaming=True)
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    tokenizer.pad_token = tokenizer.eos_token

    def stream_loader():
        for ex in dataset:
            tokens = tokenizer(ex['text'], truncation=True, max_length=MAX_SEQ_LEN)['input_ids']
            if len(tokens) > 1:
                yield torch.tensor(tokens).unsqueeze(0)

    loader = stream_loader()

    print("Starting Sacred Training Cycle...")
    model.train()
    step = 0
    start_time = time.time()

    try:
        for batch in loader:
            if step >= MAX_TRAINING_STEPS: break

            batch = batch.to(device)
            with autocast():
                outputs = model(batch)
                logits = outputs['logits']
                loss = F.cross_entropy(logits[:, :-1, :].reshape(-1, VOCAB_SIZE), batch[:, 1:].reshape(-1))
                loss = loss / GRADIENT_ACCUMULATION_STEPS

            scaler.scale(loss).backward()

            if (step + 1) % GRADIENT_ACCUMULATION_STEPS == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad()

                if step % (GRADIENT_ACCUMULATION_STEPS * 10) == 0:
                    elapsed = time.time() - start_time
                    print(f"Step {step} | Loss {loss.item()*GRADIENT_ACCUMULATION_STEPS:.4f} | Time {elapsed:.1f}s")
                    torch.cuda.empty_cache()
                    gc.collect()

            step += 1

    except KeyboardInterrupt:
        print("Training interrupted.")

    print("Training Complete. Saving model...")
    torch.save(model.state_dict(), "io_sacred_final.pt")

    # Final Test
    print("\n[Inference Test]")
    prompt = "The future of artificial intelligence is"
    input_ids = torch.tensor(tokenizer.encode(prompt)).unsqueeze(0).to(device)
    output, tps = model.generate(input_ids, max_new_tokens=50)

    generated_text = tokenizer.decode(output[0].tolist())
    print(f"Prompt: {prompt}")
    print(f"AI: {generated_text}")
    print(f"Performance: {tps:.2f} TPS")

    with open("io_generation_report.txt", "w") as f:
        f.write(f"TPS Record: {tps:.2f}\n\n")
        f.write("Generated Text:\n")
        f.write(generated_text)
    print("\nResults saved to io_generation_report.txt")

if __name__ == "__main__":
    train()
