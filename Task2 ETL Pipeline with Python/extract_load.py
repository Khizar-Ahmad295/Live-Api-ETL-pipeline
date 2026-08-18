import json
import os
import pandas as pd

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, MetaData, Table, insert
from urllib.parse import quote_plus
from pathlib import Path

# Creating database connection here
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent  
load_dotenv(BASE_DIR / ".env")

password = quote_plus(os.getenv("DB_PASSWORD"))

DATABASE_URL = (
    f"postgresql+psycopg2://{os.getenv('DB_USER')}:{password}@"
    f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=2
)

# Holds reflected Table objects so we only ask Postgres to describe each table once, instead of on every load_data() call.
metadata = MetaData()

ALLOWED_ORDER_STATUS = {
    "pending",
    "processing",
    "shipped",
    "delivered",
    "cancelled"
}

ALLOWED_PAYMENT_METHOD = {
    "cash",
    "card",
    "bank_transfer",
    "online"
}

rejected_rows = []

# Append rejected row in list to create the csv at the end
def reject_row(row, table_name, reason):

    rejected = row.to_dict()

    rejected["source_table"] = table_name
    rejected["rejection_reason"] = reason

    rejected_rows.append(rejected)

# get ids of csv rows from database already inserted before in database so same product or customer didnot get inserted twice
def get_existing_ids_by_column(table_name, column_name, values):

    """
    Returns:

        {column_value: database_id}

    Example:

        {
            "john@gmail.com": 31,
            "ali@gmail.com": 32
        }

    """

    values = list(values)

    if not values:
        return {}

    with engine.connect() as connection:

        result = connection.execute(
            text(
                f"SELECT {column_name}, id "
                f"FROM {table_name} "
                f"WHERE {column_name} = ANY(:values)"
            ),
            {"values": values}
        )

        return {
            row[0]: row[1]
            for row in result
        }

# load data in the database and also perform id mapping

def load_data(data,table_name,raw_id_column,columns,json_columns=None):
    
    if data.empty:
        print(f"  -> No valid rows to load into {table_name}")
        return {}

    # Only send actual database columns to PostgreSQL
    data_to_load = data[columns].copy()

    # JSONB columns need real Python dicts, not JSON-as-text strings.
    # If the CSV loaded them as strings, decode them here first.
    if json_columns:

        for col in json_columns:

            data_to_load[col] = data_to_load[col].apply(lambda v: json.loads(v) if isinstance(v, str) else v)
    # Reflect the table once (SQLAlchemy caches by name in `metadata`)
    if table_name in metadata.tables:
        table = metadata.tables[table_name]
    else:
        table = Table(table_name, metadata, autoload_with=engine)

    records = data_to_load.to_dict("records")

    with engine.begin() as connection:

        result = connection.execute(
            insert(table).returning(table.c.id),
            records
        )

        # Rows come back in the same order they were sent in
        new_ids = [row.id for row in result]

    id_map = dict(zip(data[raw_id_column],new_ids))
    print(f"  -> Loaded {len(data)} rows into {table_name}")
    return id_map


# load the customer data from the csv and send load data to load the data in the database 
def process_customers():

    print("Processing customers_raw.csv...")

    df = pd.read_csv(SCRIPT_DIR / "customers_raw.csv")

    total_rows = len(df)

    # Exact duplicate rows
    duplicate_rows = df[df.duplicated(keep="first")]
    for _, row in duplicate_rows.iterrows():

        reject_row(row,"customers","exact duplicate row")

    df = df.drop_duplicates(keep="first")

    # Existing customers based on email
    existing_by_email = get_existing_ids_by_column("customers","email",df["email"].dropna().astype(str).str.strip().str.lower().unique())

    valid_rows = []

    seen_emails = set()

    # RAW CSV id -> DATABASE id
    customer_id_map = {}

    already_loaded_count = 0

    for _, row in df.iterrows():

        # IMPORTANT:
        # Fake data generator uses "id", not "customer_id"
        raw_customer_id = row["id"]

        name = (
            str(row["name"]).strip()
            if pd.notna(row["name"])
            else ""
        )

        email = (
            str(row["email"]).strip().lower()
            if pd.notna(row["email"])
            else ""
        )

        if not name:

            reject_row(row,"customers","missing required field: name"
            )
            continue

        if not email:

            reject_row(row,"customers","missing required field: email")

            continue

        if "@" not in email:

            reject_row(row,"customers","invalid email format")

            continue

        # Customer already exists
        if email in existing_by_email:

            customer_id_map[raw_customer_id] = existing_by_email[email]

            already_loaded_count += 1

            continue

        # Duplicate email inside this CSV
        if email in seen_emails:

            reject_row(row,"customers","duplicate email ""(violates UNIQUE constraint)")

            continue

        phone = (
            str(row["phone"])
            if pd.notna(row["phone"])
            else ""
        )

        if len(phone) > 20:

            reject_row(row,"customers",f"phone exceeds VARCHAR(20) limit: '{phone}'")

            continue

        seen_emails.add(email)

        row = row.copy()
        row["email"] = email

        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)

    new_id_map = load_data(clean,"customers",raw_id_column="id",
        columns=[
            "name",
            "email",
            "phone",
            "address",
            "created_at"
        ],

        json_columns=["address"]
    )

    customer_id_map.update(
        new_id_map
    )

    print(
        f"  customers: {len(clean)} newly inserted, "
        f"{already_loaded_count} already existed, "
        f"{total_rows} total in file"
    )

    return customer_id_map

 # load the customer data from the csv and send load data to load the data in the database 

# load the products data from the csv and send load data to load the data in the database 
def process_products():

    print("Processing products_raw.csv...")

    df = pd.read_csv(SCRIPT_DIR / "products_raw.csv")

    total_rows = len(df)

    # Existing products based on title
    existing_by_title = get_existing_ids_by_column("products","title",df["title"].dropna().unique())

    valid_rows = []

    # RAW CSV id -> DATABASE id
    product_id_map = {}

    already_loaded_count = 0

    for _, row in df.iterrows():

        # IMPORTANT:
        # Fake data generator uses "id"
        raw_product_id = row["id"]

        title = (
            str(row["title"]).strip()
            if pd.notna(row["title"])
            else ""
        )

        if not title:

            reject_row(row,"products","missing required field: title")

            continue

        # Product already exists
        if title in existing_by_title:

            product_id_map[raw_product_id] = existing_by_title[title]

            already_loaded_count += 1

            continue

        if pd.isna(row["price"]):

            reject_row(row,"products",f"price missing or non-numeric (raw: '{row['price']}')")

            continue

        price = float(row["price"])

        if price < 0:

            reject_row(row,"products","negative price violates CHECK constraint")

            continue

        row = row.copy()

        row["price"] = price

        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)

    if not clean.empty:

        clean["brand"] = clean["brand"].replace("", None)

        clean["availability_status"] = clean["stock_quantity"].apply(
            lambda quantity:
                "Low Stock"
                if pd.notna(quantity)
                and quantity < 10
                else "In Stock"
        )

    new_id_map = load_data(clean,"products",raw_id_column="id",
        columns=[
            "title",
            "description",
            "category",
            "brand",
            "price",
            "discount_percentage",
            "stock_quantity",
            "rating",
            "availability_status",
            "minimum_order_quantity",
            "created_at"
        ]
    )

    product_id_map.update(new_id_map)

    print(
        f"  products: {len(clean)} newly inserted, "
        f"{already_loaded_count} already existed, "
        f"{total_rows} total in file"
    )

    return product_id_map


# load the orders data from the csv and send load data to load the data in the database 
def process_orders(customer_id_map):
    print("Processing orders_raw.csv...")
    df = pd.read_csv(SCRIPT_DIR / "orders_raw.csv")
    total_rows = len(df)
    valid_rows = []
    for _, row in df.iterrows():
        raw_order_id = row["id"]

        raw_customer_id = row["customer_id"]

        if (pd.isna(raw_customer_id)or str(raw_customer_id).strip() == ""):
            reject_row(row,"orders","missing required field: customer_id")

            continue

        try:

            raw_customer_id = int(raw_customer_id)

        except (ValueError, TypeError):

            reject_row(row,"orders",f"customer_id not numeric:'{raw_customer_id}'")
            continue

        status = (str(row["status"]).strip().lower())
        if status not in ALLOWED_ORDER_STATUS:
            reject_row(row,"orders",f"invalid status value: '{status}'")
            continue

        # Convert raw customer ID
        # to PostgreSQL customer ID
        database_customer_id = (customer_id_map.get(raw_customer_id))

        if database_customer_id is None:

            reject_row(row,"orders",f"customer_id {raw_customer_id} does not exist or was rejected (orphan FK)")

            continue

        row = row.copy()

        row["customer_id"] = (
            database_customer_id
        )

        row["status"] = status

        # Recalculated later from order_items
        row["total_amount"] = 0.0

        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)

    order_id_map = load_data(clean,"orders",
        raw_id_column="id",
        # PostgreSQL columns
        columns=["customer_id","order_date","status","total_amount"]
    )

    print(f"  orders: {len(clean)} valid /{total_rows} total")

    return order_id_map


# load the order_items data from the csv and send load data to load the data in the database 
def process_order_items(order_id_map,product_id_map):
    print("Processing order_items_raw.csv...")
    df = pd.read_csv(SCRIPT_DIR / "order_items_raw.csv")
    total_rows = len(df)
    valid_rows = []
    for _, row in df.iterrows():

        # IMPORTANT:
        # Raw order_items CSV uses "id"
        raw_item_id = row["id"]

        try:
            quantity = int(row["quantity"])
        except (ValueError, TypeError):
            reject_row(row,"order_items",f"quantity not an integer: '{row['quantity']}'")

            continue

        if quantity <= 0:

            reject_row(row,"order_items","quantity must be > 0  (CHECK constraint)")

            continue

        raw_order_id = row["order_id"]

        raw_product_id = row["product_id"]

        try:

            database_order_id = (order_id_map.get(int(raw_order_id)) if pd.notna(raw_order_id) else None)

            database_product_id = (product_id_map.get(int(raw_product_id))if pd.notna(raw_product_id)else None)

        except (ValueError, TypeError):

            reject_row(row,"order_items", "order_id or product_id is not numeric")

            continue

        if database_order_id is None:

            reject_row(row,"order_items",f"order_id {raw_order_id} does not exist or was rejected (orphan FK)")

            continue

        if database_product_id is None:

            reject_row(row,"order_items",f"product_id {raw_product_id} does not exist or was rejected (orphan FK)"
            )

            continue

        row = row.copy()

        row["quantity"] = quantity

        row["order_id"] = (database_order_id)

        row["product_id"] = (database_product_id)

        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)

    load_data(clean,"order_items",raw_id_column="id",
        # PostgreSQL columns
        columns=[
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "discount_percentage"
        ]
    )

    # Recalculate order totals
    if not clean.empty:
        with engine.begin() as connection:
            connection.execute(
                text("""UPDATE orders AS orders_table
                        SET total_amount = totals.total
                    FROM (SELECT order_id,ROUND(SUM(quantity* unit_price* (1- discount_percentage/ 100.0)),2) AS total
                          FROM order_items
                          GROUP BY order_id) AS totals
                          WHERE orders_table.id = totals.order_id"""))
        print("  -> Recalculated orders.total_amount from order_items")
    print(f"  order_items: {len(clean)} valid /{total_rows} total")


# load the payments data from the csv and send load data to load the data in the database 
def process_payments(order_id_map):
    print("Processing payments_raw.csv...")
    df = pd.read_csv(SCRIPT_DIR / "payments_raw.csv")
    total_rows = len(df)
    valid_rows = []
    seen_payments = set()
    for _, row in df.iterrows():
        # IMPORTANT:
        # Raw payments CSV uses "id"
        raw_payment_id = row["id"]
        payment_key = (row["order_id"],row["amount"],row["method"],row.get("payment_date"))
        if payment_key in seen_payments:
            reject_row(row,"payments","duplicate payment row")

            continue

        if pd.isna(row["amount"]):

            reject_row(row,"payments",f"amount missing or non-numeric (raw: '{row['amount']}')")
            continue
        amount = float(row["amount"])
        if amount <= 0:
            reject_row(row,"payments","amount must be > 0 (CHECK constraint)")
            continue
        method = (str(row["method"]).strip().lower())
        if method not in ALLOWED_PAYMENT_METHOD:
            reject_row(row,"payments",f"invalid payment method: '{method}'")
            continue
        raw_order_id = row["order_id"]
        try:
            database_order_id = (order_id_map.get(int(raw_order_id))
                if pd.notna(raw_order_id)
                else None
            )
        except (ValueError, TypeError):
            reject_row(row,"payments",f"order_id not numeric:'{raw_order_id}'"
            )
            continue
        if database_order_id is None:
            reject_row(row,"payments",f"order_id {raw_order_id} does not exist or was rejected (orphan FK)")
            continue

        seen_payments.add(payment_key)
        row = row.copy()
        row["amount"] = amount
        row["method"] = method
        row["order_id"] = (database_order_id)

        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)

    load_data(clean,"payments",raw_id_column="id",
        # PostgreSQL columns
        columns=[
            "order_id",
            "amount",
            "payment_date",
            "method"
        ]
    )

    print(f"  payments: {len(clean)} valid /{total_rows} total")

if __name__ == "__main__":
    try:
        customer_id_map = process_customers()
        product_id_map = process_products()
        order_id_map = process_orders(customer_id_map)
        process_order_items(order_id_map,product_id_map)
        process_payments(order_id_map)
    finally:
        if rejected_rows:
            pd.DataFrame(rejected_rows).to_csv("rejected_records.csv",index=False)
            print(f"\n{len(rejected_rows)} rows rejected -> written to rejected_records.csv" )
        else:
            print("\nNo rejected rows.")
    print("\nExtract & Load complete.")