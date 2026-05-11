import torch
import torch.nn as nn
import torch.optim as optim
import sys
import os

# Add the directory containing the model to the path
sys.path.append(os.path.join(os.getcwd(), "public/GIGA/Aethyr One Ai"))
from hst_v8_pytorch_closed_if import HSTv8Crystalline, HSTv8Config

def train():
    # 1. Configuration for a small model
    config = HSTv8Config(
        vocab_size=256,    # Small vocab for demonstration
        d_model=64,        # Small embedding dimension
        n_heads=4,
        n_layers=2,        # Few layers
        d_ffn=128,
        lattice_depth=16,
        max_seq_len=64
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HSTv8Crystalline(config).to(device)

    # 2. Synthetic dataset: simple counting/pattern
    # We'll train it to predict the next number in a sequence [0, 1, 2, ..., 254]
    def get_batch(batch_size, seq_len):
        start_vals = torch.randint(0, 255 - seq_len, (batch_size,))
        data = torch.stack([torch.arange(s, s + seq_len + 1) for s in start_vals])
        x = data[:, :-1].to(device)
        y = data[:, 1:].to(device)
        return x, y

    optimizer = optim.AdamW(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()

    print(f"Training small Io model on {device}...")
    model.train()

    for step in range(2000):
        x, y = get_batch(16, 32)

        optimizer.zero_grad()
        output = model(x, training=True)
        logits = output['logits']

        loss = criterion(logits.reshape(-1, config.vocab_size), y.reshape(-1))
        loss.backward()
        optimizer.step()

        if step % 100 == 0:
            print(f"Step {step}, Loss: {loss.item():.4f}")

    # 3. Save the model
    torch.save(model.state_dict(), "io_small_model.pt")
    print("Training complete. Model saved to io_small_model.pt")

if __name__ == "__main__":
    train()
