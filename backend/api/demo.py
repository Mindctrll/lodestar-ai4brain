"""The "Demo" button: sign this browser in as the demo user (Alex, from `backend.db.seed`), seeding
them on first use. Off with LODESTAR_DEMO=0, for a deployment open to the public."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from backend.config import get_settings
from backend.contracts.views import CreatedUser
from backend.db.engine import get_engine
from backend.db.seed import demo_sign_in
from backend.db.seed_memory import seed_memory

router = APIRouter(tags=["users"])
log = logging.getLogger(__name__)


def _sign_in() -> tuple[CreatedUser, bool]:
    with get_engine().begin() as conn:
        user_id, token, created = demo_sign_in(conn)
    return CreatedUser(user_id=user_id, token=token), created


@router.post("/demo", response_model=CreatedUser)
async def post_demo(request: Request) -> CreatedUser:
    """A bearer token for the demo user, who has four months of practice to look around in."""
    if not get_settings().demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo is switched off here.")
    user, created = await run_in_threadpool(_sign_in)
    if created:
        services = getattr(request.app.state, "services", None)
        memory = getattr(services, "memory", None)
        try:
            if memory is not None:
                await seed_memory(user.user_id, memory)
        except Exception:
            log.warning("Demo memory notes skipped", exc_info=True)
    return user
