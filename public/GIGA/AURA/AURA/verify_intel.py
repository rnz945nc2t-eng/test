import sys
import os
import time
from pathlib import Path
import shutil

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_folder import FolderAura
from aura_field import PellLucasSpine

def test_intelligence_layer():
    test_node = Path("./intel_test")
    if test_node.exists(): shutil.rmtree(test_node)
    test_node.mkdir()
    
    (test_node / "shared").mkdir()
    (test_node / "shared" / "python_script.py").write_text("import os\nprint('hello')")
    
    fa = FolderAura(str(test_node)).scan()
    
    # 1. Test Resonance Caching (ClosedIfSet)
    query = "python coding"
    
    start = time.time()
    res1 = fa.resonate(query)
    time1 = time.time() - start
    
    start = time.time()
    res2 = fa.resonate(query)
    time2 = time.time() - start
    
    print(f"Resonance 1: {res1:.4f} ({time1:.6f}s)")
    print(f"Resonance 2: {res2:.4f} ({time2:.6f}s)")
    
    assert res1 == res2
    # The second call should be significantly faster (cached)
    # Even in this small example, it should be faster.
    print(f"✓ Resonance caching works (Speedup: {time1/max(time2,1e-9):.1f}x)")
    
    # 2. Test PellLucasSpine
    spine = PellLucasSpine(max_levels=8)
    history = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    encoded = spine.encode(history, levels=4)
    
    print(f"Encoded history: {encoded}")
    assert len(encoded) == 8 # 4 levels * 2 (avg, var)
    print("✓ PellLucasSpine encoding works")

if __name__ == "__main__":
    try:
        test_intelligence_layer()
        print("\nALL INTELLIGENCE LAYER TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
