import os
import ctypes
import sys

dll_dir = r"E:\python\lh01\gold-quantification\dist\AQuantPro\_internal\torch\lib"
os.add_dll_directory(dll_dir)

try:
    print("Trying to load c10.dll...")
    ctypes.CDLL(os.path.join(dll_dir, "c10.dll"))
    print("c10.dll loaded successfully!")
except Exception as e:
    print("c10.dll load failed:", e)

try:
    print("Trying to load torch_cpu.dll...")
    ctypes.CDLL(os.path.join(dll_dir, "torch_cpu.dll"))
    print("torch_cpu.dll loaded successfully!")
except Exception as e:
    print("torch_cpu.dll load failed:", e)
