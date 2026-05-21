import sys
import os

# Align paths
sys.path.append(os.path.join(os.getcwd(), "quant_app", "backend"))
sys.path.append(os.path.join(os.getcwd(), "quant_app", "backend", "strategies"))

from martingale_grid import MartingaleGrid

def test_lot_progression():
    print("--- Testing Ranger 2.0 Lot Progression ---")
    strategy = MartingaleGrid()
    strategy.initial_lot = 0.01
    strategy.lot_multiplier = 1.12
    strategy.stagnant_layers = 3
    
    print(f"Settings: Initial={strategy.initial_lot}, Multiplier={strategy.lot_multiplier}, Stagnant={strategy.stagnant_layers}")
    
    for i in range(11):
        lot = strategy.get_next_lot(i)
        print(f"Layer {i}: {lot}")

if __name__ == "__main__":
    test_lot_progression()
