import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine,text
from sqlalchemy.dialects.postgresql import JSONB

#Creating connection with postgresql

load_dotenv()

Database_URL=(f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}" f"@{os.getenv("DB_HOST")}:{os.getenv('DB_PORT')/{os.getenv('DB_NAME')}}")

#sqlconnection created
engine=create_engine(Database_URL,poolsize=5,max_overflow=2)

rejected_rows=[] #every rejected row stored here

ALLOWED_ORDER_STATUS = {"pending", "processing", "shipped", "delivered", "cancelled"}
ALLOWED_PAYMENT_METHOD = {"cash", "card", "bank_transfer", "online"}

# adding rejected rows to the list
def rejected(df_row,source_table,reason):
    row=df_row.to_dict()
    row["souce_table"]=source_table
    row["rejection_reason"]=reason
    rejected_rows.append(row)

# method for loading data in database POSTgres and returning a dict mapping

def load_and_map(clean_df,table_name,src_id_col,load_cols,dtype=None):
    if clean_df.empty:
        print(f" -> nothing valid to load into {table_name}")
        return {}
    with engine.connect() as conn:
        result=conn.excecute(text(f"SELECT COALESCE(MAX(id),0) FROM {table_name}"))
        start_id=result.scalar()
    to_insert=clean_df[load_cols]
    to_insert.to_sql(table_name,engine,if_exists="append",index=False,dtype=dtype)
    
    new_ids=range(start_id+1,start_id+1+len(clean_df))
    id_map=dict(zip(clean_df[src_id_col],new_ids))

    print(f" -> loaded {len(clean_df)} rows into {table_name}")
    
    return id_map
    
# Creating the Customer inserting method

def process_customers():
    print("Processing customers_raw.csv ...")
    df=pd.read_csv("customers_raw.csv")
    before=len(df)
    
    dupes=df[df.duplicated(keep="first")]
    
    for _,row in dupes.iterrows():
        rejected(row,"customers","exact duplicate row")
        
    df=df.drop_duplicates(keep="first")
    # check for valid_rows and adding set to check for email already exist in csv or not for knowing duplicated email
    valid_rows=[]
    seen_emails=set()
    
    for _,row in df.iterrows():
        name=str(row["name"]).strip() if pd.notna(row["name"]) else ""
        email=str(row["email"]).strip() if pd.notna(row["email"]) else ""
        
        if not name:
            rejected(row,"customers","missing required field: name")
            continue
        
        if not email:
            rejected(row,"customers","missing required field: email")
            continue
        
        if "@" not in email:
            rejected(row,"customers","invalid email format")
            continue
        if email in seen_emails:
            rejected(row,"customers","duplicate email (violates UNIQUE constraint)")
            continue
        
        phone=str(row["phone"]) if pd.notna(row["phone"]) else""
        if len(phone)>20:
            rejected(row,"customers",f"phone exceeds VARCHAR(20) limit: '{phone}'")
            continue
        
        seen_emails.add(email)
        valid_rows.append(row)
        
    clean=pd.DataFrame(valid_rows)
    
    id_map=load_and_map(clean,"customers",src_id_col="customer_id",
                            load_cols=["name","email","phone","address","created_at"],
                            dtype={"address":JSONB})
    
    print(f" customers:{len(clean)} valid/{before} total")
    
    return id_map
# method for loading products and clean the data for sending to load and map process
def process_products():
    print("Processing products_raw.csv ...")
    df = pd.read_csv("products_raw.csv")
    before = len(df)

    valid_rows = []
    for _, row in df.iterrows():
        title = str(row["title"]).strip() if pd.notna(row["title"]) else ""
        if not title:
            rejected(row, "products", "missing required field: title")
            continue

        if pd.isna(row["price"]):
           
            rejected(row, "products", f"price missing or non-numeric (raw: '{row['price']}')")
            continue
        price = float(row["price"])
        if price < 0:
            rejected(row, "products", "negative price violates CHECK constraint")
            continue

        row = row.copy()
        row["price"] = price
        valid_rows.append(row)

    clean = pd.DataFrame(valid_rows)
    if not clean.empty:
        clean["brand"] = clean["brand"].replace("", None)
        clean["availability_status"] = clean["stock_quantity"].apply(
            lambda q: "Low Stock" if pd.notna(q) and q < 10 else "In Stock"
        )

    id_map = load_and_map(
        clean, "products", src_id_col="product_id",
        load_cols=["title", "description", "category", "brand", "price",
                   "discount_percentage", "stock_quantity", "rating",
                   "availability_status", "minimum_order_quantity", "created_at"],
    )
    print(f"  products: {len(clean)} valid / {before} total")
    return id_map



# method for loading orders and clean the data for sending to load and map process

def process_orders(customer_id_map):
    print("Processing orders_raw.csv")
    
    df=pd.read_csv("orders_raw.csv")
    
    before=len(df)
    
    valid_rows=[]
    
    for _,row in df.iterrows():
        raw_cust_id=row["customer_id"]
        if pd.isna(raw_cust_id) or str(raw_cust_id).strip()=="":
            rejected(row,"orders","missing required field: customer_id")
    
        try:
            raw_cust_id=int(raw_cust_id)
        except (ValueError,TypeError):
            rejected(row,"orders",f"customer_id not numeric: '{raw_cust_id}'")
            continue
        
        status=str(row["status"]).strip().lower()
        
        if status not in ALLOWED_ORDER_STATUS:
            rejected(row,"orders",f"invalid status value: '{status}'")
            continue
        
        db_cust_id=customer_id_map.get(raw_cust_id)
        if db_cust_id is None:
            rejected(row,"orders",f"customer_id {raw_cust_id} does not exist or was rejected (orphan FK)")
            continue
        
        row=row.copy()
        row["customer_id"]=db_cust_id
        row["status"]=status
        row["total_amount"]=0.0 #placeholder updated after loading the other orderitems data
        valid_rows.append(row)
        
        clean=pd.DataFrame(valid_rows)
        id_map=load_and_map(
            clean,"orders",src_id_col="order_id",
            load_cols=["customer_id","order_date","status","total_amount"],
            
        )
        print(f"orders:{len(clean)} valid/{before} total")
        return id_map
    
# method for loading order_items and clean the data for sending to load and map process

def process_order_items(order_id_map,product_id_map):
    print("Processing order_items_raw.csv...")
    df=pd.read_csv("order_items_raw.csv")
    
    before=len(df)
    
    valid_rows=[]
    
    for _,row in df.iterrows():
        try:
            qty=int(row["quantity"])
        except (ValueError,TypeError):
            rejected(row,"order_items",f"quantity not an integer: '{row['quantity']}'")
            continue
        
        if qty<=0:
            rejected(row,"order_items",f"quantity must be > 0 (CHECK constraint)")
            continue
        
        raw_order_id=row["order_id"]
        raw_product_id=row["product_id"]
        
        db_order_id=order_id_map.get(int(raw_order_id)) if pd.notna(raw_order_id) else None
        
        db_product_id=product_id_map.get(int(raw_product_id)) if pd.notna(raw_product_id) else None
        
        if db_order_id is None:
            rejected(row, "order_items", f"order_id {raw_order_id} does not exist or was rejected (orphan FK)")
            continue
        if db_product_id is None:
            rejected(row, "order_items", f"product_id {raw_product_id} does not exist or was rejected (orphan FK)")
            continue
        
        row=row.copy()
        row["quantity"]=qty
        row["order_id"]=db_order_id
        row["product_id"]=db_product_id
        valid_rows.append(row)
        
        clean=pd.DataFrame(valid_rows)
        
        load_and_map(clean,"order_items",src_id_col="item_id",load_cols=["order_id","product_id","quantity","unit_price","discount_percentage"],)
        
        if not clean.empty:
            # oder_items are loaded with 0.0 total_amount placeholder on 
            # orders - so now we will recompute the real toatl from the line items now.
            
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE orders o
                    SET total_amount = sub.total
                    FROM (
                        SELECT order_id,
                            ROUND(SUM(quantity * unit_price * (1 - discount_percentage / 100.0)), 2) AS total
                        FROM order_items
                        GROUP BY order_id
                    ) sub
                    WHERE o.id = sub.order_id
                """))
        print("  -> recalculated orders.total_amount from order_items")
 
    print(f"  order_items: {len(clean)} valid / {before} total")
 
# method for loading payments.csv and clean the data for sending to load and map process this method also need order table id map

def process_payments(order_id_map):
    print("Processing payments_raw.csv ...")
    df = pd.read_csv("payments_raw.csv")
    before = len(df)
 
    seen = set()
    valid_rows = []
    for _, row in df.iterrows():
        key = (row["order_id"], row["amount"], row["method"])
        if key in seen:
            rejected(row, "payments", "duplicate payment row")
            continue
 
        if pd.isna(row["amount"]):
            rejected(row, "payments", f"amount missing or non-numeric (raw: '{row['amount']}')")
            continue
        amount = float(row["amount"])
        if amount <= 0:
            rejected(row, "payments", "amount must be > 0 (CHECK constraint)")
            continue
 
        method = str(row["method"]).strip().lower()
        if method not in ALLOWED_PAYMENT_METHOD:
            rejected(row, "payments", f"invalid payment method: '{method}'")
            continue
 
        raw_order_id = row["order_id"]
        db_order_id = order_id_map.get(int(raw_order_id)) if pd.notna(raw_order_id) else None
        if db_order_id is None:
            rejected(row, "payments", f"order_id {raw_order_id} does not exist or was rejected (orphan FK)")
            continue
 
        seen.add(key)
        row = row.copy()
        row["amount"] = amount
        row["method"] = method
        row["order_id"] = db_order_id
        valid_rows.append(row)
 
    clean = pd.DataFrame(valid_rows)
    load_and_map(
        clean, "payments", src_id_col="payment_id",
        load_cols=["order_id", "amount", "payment_date", "method"],
    )
    print(f"  payments: {len(clean)} valid / {before} total")
 
 
# =================================================================
# MAIN
# =================================================================
if __name__ == "__main__":
    customer_id_map = process_customers()
    product_id_map = process_products()
    order_id_map = process_orders(customer_id_map)
    process_order_items(order_id_map, product_id_map)
    process_payments(order_id_map)
 
    if rejected_rows:
        pd.DataFrame(rejected_rows).to_csv("rejected_records.csv", index=False)
        print(f"\n{len(rejected_rows)} rows rejected -> written to rejected_records.csv")
    else:
        print("\nNo rejected rows.")
 
    print("\nExtract & Load complete.")
 