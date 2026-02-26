# schemas.py 

from pydantic import BaseModel, Field

# Pydantic models for request and response

class OrderRequest(BaseModel):
    # Fields that client sends in Request
    customer_id: str = Field(..., examples=["cust-42"])
    item_id: str = Field(..., examples=["item-9"])
    quantity: int = Field(..., ge=1, examples=[1])

class OrderResponse(BaseModel):
    # Fields that appear in Response body
    order_id: str = Field(..., examples=["abc123"])
    status: str = Field(..., examples=["created"])