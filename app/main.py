# main.py

import uuid, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.schemas import OrderRequest, OrderResponse
from app.database import create_connection, create_tables
from app.database import hash_request_body, idempotency_check, store_idempotency_record, insert_order, get_order_by_id
from app.logger import log_info, log_error, log_debug, log_warning


# Initialize database connection, create tables on startup, and close connection on shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Set up the database connection and create tables on startup.
    Close the connection on shutdown.
    """
    # create database connection to orders.db 
    log_info("Creating database connection and tables...")
    db_file = "orders.db"
    conn = create_connection(db_file)
    # create tables if they don't exist
    create_tables(conn=conn)
    # store in database connection in app state for use in endpoints
    app.state.db_conn = conn
    log_info("Starting up the Order Management API...")
    
    yield
    # on shutdown, close the database connection
    log_info("Shutting down the Order Management API...")
    if conn:
        app.state.db_conn = None
        conn.close()
        log_info("Database connection closed.")

# Initialize FastAPI app with lifespan for startup and shutdown events
app = FastAPI(lifespan=lifespan)

# Set up a middleware to generate request_id for each request and log it
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Generate a unique request_id for each incoming request and log it for tracing.
    """
    # if request id exists in headers, use it, otherwise generate a new one
    request_id = request.headers.get("Request-ID")
    if request_id:
        log_info(f"Received Request-ID header: {request_id}")
        request.state.request_id = request_id
    else:
        # if request id does not exist, generate a new one
        request_id = str(uuid.uuid4())
        log_info("No Request-ID header found, generating a new request ID.", request_id=request_id)
        # save the generated request_id in request state
        request.state.request_id = request_id
        log_info(f"Request ID generated: {request_id}", request_id=request_id)

    log_info(f"Received request: {request.method} {request.url}", request_id=request_id)

    response = await call_next(request)
    # add the request_id to the response headers for tracking
    response.headers["Request-ID"] = request_id
    log_info(f"Completed request: {request.method} {request.url} with status {response.status_code}", request_id=request_id)
    return response

# API: /orders - POST to create a new order
@app.post("/orders")
def create_order(request: Request, order: OrderRequest):
    """
    Create a new order.

    CHECK:
      - Idempotency: Check if the same request exists.
      - Order_id: Check if the generated order_id already exists in the database to prevent duplicates.
    
    If the request is a duplicate (same idempotency key or order_id), return the saved response.
    Only create new order if idempotency key is unique and order_id does not exist in the database.
    """
    # extract idempotency key from headers
    idempotency_key = request.headers.get("Idempotency-Key")

    # if idempotency key is missing, return 400 error
    if not idempotency_key:
        log_error("Missing idempotency key in request headers.", request_id=request.state.request_id)
        raise HTTPException(status_code=400, detail="Missing idempotency key")
    
    # connect to database
    conn = request.app.state.db_conn
    # hash the request body for idempotency check
    hash_request = hash_request_body(order.model_dump())
    # check if idempotency key exists in database
    stored_response, stored_status_code, stored_request_hash = idempotency_check(
        idempotency_key=idempotency_key,
        conn=conn
    )
    # if record exists, check if request body hash matches
    if stored_response is not None:
        if stored_request_hash == hash_request:
            log_info("Idempotency key found with matching request body hash. Returning stored response.", request_id=request.state.request_id)
            return JSONResponse(content=json.loads(stored_response), status_code=stored_status_code)
        else:
            log_warning("Conflict Case: Same key, different payload. Idempotency key found but request body hash does not match.", request_id=request.state.request_id)
            raise HTTPException(status_code=409, detail="Conflict Case: Same key, different payload.")
    
    # if no record exists for the idempotency key, proceed with creating the order
    log_info("No existing idempotency record found. Creating new order.", request_id=request.state.request_id)
    try:
        # insert into order and ledger tables
        order_id=str(uuid.uuid4())  # generate a unique order_id
        insert_order(
            order_id=order_id,
            customer_id=order.customer_id,
            item_id=order.item_id,
            quantity=order.quantity,
            status="created",
            idempotency_key=idempotency_key,
            conn=conn
        )
        # store in idempotency records table
        store_idempotency_record(
            idempotency_key=idempotency_key,
            request_body_hash=hash_request,
            response_body={"order_id": order_id, "status": "created"},
            status_code=201,
            conn=conn
        )

        # commit the transaction to save changes to the database
        conn.commit()

        response = {"order_id": order_id, "status": "created"}
        
    except Exception as e:
        conn.rollback()  # rollback the transaction in case of error
        log_error(f"Error creating order: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
    # Failure simulation
    debug_key = request.headers.get("X-Debug-Fail-After-Commit")
    if debug_key == "true":
        log_error("Failure simulation: Order has timed out after commit", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Simulated Failure:Internal Server Error")
    
    return JSONResponse(content=response, status_code=201)

# API: /orders/{order_id} - GET to read a specific order
@app.get("/orders/{order_id}")
def read_order(request: Request, order_id: str):
    """
    Retrieve a specific order by order_id.
    """
    try:
        # connect to database
        conn = request.app.state.db_conn
        log_info(f"Reading order: {order_id}", request_id=request.state.request_id)
        # read order details from database
        order_details = get_order_by_id(order_id=order_id, conn=conn)
    except Exception as e:
        # if error occurs while reading from database, log the error and return 500 error
        log_error(f"Error reading order: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error.")
    
    # if order not found, return 404 error
    if order_details is None:
        log_warning("Order not found", request_id=request.state.request_id)
        raise HTTPException(status_code=404, detail="Order not found.")

    # if order found, return the order details in the response
    response = {
        "order_id": order_details[0],
        "customer_id": order_details[1],
        "item_id": order_details[2],
        "quantity": order_details[3],
        "status": order_details[4]
    }
    return JSONResponse(content=response, status_code=200)
