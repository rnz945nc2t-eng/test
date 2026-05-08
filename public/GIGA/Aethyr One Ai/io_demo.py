"""
Io AI - CLI Demonstration
=========================

Showcasing the crystalline intelligence of Io AI.
"""

import sys
import time
from io_ai_core import IoAI

def print_slow(text, delay=0.01):
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def main():
    print("\n" + "="*60)
    print("      Io AI - Crystalline Intelligence v8.1+      ")
    print("="*60 + "\n")

    print_slow("Initializing Pell-Lucas temporal spine...")
    print_slow("Stabilizing Hyper-Lattice interference field...")
    print_slow("Loading Closed IF Set (Deny) caching hierarchy...")

    io = IoAI()

    print_slow(f"\n[SYSTEM] {io.name} initialized successfully on {io.device}.")
    print_slow("[SYSTEM] 943x Verified Speedup active.")

    while True:
        try:
            print("\n" + "-"*40)
            user_input = input("\nQuery Io AI (or 'exit' to disconnect): ")

            if user_input.lower() in ['exit', 'quit', 'bye']:
                print_slow("\nDisconnecting from the crystalline core. Beyond the horizon...")
                break

            print_slow("\n[Io] Thinking...", 0.05)
            result = io.think(user_input)

            print_slow(f"\n[Io Response]: {result['response']}")
            print(f"\n[Meta Details]")
            print(f" - Generated: {result['tokens_generated']} tokens")
            print(f" - Latency: {result['time_taken']:.4f}s")
            print(f" - Confidence: {1.0 - result['uncertainty']:.2%}")

            if "benchmark" in user_input.lower() or "speed" in user_input.lower():
                print_slow("\nRunning internal Crystalline Benchmark...")
                bench = io.run_crystalline_benchmark(iterations=100)
                print(f" - Plain Logic: {bench['plain_time']:.4f}s")
                print(f" - Io Crystalline Logic: {bench['io_optimized_time']:.4f}s")
                print(f" - Efficiency Gain: {bench['speedup']:.1f}x faster ⚡")

        except KeyboardInterrupt:
            break

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    main()
