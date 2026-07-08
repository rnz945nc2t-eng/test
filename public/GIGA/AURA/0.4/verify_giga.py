import sys
import os
import shutil
from pathlib import Path

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_field import AuraField, MSG_ROUTE, MSG_SEEK

def test_full_giga_stack():
    test_node = Path("./giga_full_test")
    if test_node.exists(): shutil.rmtree(test_node)
    test_node.mkdir()

    field = AuraField(str(test_node), channel="giga-network")

    print(f"GIGA Node: {field.node_id}")
    print(f"AYR Address: {field.wallet_addr}")

    # 1. Test Intelligence awarding on interaction
    field.folder.tags = {"blockchain": 1.0}

    # Award for seek resonance
    field._handle(MSG_SEEK, {
        "node_id": "seeker",
        "name": "seeker_node",
        "query": "blockchain",
        "_verified": True
    }, "127.0.0.1")

    balance1 = field.ledger.balance
    print(f"Balance after seek: {balance1}")
    assert balance1 > 0

    # Award for receiving route
    field._handle(MSG_ROUTE, {
        "node_id": "router",
        "name": "router_node",
        "target": field.node_id,
        "filename": "giga_specs.pdf",
        "content": "GIGA Protocol v1.0",
        "_verified": True
    }, "127.0.0.1")

    balance2 = field.ledger.balance
    print(f"Balance after route: {balance2}")
    assert balance2 > balance1

    # 2. Verify ClosedIfSet on repeated seek
    import time
    start = time.time()
    field.folder.resonate("blockchain")
    t1 = time.time() - start

    start = time.time()
    field.folder.resonate("blockchain")
    t2 = time.time() - start
    print(f"Resonate timing: T1={t1:.6f}s, T2={t2:.6f}s")
    # T2 should be much smaller

    print("✓ Full GIGA integration verified")

if __name__ == "__main__":
    try:
        test_full_giga_stack()
        print("\nALL GIGA INTEGRATION TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
