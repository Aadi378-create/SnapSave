
import re

with open('SnapSave-Backend/api/server.py', 'r', encoding='utf-8') as f:
    code = f.read()

print('DeliveryConfigUpdate found:', 'DeliveryConfigUpdate' in code)

endpoints = re.findall(r'@app\.(get|post|put|delete)\(\"(.*?)\"\)', code)
seen = set()
duplicates = []
for m, path in endpoints:
    if (m, path) in seen:
        duplicates.append(f'{m.upper()} {path}')
    seen.add((m, path))
print('Duplicates:', duplicates)

place_req = code.find('class PlaceOrderRequest')
place_route = code.find('@app.post(\"/api/orders/{order_id}/place\")')
print('PlaceOrderRequest position:', place_req, 'Route position:', place_route)

