def generate_order_sheet(order):

    text = []

    text.append(f"Store → {order['store'].title()}")
    text.append("")

    text.append("Items:")

    for item in order["items"]:

        text.append(f"- {item['name']} x{item['qty']}")

    text.append("")
    text.append(f"Customer → {order['customer_name']}")
    text.append(f"Phone → {order['phone']}")
    text.append(f"Address → {order['address']}")
    text.append("")
    text.append(f"Expected Price → ₹{order['amount']}")

    return "\n".join(text)