import sys
import os
import time
from pathlib import Path
import shutil

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_field import AuraField, MSG_ROUTE, MSG_SEEK

def test_ledger():
    test_node = Path("./ledger_test")
    if test_node.exists(): shutil.rmtree(test_node)
    test_node.mkdir()
    
    field = AuraField(str(test_node))
    
    print(f"Node ID: {field.node_id}")
    print(f"Wallet: {field.wallet_addr}")
    assert field.wallet_addr.startswith("AYR")
    assert len(field.wallet_addr) == 35 # AYR + 32 hex
    
    # Initial balance
    assert field.ledger.balance == 0.0
    
    # 1. Test MSG_SEEK credit
    # Simulate a high resonance seek
    # We need to mock fa.resonate to return high score
    field.folder.tags = {"test": 1.0}
    
    field._handle(MSG_SEEK, {
        "node_id": "other",
        "name": "other_node",
        "query": "test",
        "_verified": True
    }, "127.0.0.1")
    
    print(f"Balance after seek: {field.ledger.balance}")
    assert field.ledger.balance > 0
    
    # 2. Test MSG_ROUTE credit
    old_balance = field.ledger.balance
    field._handle(MSG_ROUTE, {
        "node_id": "other",
        "name": "other_node",
        "target": field.node_id,
        "filename": "test.txt",
        "content": "hello",
        "_verified": True
    }, "127.0.0.1")
    
    print(f"Balance after route: {field.ledger.balance}")
    assert field.ledger.balance == old_balance + 0.1
    
    # 3. Verify persistence
    field.ledger.credit(5.0, "Bonus")
    new_balance = field.ledger.balance
    
    # Create new field object to reload ledger
    field2 = AuraField(str(test_node))
    assert field2.ledger.balance == new_balance
    print("✓ Ledger persistence verified")

if __name__ == "__main__":
    try:
        test_ledger()
        print("\nALL LEDGER TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
