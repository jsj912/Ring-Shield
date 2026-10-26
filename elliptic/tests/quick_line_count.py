with open("elliptic/data/raw/amlworld/HI-Small_Trans.csv", "rb") as f:
    count = sum(1 for _ in f)
print("Total lines (including header):", count)
print("Transaction rows (excluding header):", count - 1)