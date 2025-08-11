from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.routes import router as api_router
from app.logging_config import configure_logging
from app.services.rabbit import get_connection_manager

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    rabbit_manager = get_connection_manager()
    await rabbit_manager.connect()
    # Start consumers as background tasks
    await rabbit_manager.start_consumers()
    yield
    # Shutdown
    await rabbit_manager.close()


app = FastAPI(title="VR Notification System", version="0.1.0", lifespan=lifespan)
app.include_router(api_router, prefix="/api")

configure_logging()
