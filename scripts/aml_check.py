import pandas as pd
df = pd.read_csv("data/raw/amlworld/HI-Small_Trans.csv", nrows=5)
print(df.columns.tolist())
print(df.head())
print(df.dtypes)