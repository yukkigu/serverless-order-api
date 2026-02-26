# database.py

import hashlib
import json
from sqlite3 import connect, Connection

# Establish database connection
def create_connection(db_file: str) -> Connection:
    """ Create a database connection to the SQLite database specified by db_file. """
    conn = None
    try:
        conn = connect(db_file, check_same_thread=False)
        print(f"Connected to database: {db_file}")
    except Exception as e:
        print(f"Error connecting to database: {e}")
    return conn

# Create tables if it doesn't exist
def create_tables(conn: Connection):
    """ Create tables for orders, ledger, and idempotency key. """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY NOT NULL UNIQUE,
                customer_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL REFERENCES orders(order_id),
                customer_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key TEXT PRIMARY KEY NOT NULL UNIQUE,
                request_body_hash TEXT NOT NULL,
                response_body TEXT,
                status_code INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")

# Hash the request body for idempotency key storage
def hash_request_body(request_body: dict) -> str:
    """ Hash the request body to store in idempotency records. """
    # Convert the request body to a JSON string and hash it with sha256
    request_body_str = json.dumps(request_body, sort_keys=True)
    return hashlib.sha256(request_body_str.encode()).hexdigest()

# Implement idempotency key handling
def idempotency_check(idempotency_key: str, conn: Connection):
    """ Check if the same request has been processed before using an idempotency key. """
    cursor = conn.cursor()
    # check if the idempotency key exists in the idempotency_records table
    cursor.execute(
        "SELECT response_body, status_code, request_body_hash FROM idempotency_records WHERE idempotency_key = ?",
        (idempotency_key,),
    )
    # if record exists, return the cached response, status code, and request body hash
    record = cursor.fetchone()
    
    if record:
        # return cached response, status code, and request body hash
        return record[0], record[1], record[2] 
    else:
        # no record found, return none
        return None, None, None

# Store the response in the idempotency records table
def store_idempotency_record(idempotency_key: str, request_body_hash: str, response_body: dict, status_code: int, conn: Connection):
    """ Store the response in the idempotency records table. """
    cursor = conn.cursor()
    # insert record into idempotency_records table
    cursor.execute(
        """
        INSERT INTO idempotency_records (idempotency_key, request_body_hash, response_body, status_code)
        VALUES (?, ?, ?, ?)
        """,
        (idempotency_key, request_body_hash, json.dumps(response_body), status_code),
    )

# Insert order into orders table and ledger table
def insert_order(order_id: str, customer_id: str, item_id: str, quantity: int, status: str, idempotency_key: str, conn: Connection):
    """ Insert order into orders table and ledger table. """
    cursor = conn.cursor()
    # insert into orders table
    cursor.execute(
        """
        INSERT INTO orders (order_id, customer_id, item_id, quantity, status, idempotency_key)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (order_id, customer_id, item_id, quantity, status, idempotency_key),
    )
    # insert into ledger table
    cursor.execute(
        """
        INSERT INTO ledger (order_id, customer_id, quantity)
        VALUES (?, ?, ?)
        """,
        (order_id, customer_id, quantity),
    )

# Retrieve order details by order_id
def get_order_by_id(order_id: str, conn: Connection):
    """ Retrieve order details by order_id. """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT order_id, customer_id, item_id, quantity, status FROM orders WHERE order_id = ?",
        (order_id,),
    )
    return cursor.fetchone()