from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import json
import yaml
import os
from pathlib import Path
from contextlib import asynccontextmanager
import uvicorn
import tempfile
import subprocess
import shutil

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

# OpenAPI Diff endpoints
class OpenAPIDiffRequest(BaseModel):
    oldSpec: str
    newSpec: str


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


# Admin endpoints
@app.post("/api/regenerate-spec", tags=["Admin"])
async def regenerate_spec():
    """Manually trigger OpenAPI spec regeneration"""
    save_openapi_spec(app)
    return {
        "message": "OpenAPI spec regenerated",
        "files": {
            "json": str(SPECS_DIR / "openapi_new.json"),
            "yaml": str(SPECS_DIR / "openapi_new.yaml"),
            "old_json": str(SPECS_DIR / "openapi_old.json") if (SPECS_DIR / "openapi_old.json").exists() else None
        }
    }


@app.get("/api/spec-diff", tags=["Admin"])
async def get_spec_diff():
    """Get information about spec differences"""
    old_path = SPECS_DIR / "openapi_old.json"
    new_path = SPECS_DIR / "openapi_new.json"
    
    if not old_path.exists():
        return {"message": "No old spec found. Add/remove endpoints and restart to create diff."}
    
    try:
        with open(old_path) as f:
            old_spec = json.load(f)
        with open(new_path) as f:
            new_spec = json.load(f)
        
        # Simple comparison
        old_endpoints = set()
        new_endpoints = set()
        
        if "paths" in old_spec:
            old_endpoints = set(old_spec["paths"].keys())
        if "paths" in new_spec:
            new_endpoints = set(new_spec["paths"].keys())
        
        added = new_endpoints - old_endpoints
        removed = old_endpoints - new_endpoints
        
        return {
            "old_spec_exists": True,
            "new_spec_exists": True,
            "added_endpoints": list(added),
            "removed_endpoints": list(removed),
            "unchanged_endpoints": list(old_endpoints & new_endpoints),
            "message": f"Found {len(added)} added, {len(removed)} removed endpoints"
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/openapi-diff", tags=["OpenAPI Diff"])
async def openapi_diff(specs: OpenAPIDiffRequest):
    """
    Compare two OpenAPI specs using openapi-diff tool.
    Accepts old and new OpenAPI specs as strings (JSON or YAML).
    """
    
    old_spec = specs.oldSpec
    new_spec = specs.newSpec
    
    # Check if openapi-diff is available
    openapi_diff_cmd = shutil.which("openapi-diff")
    
    if not openapi_diff_cmd:
        # Fallback: Use Python-based diff
        return await openapi_diff_python(old_spec, new_spec)
    
    # Create temporary files
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f1:
        f1.write(old_spec)
        old_file = f1.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f2:
        f2.write(new_spec)
        new_file = f2.name
    
    try:
        # Run openapi-diff
        result = subprocess.run(
            [openapi_diff_cmd, old_file, new_file],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return {
            "diff": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "tool": "openapi-diff"
        }
    except subprocess.TimeoutExpired:
        return {"error": "Diff operation timed out"}
    except Exception as e:
        return {"error": str(e), "fallback": "Using Python-based diff"}
    finally:
        # Clean up temp files
        try:
            os.unlink(old_file)
            os.unlink(new_file)
        except:
            pass


async def openapi_diff_python(old_spec: str, new_spec: str):
    """Python-based fallback for OpenAPI diff"""
    from deepdiff import DeepDiff
    
    try:
        # Parse specs
        if old_spec.strip().startswith('{'):
            old_data = json.loads(old_spec)
        else:
            old_data = yaml.safe_load(old_spec)
        
        if new_spec.strip().startswith('{'):
            new_data = json.loads(new_spec)
        else:
            new_data = yaml.safe_load(new_spec)
        
        # Compare
        diff = DeepDiff(old_data, new_data, ignore_order=True, verbose_level=2)
        
        # Format results
        changes = {
            "added": [],
            "removed": [],
            "changed": []
        }
        
        if "dictionary_item_added" in diff:
            changes["added"] = list(diff["dictionary_item_added"])
        if "dictionary_item_removed" in diff:
            changes["removed"] = list(diff["dictionary_item_removed"])
        if "values_changed" in diff:
            changes["changed"] = [
                {
                    "path": key,
                    "old": str(value.get("old_value", "")),
                    "new": str(value.get("new_value", ""))
                }
                for key, value in diff["values_changed"].items()
            ]
        
        return {
            "diff": json.dumps(diff, indent=2, default=str),
            "changes": changes,
            "tool": "python-deepdiff",
            "summary": {
                "added_count": len(changes["added"]),
                "removed_count": len(changes["removed"]),
                "changed_count": len(changes["changed"])
            }
        }
    except Exception as e:
        return {"error": f"Failed to parse or compare specs: {str(e)}"}


# @app.post("/api/openapi-diff-files", tags=["OpenAPI Diff"])
# async def openapi_diff_from_files():
#     """
#     Compare OpenAPI specs from automatically generated files.
#     Uses openapi_specs/openapi_old.json and openapi_specs/openapi_new.json
#     """
#     old_file = SPECS_DIR / "openapi_old.json"
#     new_file = SPECS_DIR / "openapi_new.json"
    
#     if not old_file.exists():
#         raise HTTPException(status_code=404, detail="Old spec file not found. Start the app, modify it, and restart to generate old spec.")
    
#     if not new_file.exists():
#         raise HTTPException(status_code=404, detail="New spec file not found. Start the app to generate spec.")
    
#     # Read files
#     with open(old_file) as f:
#         old_spec = f.read()
    
#     with open(new_file) as f:
#         new_spec = f.read()
    
#     # Use the diff endpoint logic
#     request = OpenAPIDiffRequest(oldSpec=old_spec, newSpec=new_spec)
#     return await openapi_diff(request)



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)

