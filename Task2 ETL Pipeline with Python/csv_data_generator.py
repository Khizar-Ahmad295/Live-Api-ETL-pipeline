import csv
import json
import random
import faker 
fake=faker.Faker()
faker.Faker.seed(42)
random.seed(42)

CUSTOMER_START_ID=31
PRODUCT_START_ID=31
ORDER_START_ID=16

NUM_CUSTOMERS=300
NUM_PRODUCTS=60
NUM_ORDERS=500

CATEGORIES = {
    "beauty": ["Essence", "Glamour Beauty", "Chic Cosmetics", "Nail Couture", None],
    "fragrances": ["Calvin Klein", "Chanel", "Dior", "Gucci", "Dolce & Gabbana"],
    "furniture": ["Annibale Colombo", "Knoll", "Furniture Co.", "Bath Trends"],
    "groceries": [None],
    "electronics": ["Samsung", "Sony", "Apple", "LG", None],
}
STATUSES = ["pending", "processing", "shipped", "delivered", "cancelled"]
METHODS = ["cash", "card", "bank_transfer", "online"]

#Customers_csv

customer=[]

for i in range(NUM_CUSTOMERS):
    cid=CUSTOMER_START_ID+i
    address = {
        "street": fake.street_address(),
        "city": fake.city(),
        "state": fake.state(),
        "postalCode": fake.postcode(),
        "country": "United States",
    }
    customer.append({"id":cid,
                      "name":fake.name(),
                      "email":fake.unique.email(),
                      "phone":fake.phone_number(),
                      "address":json.dumps(address),
                      "created_at":fake.date_time_between(start_date='-2y',end_date='now').isoformat(),
                      })
with open("Task2 ETL Pipeline with Python/customers_raw.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=customer[0].keys())
    w.writeheader()
    w.writerows(customer)
    
##Products_csv
products=[]

for i in range(NUM_PRODUCTS):
    pid=PRODUCT_START_ID+i
    category=random.choice(list(CATEGORIES.keys()))
    brand=random.choice(CATEGORIES[category])
    stock=random.randint(0,100)
    availability="Low Stock" if stock<10 else "In Stock"
    products.append({
    "id": pid,
    "title": fake.catch_phrase(),
    "description": fake.sentence(nb_words=12),
    "category": category,
    "brand": brand if brand else "",
    "price": round(random.uniform(2, 500), 2),
    "discount_percentage": round(random.uniform(0, 20), 2),
    "stock_quantity": stock,
    "rating": round(random.uniform(2, 5), 2),
    "availability_status": availability,
    "minimum_order_quantity": random.randint(1, 50),
    "created_at": fake.date_time_between(
        start_date="-2y", end_date="-30d"
    ).isoformat(),
    "updated_at": fake.date_time_between(
        start_date="-30d", end_date="now"
    ).isoformat()
})
    
with open("Task2 ETL Pipeline with Python/products_raw.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=products[0].keys())
    w.writeheader()
    w.writerows(products)
    
# orders and order_items csv creating

orders=[]
order_items=[]
item_id=1

for i in range(NUM_ORDERS):
    oid=ORDER_START_ID+i
    cust=random.choice(customer)
    order_date=fake.date_time_between(start_date="-1y",end_date="now")
    status=random.choice(STATUSES)
    
    num_items=random.randint(1,4)
    choosen_products=random.sample(products,num_items)
    total_amount=0
    for prod in choosen_products:
        qty=random.randint(1,5)
        unit_price=prod["price"]
        discount=prod["discount_percentage"]
        line_total = round(qty * unit_price * (1 - discount / 100), 2)
        total_amount += line_total
 
        order_items.append({
            "id": item_id,
            "order_id": oid,
            "product_id": prod["id"],
            "quantity": qty,
            "unit_price": unit_price,
            "discount_percentage": discount,
        })
        item_id += 1
 
    orders.append({
        "id": oid,
        "customer_id": cust["id"],
        "order_date": order_date.isoformat(),
        "status": status,
        "total_amount": round(total_amount, 2),
    })
 
with open("Task2 ETL Pipeline with Python/orders_raw.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=orders[0].keys())
    w.writeheader()
    w.writerows(orders)
 
with open("Task2 ETL Pipeline with Python/order_items_raw.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=order_items[0].keys())
    w.writeheader()
    w.writerows(order_items)
 
# ---------- 5. payments.csv ----------
payments = []
pay_id = 1
for order in orders:
    if order["status"] == "cancelled" and random.random() < 0.7:
        continue  # most cancelled orders never got paid
    payments.append({
        "id": pay_id,
        "order_id": order["id"],
        "amount": order["total_amount"],
        "payment_date": order["order_date"],
        "method": random.choice(METHODS),
    })
    pay_id += 1
 
with open("Task2 ETL Pipeline with Python/payments_raw.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=payments[0].keys())
    w.writeheader()
    w.writerows(payments)
 
print(f"customers.csv   -> {len(customer)} rows")
print(f"products.csv    -> {len(products)} rows")
print(f"orders.csv      -> {len(orders)} rows")
print(f"order_items.csv -> {len(order_items)} rows")
print(f"payments.csv    -> {len(payments)} rows")
 