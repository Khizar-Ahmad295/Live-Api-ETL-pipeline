import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

# Creating Database connection
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

password = quote_plus(os.getenv("DB_PASSWORD"))

DATABASE_URL = (
    f"postgresql+psycopg2://{os.getenv('DB_USER')}:{password}@"
    f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=2)


# Revenue per product category
def get_revenue_by_category():
    query = text("""
        SELECT
            p.category,
            ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_percentage / 100)), 2) AS total_revenue
        FROM products p
        JOIN order_items oi ON p.id = oi.product_id
        JOIN orders o ON oi.order_id = o.id
        WHERE o.status != 'cancelled'
        GROUP BY p.category
        ORDER BY total_revenue DESC;
    """)
    return pd.read_sql(query, engine)


# Top 5 customers by spending
def get_top_customers():
    query = text("""
        SELECT
            c.id AS customer_id,
            c.name,
            c.email,
            ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_percentage / 100)), 2) AS total_spend
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        JOIN order_items oi ON o.id = oi.order_id
        WHERE o.status != 'cancelled'
        GROUP BY c.id, c.name, c.email
        ORDER BY total_spend DESC
        LIMIT 5;
    """)
    return pd.read_sql(query, engine)


# Orders count by status
def get_orders_by_status():
    query = text("""
        SELECT
            status,
            COUNT(*) AS order_count,
            CASE
                WHEN status = 'delivered' THEN 'Completed'
                WHEN status = 'cancelled' THEN 'Not Completed'
                WHEN status IN ('pending', 'processing') THEN 'In Progress'
                WHEN status = 'shipped' THEN 'In Transit'
            END AS status_group
        FROM orders
        GROUP BY status
        ORDER BY order_count DESC;
    """)
    return pd.read_sql(query, engine)


# Month-over-month revenue
def get_monthly_revenue():
    query = text("""
        WITH monthly_sales AS (
            SELECT
                DATE_TRUNC('month', o.order_date) AS month,
                SUM(oi.quantity * oi.unit_price * (1 - oi.discount_percentage / 100)) AS revenue
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            WHERE o.status != 'cancelled'
            GROUP BY DATE_TRUNC('month', o.order_date)
        )
        SELECT
            month,
            ROUND(revenue, 2) AS revenue,
            ROUND(LAG(revenue) OVER (ORDER BY month), 2) AS previous_month_revenue,
            ROUND(revenue - LAG(revenue) OVER (ORDER BY month), 2) AS revenue_change
        FROM monthly_sales
        ORDER BY month;
    """)
    return pd.read_sql(query, engine)


def write_section(f, title, df):
    """Write one labeled table into the already-open CSV file, keeping its own real columns."""
    f.write(f"# {title}\n")
    df.to_csv(f, index=False)
    f.write("\n")


# Create final report
def create_report():
    print("Generating analytical report...")

    category_report = get_revenue_by_category()
    customer_report = get_top_customers()
    status_report = get_orders_by_status()
    monthly_report = get_monthly_revenue()

    output_file = BASE_DIR / "Task2 ETL Pipeline with Python/weekly_sales_report.csv"

    with open(output_file, "w", newline="") as f:
        write_section(f, "Revenue by Category", category_report)
        write_section(f, "Top 5 Customers by Spend", customer_report)
        write_section(f, "Orders by Status", status_report)
        write_section(f, "Month-over-Month Revenue", monthly_report)

    total_rows = (
        len(category_report)
        + len(customer_report)
        + len(status_report)
        + len(monthly_report)
    )

    print(f"Report created: {output_file}")
    print(f"Total rows: {total_rows}")


if __name__ == "__main__":
    create_report()
    print("Export report complete.")