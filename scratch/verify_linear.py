import sys
import os

# Align paths
sys.path.append(os.path.join(os.getcwd(), "quant_app", "backend"))
sys.path.append(os.path.join(os.getcwd(), "quant_app", "backend", "strategies"))

from martingale_grid import MartingaleGrid

def test_linear_progression():
    print("--- Testing Ranger 3.0 'Linear Elite' Lot Progression ---")
    strategy = MartingaleGrid()
    strategy.initial_lot = 0.01
    strategy.stagnant_layers = 3
    strategy.lot_arithmetic_mode = True
    strategy.lot_increment = 0.01
    strategy.increment_step = 2
    
    print(f"Settings: Initial={strategy.initial_lot}, Stagnant={strategy.stagnant_layers}, Increment={strategy.lot_increment}, Step={strategy.increment_step}")
    
    for i in range(16):
        lot = strategy.get_next_lot(i)
        print(f"Layer {i}: {lot}")

if __name__ == "__main__":
    test_linear_progression()
