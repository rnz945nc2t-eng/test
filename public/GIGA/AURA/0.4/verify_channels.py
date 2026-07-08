import sys
import os
from pathlib import Path
import shutil

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_field import AuraField

def test_channels():
    node1_path = Path("./c_node1")
    node2_path = Path("./c_node2")

    for p in [node1_path, node2_path]:
        if p.exists(): shutil.rmtree(p)
        p.mkdir()

    # 1. Default channel
    field1 = AuraField(str(node1_path))
    # 2. Custom channel
    field2 = AuraField(str(node2_path), channel="secret")

    print(f"Node 1 (default) field: {field1.field_group}:{field1.field_port}")
    print(f"Node 2 (secret)  field: {field2.field_group}:{field2.field_port}")

    assert field1.field_group != field2.field_group or field1.field_port != field2.field_port
    print("✓ Channels use different multicast parameters")

    # Verify MD5 mapping is deterministic
    field3 = AuraField(str(node1_path), channel="secret")
    assert field2.field_group == field3.field_group
    assert field2.field_port == field3.field_port
    print("✓ Channel mapping is deterministic")

if __name__ == "__main__":
    try:
        test_channels()
        print("\nALL CHANNEL TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
