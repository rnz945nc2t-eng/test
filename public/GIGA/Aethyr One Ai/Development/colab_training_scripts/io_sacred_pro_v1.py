"""
Io v2 Sacred (v8.2 Crystalline) - PRO Training Script
Optimized for Google Colab Pro / Tesla T4 (16GB VRAM)

Architecture: HST v8.2 Crystalline
Configuration: D=1024, L=24, LR=2e-4
Dataset: HuggingFace FineWeb-Edu (10BT Sample)
"""

import os
import gc
import time
import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import autocast, GradScaler
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, DataCollatorForLanguageModeling, get_linear_schedule_with_warmup
from datasets import load_dataset
from tqdm import tqdm

# ==================== CONFIGURATION (PRO) ====================
D_MODEL = 1024
N_HEADS = 16
N_LAYERS = 24
LATTICE_DEPTH = 64
MAX_SEQ_LEN = 512
VOCAB_SIZE = 50257
BATCH_SIZE = 4
GRADIENT_ACCUMULATION_STEPS = 4
MAX_TRAINING_STEPS = 100000
INITIAL_LR = 2e-4
WARMUP_STEPS = 2000

os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'backend:cudaMallocAsync,expandable_segments:True,max_split_size_mb:32'
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# ==================== ARCHITECTURE (v8.2) ====================

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size, d_model, curvature=1.0):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, d_model)
        self.c = curvature
        nn.init.normal_(self.embed.weight, 0, 0.01)

    def forward(self, x):
        h = self.embed(x)
        norm = h.norm(dim=-1, keepdim=True)
        max_norm = (1 - 1e-3) / math.sqrt(self.c)
        scale = torch.clamp(norm / max_norm, max=1.0)
        return h / (scale + 1e-8)

class DiamondMixer(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.proj = nn.Linear(d_model, d_model * 2)
        self.merge = nn.Linear(d_model * 2, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, u):
        xy = self.proj(u)
        x, y = xy.chunk(2, dim=-1)
        z, w = F.gelu(x + y), F.gelu(y - x)
        return self.norm(u + self.merge(torch.cat([z, w], dim=-1)))

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.qkv = nn.Linear(d_model, d_model * 3, bias=False)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x):
        q, k, v = self.qkv(x).chunk(3, dim=-1)
        kv = torch.einsum('bsd,bse->bde', k, v) * 0.95
        out = torch.einsum('bsd,bde->bse', q, kv)
        lr = torch.sigmoid((q * k).sum(dim=-1, keepdim=True))
        return self.norm(x + out * lr)

class HyperLatticeBlock(nn.Module):
    def __init__(self, d_model, lattice_depth=64):
        super().__init__()
        self.gate = nn.Linear(d_model, lattice_depth, bias=False)
        self.lattice_weights = nn.Parameter(torch.randn(lattice_depth, d_model, d_model) * 0.02)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x):
        logits = self.gate(x)
        k = max(1, int(logits.size(-1) * 0.1))
        scores, indices = torch.topk(F.softmax(logits, dim=-1), k, dim=-1)
        weights = self.lattice_weights[indices]
        effective = (weights * scores.unsqueeze(-1).unsqueeze(-1)).sum(dim=2)
        return self.norm(x + torch.matmul(x.unsqueeze(2), effective).squeeze(2))

class IoSacredModel(nn.Module):
    def __init__(self, vocab_size, d_model, n_layers):
        super().__init__()
        self.emb = HyperbolicEmbedding(vocab_size, d_model)
        self.pos = nn.Parameter(torch.zeros(1, MAX_SEQ_LEN, d_model))
        self.n_bottom = n_layers // 2

        self.bottom = nn.ModuleList([nn.ModuleDict({
            'mixer': DiamondMixer(d_model), 'hebb': HebbianFastWeights(d_model)
        }) for _ in range(self.n_bottom)])

        self.lattice = HyperLatticeBlock(d_model, LATTICE_DEPTH)

        self.top = nn.ModuleList([nn.ModuleDict({
            'mixer': DiamondMixer(d_model), 'hebb': HebbianFastWeights(d_model)
        }) for _ in range(n_layers - self.n_bottom)])

        self.ln_f = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size, bias=False)
        self.head.weight = self.emb.embed.weight

    def forward(self, x):
        h = self.emb(x) + self.pos[:, :x.size(1), :]
        for b in self.bottom: h = b['hebb'](b['mixer'](h))
        h = self.lattice(h)
        for b in self.top: h = b['hebb'](b['mixer'](h))
        return self.head(self.ln_f(h))

# ==================== TRAINING LOOP ====================

def main():
    print(f"Building Io v2 Sacred [D={D_MODEL}, L={N_LAYERS}]...")
    model = IoSacredModel(VOCAB_SIZE, D_MODEL, N_LAYERS).to(device)
    print(f"Model Parameters: {sum(p.numel() for p in model.parameters())/1e6:.1f}M")

    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    tokenizer.pad_token = tokenizer.eos_token

    print("Loading FineWeb-Edu Streamer...")
    dataset = load_dataset("HuggingFaceFW/fineweb-edu", "sample-10BT", split="train", streaming=True)

    def tokenize(ex):
        return {"input_ids": tokenizer(ex["text"], truncation=True, max_length=MAX_SEQ_LEN)["input_ids"]}

    stream = dataset.map(tokenize, batched=True, batch_size=1000, remove_columns=dataset.column_names)
    collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)
    loader = DataLoader(stream, batch_size=BATCH_SIZE, collate_fn=collator)

    optimizer = torch.optim.AdamW(model.parameters(), lr=INITIAL_LR, weight_decay=0.01)
    scheduler = get_linear_schedule_with_warmup(optimizer, WARMUP_STEPS, MAX_TRAINING_STEPS)
    scaler = GradScaler('cuda' if device.type == 'cuda' else 'cpu', enabled=(device.type == 'cuda'))

    model.train()
    step = 0
    pbar = tqdm(total=MAX_TRAINING_STEPS, desc="Training Io Sacred")

    for batch in loader:
        if step >= MAX_TRAINING_STEPS: break

        ids = batch["input_ids"].to(device)
        with autocast(device_type=device.type):
            logits = model(ids)
            loss = F.cross_entropy(logits[:, :-1, :].reshape(-1, VOCAB_SIZE), ids[:, 1:].reshape(-1))
            loss = loss / GRADIENT_ACCUMULATION_STEPS

        scaler.scale(loss).backward()

        if (step + 1) % GRADIENT_ACCUMULATION_STEPS == 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad()

            pbar.set_postfix({"loss": loss.item() * GRADIENT_ACCUMULATION_STEPS})
            pbar.update(1)

        if step % 5000 == 0:
            torch.save(model.state_dict(), f"io_sacred_pro_step_{step}.pt")

        step += 1

if __name__ == "__main__":
    main()
