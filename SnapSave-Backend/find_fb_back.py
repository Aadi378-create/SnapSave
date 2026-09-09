with open('api/server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'feedback' in line.lower():
        print(f"{i+1}: {line.strip()}".encode('ascii', 'ignore').decode())
