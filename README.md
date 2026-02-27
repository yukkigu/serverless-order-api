# Serverless Order API

## Project Overview

A Cloud Order Service that implements

- Idempotency
- Retries
- Eventual Consistency

The service ensures exactly-once effects even when the same request is being sent multiple times using idempotency to handle duplicated requests and request IDs to trace and track requests.

Built with FastAPI and SQLite, deployed on AWS EC2.

## Project Structure

```bash
serverless-order-api/
├── app/
│   ├── main.py        # FastAPI app, endpoints
│   ├── database.py    # SQLite connection, queries
│   ├── schemas.py     # Pydantic models
│   └── logger.py      # Structured JSON logging
├── requirements.txt
└── README.md
```

## Setup

### Prerequisites

- Python 3.12

### To run locally:

```bash
# navigate to directory with zip file and unzip
unzip serverless-order-api.zip
cd serverless-order-api

# create and activate local virtual environment
python3 -m venv venv
source venv/bin/activate

# install dependencies
pip install -r requirements.txt

# run app
uvicorn app.main:app --reload

# App will be available at `http://localhost:8000`
```

## Deployment Instructions

### 1. Create new Instance

#### Deployment Specifications

The app is deployed and launched on an EC2 instance.

- AMI: Ubuntu Server 24.04
- EC2 instance type: t3.micro

Security Group Configuration:
|Type|Protocol|Port|Source|
|----|-------|-----|-----|
|SSH|TCP|22|My IP|
|Custom TCP|TCP|8000|Anywhere(0.0.0.0/0)|

Port configuration: 8000

```bash
http://18.118.254.211:8000
```

### 2. Save Public IP and `.pem` file

Usually under Public IPv4 address

```bash
# Example IP
Public IP: 18.118.254.211

# .pem file should be downloaded after creating instance
key-file.pem
```

### 3. Connect to EC2

```bash
chmod 400 ~/PATH/TO/FILE/<file-name>.pem

ssh -i "~/PATH/TO/FILE/<file-name>.pem" ubuntu@<Public-IP-address>

# Example:
chmod 400 ~/PATH/TO/FILE/key-file.pem
ssh -i "~/PATH/TO/FILE/key-file.pem" ubuntu@18.118.254.211
```

### 4. Install dependencies in EC2

```bash
# Update packages
sudo apt update

# install python and pip
sudo apt install python3-pip python3-venv -y
```

### 5. Transfer local code to EC2

```bash
# On local terminal:
scp -i "C:/FILE/PATH/key-file.pem" -r \
 "C:/PROJECT/PATH/<project-name>" \
 ubuntu@<Public-IP-address>:~/<project-name>
```

### 6. Set up Virtual Environment

```bash
# Navigate to project
cd ~/<project-name>

# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 7. Start App and Run Server

```bash
# Install tmux
sudo apt install tmux -y

# Start a new session called "orderapi"
tmux new -s orderapi

# Run the app inside tmux
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Detach from tmux (keeps running after disconnect)
# Press: Ctrl + B, then D

# To reconnect again:
tmux attach -t orderapi
```

## API Endpoints

| Method | Endpoint             | Description             |
| ------ | -------------------- | ----------------------- |
| `POST` | `/orders`            | Create a new order      |
| `GET`  | `/orders/{order_id}` | Retrieve an order by ID |

### Headers

| Header                      | Description            |
| --------------------------- | ---------------------- |
| `Idempotency-Key`           | Unique key per request |
| `Content-Type`              | `application/json`     |
| `X-Debug-Fail-After-Commit` | Failure Simulation     |

## Verification

### Step 1 - Basic Order Creation

```bash
curl -i -X POST http://18.118.254.211:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-123" \
  -d '{"customer_id":"cust1","item_id":"item1","quantity":1}'
```

Save the `order_id` for order `/GET` request later

Expected Behavior:

- HTTP `201 Created`
- JSON response containing:
  - `order_id`
  - `status: "created"`

#### Orders.db

| Customer ID | Item ID | Quantity | Orders | Ledger | Idempotency Key |
| ----------- | ------- | -------- | ------ | ------ | --------------- |
| cust1       | item1   | 1        | 1      | 1      | test-123        |

### Step 2 - Retry Same Key

```bash
curl -i -X POST http://18.118.254.211:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-123" \
  -d '{"customer_id":"cust1","item_id":"item1","quantity":1}'
```

Expected behavior (idempotency):

- Same HTTP status code as Step 1
- Same response body
- Same `order_id`
- No duplicate order created

#### Orders.db

| Customer ID | Item ID | Quantity | Orders | Ledger | Idempotency Key |
| ----------- | ------- | -------- | ------ | ------ | --------------- |
| cust1       | item1   | 1        | 1      | 1      | test-123        |

### Step 3 - 409 Conflict

```bash
curl -i -X POST http://18.118.254.211:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-123" \
  -d '{"customer_id":"cust1","item_id":"item1","quantity":5}'
```

Expected behavior:

- HTTP `409 Conflict`
- No new order created
- No database modifications

#### Orders.db

| Customer ID | Item ID | Quantity | Orders | Ledger | Idempotency Key |
| ----------- | ------- | -------- | ------ | ------ | --------------- |
| cust1       | item1   | 1        | 1      | 1      | test-123        |

### Step 4 - Simulated Failure

```bash
curl -i -X POST http://18.118.254.211:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-fail-1" \
  -H "X-Debug-Fail-After-Commit: true" \
  -d '{"customer_id":"cust2","item_id":"item2","quantity":1}'
```

Expected behavior:

- HTTP 500 or timeout
- The order and ledger write must have already been committed

```bash
# to check in EC2, run:
sqlite3 ~/serverless-order-api/orders.db "SELECT orders.order_id, orders.customer_id, ledger.ledger_id FROM orders JOIN ledger ON orders.order_id = ledger.order_id;"
```

#### Orders.db

| Customer ID | Item ID | Quantity | Orders | Ledger | Idempotency Key |
| ----------- | ------- | -------- | ------ | ------ | --------------- |
| cust1       | item1   | 1        | 1      | 1      | test-123        |
| cust2       | item2   | 1        | 2      | 2      | test-fail-1     |

### Step 5 - Retry After Failure

```bash
curl -i -X POST http://18.118.254.211:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-fail-1" \
  -d '{"customer_id":"cust2","item_id":"item2","quantity":1}'
```

Expected behavior:

- HTTP `201 Created`
- Valid `order_id`
- Only one order and one ledger entry exist

```bash
# to check in EC2, run:
sqlite3 ~/serverless-order-api/orders.db "SELECT orders.order_id, orders.customer_id, ledger.ledger_id FROM orders JOIN ledger ON orders.order_id = ledger.order_id;"
```

#### Orders.db

| Customer ID | Item ID | Quantity | Orders | Ledger | Idempotency Key |
| ----------- | ------- | -------- | ------ | ------ | --------------- |
| cust1       | item1   | 1        | 1      | 1      | test-123        |
| cust2       | item2   | 1        | 2      | 2      | test-fail-1     |

### Step 6 - GET Order (use order_id from Step 0)

```bash
curl http://18.118.254.211:8000/orders/<order_id>
```

Expected behavior:

- Order is retrievable
- Only one order exists for that key

```json
// Expected return
{
  "order_id": "<id_num>",
  "customer_id": "cust1",
  "item_id": "item1",
  "quantity": 1,
  "status": "created"
}
```

### Database Verification — No Duplicates

```bash
# SSH into EC2 and run:
sqlite3 ~/serverless-order-api/orders.db "SELECT COUNT(*) FROM orders;"
sqlite3 ~/serverless-order-api/orders.db "SELECT COUNT(*) FROM ledger;"
sqlite3 ~/serverless-order-api/orders.db "SELECT orders.order_id, orders.customer_id, ledger.ledger_id FROM orders JOIN ledger ON orders.order_id = ledger.order_id;"
```
