from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import json
import yaml
import os
from pathlib import Path
from contextlib import asynccontextmanager
import uvicorn

# Directory for storing OpenAPI specs
SPECS_DIR = Path("openapi_specs")
SPECS_DIR.mkdir(exist_ok=True)


def save_openapi_spec(app: FastAPI):
    """Automatically save OpenAPI spec to JSON and YAML files"""
    openapi_schema = app.openapi()
    
    # Save current spec as 'new'
    new_json_path = SPECS_DIR / "openapi_new.json"
    new_yaml_path = SPECS_DIR / "openapi_new.yaml"
    
    # If 'new' exists, rename it to 'old'
    old_json_path = SPECS_DIR / "openapi_old.json"
    old_yaml_path = SPECS_DIR / "openapi_old.yaml"
    
    if new_json_path.exists():
        # Backup current 'new' to 'old'
        if old_json_path.exists():
            old_json_path.unlink()
        new_json_path.rename(old_json_path)
        
        if old_yaml_path.exists():
            old_yaml_path.unlink()
        new_yaml_path.rename(old_yaml_path)
    
    # Save new spec
    with open(new_json_path, "w") as f:
        json.dump(openapi_schema, f, indent=2)
    
    with open(new_yaml_path, "w") as f:
        yaml.dump(openapi_schema, f, default_flow_style=False, sort_keys=False)
    
    print(f"✅ OpenAPI spec automatically saved:")
    print(f"   - {new_json_path}")
    print(f"   - {new_yaml_path}")
    if old_json_path.exists():
        print(f"   - Previous version saved as: {old_json_path}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Automatically save OpenAPI spec
    save_openapi_spec(app)
    yield
    # Shutdown (if needed)


app = FastAPI(
    title="Test API",
    description="Minimal FastAPI app for OpenAPI diff testing",
    version="1.0.0",
    lifespan=lifespan
)


class Item(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float


class ItemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float


class ItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float


# In-memory storage
items_db = []
next_id = 1


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {"message": "Welcome to Test API"}


@app.get("/items", response_model=List[ItemResponse], tags=["Items"])
async def get_items():
    """Get all items"""
    return items_db


@app.get("/items/{item_id}", response_model=ItemResponse, tags=["Items"])
async def get_item(item_id: int):
    """Get a specific item by ID"""
    item = next((item for item in items_db if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.post("/items", response_model=ItemResponse, tags=["Items"])
async def create_item(item: ItemCreate):
    """Create a new item"""
    global next_id
    new_item = {
        "id": next_id,
        "name": item.name,
        "description": item.description,
        "price": item.price
    }
    items_db.append(new_item)
    next_id += 1
    return new_item


@app.delete("/items/{item_id}", tags=["Items"])
async def delete_item(item_id: int):
    """Delete an item by ID"""
    global items_db
    item = next((item for item in items_db if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    items_db = [item for item in items_db if item["id"] != item_id]
    return {"message": "Item deleted successfully"}



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)

