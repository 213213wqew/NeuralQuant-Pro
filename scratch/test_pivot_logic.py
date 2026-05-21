import sys
import os

# Ensure the app packages are in the import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_app.modules.ai.curve_analysis.curve_signal_gate import PivotSummary, CurveSignalGate, CurveGateConfig

def test_chronological_wave_logic():
    print("=== Testing Chronological Wave Swing Selection Logic ===")
    
    # Instantiate the gate
    config = CurveGateConfig()
    gate = CurveSignalGate(config)
    
    # 1. Setup the pivots exactly matching the user's H1 screenshot scenario:
    # - Valley 1: Index 60, Price 4510.0 (LOW)
    # - Peak 1: Index 180, Price 4750.0 (HIGH)
    # - Valley 2: Index 295, Price 4530.0 (LOW) -> This is the most recent pivot!
    pivots = [
        PivotSummary(index=60, price=4510.0, age=240, kind="LOW", bar_time=1789000000, confirmed=True),
        PivotSummary(index=180, price=4750.0, age=120, kind="HIGH", bar_time=1789010000, confirmed=True),
        PivotSummary(index=295, price=4530.0, age=5, kind="LOW", bar_time=1789020000, confirmed=True),
    ]
    
    # A mock smooth list
    smooth = [4500.0] * 300
    
    print("\n[Input Pivots]:")
    for p in pivots:
        print(f"  - {p.kind} at Index {p.index:>3} | Price {p.price:.2f} | Age {p.age:>3}")
        
    # Execute the newly refactored _select_major_extremes
    major_low, major_high = gate._select_major_extremes(pivots, smooth)
    
    print("\n[Selected Extremes (Output)]:")
    print(f"  - MAJOR_LOW  (Red Dot)   : Index {major_low.index:>3} | Price {major_low.price:.2f}")
    print(f"  - MAJOR_HIGH (Yellow Dot): Index {major_high.index:>3} | Price {major_high.price:.2f}")
    
    # Assertions to verify correctness
    # In the old code: major_low would have been selected as index 60 (price 4510) because 4510 < 4530.
    # In our new wave code: major_low MUST be selected as index 295 (price 4530) because it is the most recent confirmed low!
    # And major_high MUST be selected as index 180 (price 4750).
    assert major_low.index == 295, f"Expected major_low index to be 295, got {major_low.index}"
    assert major_high.index == 180, f"Expected major_high index to be 180, got {major_high.index}"
    
    print("\n>>> SUCCESS: Chronological Wave Logic assertions PASSED! The red dot correctly swapped to the right side (Index 295)!")

if __name__ == "__main__":
    test_chronological_wave_logic()
