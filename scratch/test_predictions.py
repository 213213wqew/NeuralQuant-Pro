import pandas as pd
from quant_app.modules.ai.inference import ai_engine
from quant_app.modules.ai.v_reversal_model import v_reversal_predictor

print("Loading CSV...")
df = pd.read_csv("gold_m1_history.csv")
print(f"Total rows: {len(df)}")

print("Running AI Engine prediction...")
res_ai = ai_engine.predict(df)
print("AI Engine Result:")
print(res_ai)

print("\nRunning V Reversal prediction...")
res_v = v_reversal_predictor.predict(df)
print("V Reversal Result:")
print(res_v)
