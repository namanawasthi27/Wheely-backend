from fastapi import FastAPI
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from datetime import datetime
from bson import ObjectId
import os

load_dotenv()

app = FastAPI()

MONGO_URI = os.getenv("MONGO_URI")
print("MONGO_URI:", MONGO_URI)   # <-- Add this line

from pymongo.server_api import ServerApi
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(
    MONGO_URI,
    server_api=ServerApi("1")
)
db = client["wheely"]  # this is your database name

drivers_collection = db["drivers"]
customers_collection = db["customers"]
bookings_collection = db["bookings"]


# ---------- Models ----------

class Driver(BaseModel):
    id: int
    name: str
    hourly_rate: int
    is_available: bool

class DriverCreate(BaseModel):
    name: str
    hourly_rate: int
    is_available: bool = True


class Customer(BaseModel):
    id: str
    name: str
    phone: str

class CustomerCreate(BaseModel):
    name: str
    phone: str


class BookingCreate(BaseModel):
    customer_id: str
    driver_id: str
    hours_requested: int   # how many hours the customer wants to book

class StatusUpdate(BaseModel):
    status: str     # expected values: "accepted", "ongoing", "completed", "cancelled"


# ---------- Routes ----------

@app.get("/")
def read_root():
    return {"message": "Wheely backend is running!"}


# ---------- Driver Routes ----------

# GET all drivers — reading from MongoDB
@app.get("/drivers")
async def get_all_drivers():
    drivers = []
    async for driver in drivers_collection.find():
        driver["_id"] = str(driver["_id"])  # convert MongoDB's ObjectId to a plain string
        drivers.append(driver)
    return drivers


# GET only available drivers
@app.get("/drivers/available")
async def get_available_drivers():
    drivers = []
    async for driver in drivers_collection.find({"is_available": True}):
        driver["_id"] = str(driver["_id"])
        drivers.append(driver)
    return drivers


# POST — create a new driver, saved into MongoDB
@app.post("/drivers")
async def create_driver(new_driver: DriverCreate):
    driver_dict = new_driver.dict()
    result = await drivers_collection.insert_one(driver_dict)
    driver_dict["_id"] = str(result.inserted_id)
    return driver_dict


# ---------- Customer Routes ----------

@app.post("/customers")
async def create_customer(new_customer: CustomerCreate):
    customer_dict = new_customer.dict()
    result = await customers_collection.insert_one(customer_dict)
    customer_dict["_id"] = str(result.inserted_id)
    return customer_dict


@app.get("/customers")
async def get_all_customers():
    customers = []
    async for customer in customers_collection.find():
        customer["_id"] = str(customer["_id"])
        customers.append(customer)
    return customers


# ---------- Booking Routes ----------

@app.post("/bookings")
async def create_booking(new_booking: BookingCreate):
    # Find the driver to get their hourly rate
    driver = await drivers_collection.find_one({"_id": ObjectId(new_booking.driver_id)})

    if not driver:
        return {"error": "Driver not found"}

    if not driver["is_available"]:
        return {"error": "Driver is not available"}

    estimated_amount = driver["hourly_rate"] * new_booking.hours_requested

    booking_dict = {
        "customer_id": new_booking.customer_id,
        "driver_id": new_booking.driver_id,
        "hours_requested": new_booking.hours_requested,
        "estimated_amount": estimated_amount,
        "status": "pending",     # pending -> accepted -> ongoing -> completed
        "created_at": datetime.utcnow().isoformat()
    }

    result = await bookings_collection.insert_one(booking_dict)
    booking_dict["_id"] = str(result.inserted_id)
    return booking_dict


@app.get("/bookings")
async def get_all_bookings():
    bookings = []
    async for booking in bookings_collection.find():
        booking["_id"] = str(booking["_id"])
        bookings.append(booking)
    return bookings

@app.get("/ping")
async def ping():
    try:
        await client.admin.command("ping")
        return {"message": "Connected to MongoDB"}
    except Exception as e:
        return {"error": str(e)}

@app.patch("/bookings/{booking_id}/status")
async def update_booking_status(booking_id: str, update: StatusUpdate):
    valid_statuses = ["pending", "accepted", "ongoing", "completed", "cancelled"]
    
    if update.status not in valid_statuses:
        return {"error": f"Invalid status. Must be one of {valid_statuses}"}

    booking = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return {"error": "Booking not found"}

    await bookings_collection.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"status": update.status}}
    )

    updated_booking = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    updated_booking["_id"] = str(updated_booking["_id"])
    return updated_booking

@app.patch("/bookings/{booking_id}/start")
async def start_trip(booking_id: str):
    booking = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return {"error": "Booking not found"}
    
    if booking["status"] != "accepted":
        return {"error": "Booking must be 'accepted' before starting the trip"}

    await bookings_collection.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {
            "status": "ongoing",
            "start_time": datetime.utcnow().isoformat()
        }}
    )

    updated = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    updated["_id"] = str(updated["_id"])
    return updated


@app.patch("/bookings/{booking_id}/end")
async def end_trip(booking_id: str):
    booking = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return {"error": "Booking not found"}

    if booking["status"] != "ongoing":
        return {"error": "Booking must be 'ongoing' before ending the trip"}

    driver = await drivers_collection.find_one({"_id": ObjectId(booking["driver_id"])})
    
    end_time = datetime.utcnow()
    start_time = datetime.fromisoformat(booking["start_time"])
    
    duration_hours = (end_time - start_time).total_seconds() / 3600
    final_amount = round(driver["hourly_rate"] * duration_hours, 2)

    await bookings_collection.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {
            "status": "completed",
            "end_time": end_time.isoformat(),
            "actual_duration_hours": round(duration_hours, 2),
            "final_amount": final_amount
        }}
    )

    updated = await bookings_collection.find_one({"_id": ObjectId(booking_id)})
    updated["_id"] = str(updated["_id"])
    return updated