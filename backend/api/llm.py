"""Bring-your-own-key AI provider settings (docs/plan/02 API sketch; UW22)."""

from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.api.deps import Conn, CurrentUser, Engine, RegistryDep
from backend.contracts.common import Contract, ProviderId
from backend.contracts.llm import CredentialSummary, LlmSelection
from backend.db.consent_store import granted_switches
from backend.db.llm_store import (
    credential_summaries,
    delete_credential,
    get_credential,
    get_selection,
    save_credential,
    set_selection,
)
from backend.llm.factory import LlmFactory
from backend.llm.providers import KeyRejected, OutOfCredit, ProviderUnavailable, list_models
from backend.registry.models import Registry

router = APIRouter(prefix="/llm", tags=["llm"])


def llm_factory_dep() -> LlmFactory:
    raise RuntimeError("LlmFactory is provided by the app lifespan")  # pragma: no cover


Factory = Annotated[LlmFactory, Depends(llm_factory_dep)]


class ProviderView(Contract):
    id: ProviderId
    name: str
    hosting: str
    needs_key: bool
    default_model: str
    console_url: str | None
    notes: str | None


class LlmOverview(Contract):
    providers: list[ProviderView]
    credentials: list[CredentialSummary]
    selection: LlmSelection
    keys_enabled: bool = Field(description="False when the server has no master key")


class KeyInput(Contract):
    api_key: SecretStr = Field(min_length=8, max_length=400)
    model: str | None = None


class KeySaved(Contract):
    credential: CredentialSummary
    models: list[str]
    model: str


class SelectionInput(Contract):
    mode: Literal["hosted", "local"]
    provider: ProviderId
    model: str = Field(min_length=1, max_length=200)


async def _require_cloud_ai(engine: AsyncEngine, user_id: UUID, registry: Registry) -> None:
    """Nothing goes to a cloud provider, not even a key check, before Cloud AI is switched on
    (UW22: the consent screen names the provider and where it processes data)."""
    async with engine.connect() as conn:
        consent = await granted_switches(conn, user_id, registry.consent)
    if "cloud_ai" not in consent:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn on Cloud AI first.")


@router.get("/providers", response_model=LlmOverview)
async def get_providers(
    user_id: CurrentUser, conn: Conn, registry: RegistryDep, factory: Factory
) -> LlmOverview:
    providers = [
        ProviderView(
            id=p.id,
            name=p.name,
            hosting=p.hosting,
            needs_key=p.needs_key,
            default_model=factory.settings.local_model if p.id == "ollama" else p.default_model,
            console_url=str(p.console_url) if p.console_url else None,
            notes=p.notes,
        )
        for p in registry.providers
        if not p.hidden
    ]
    return LlmOverview(
        providers=providers,
        credentials=await credential_summaries(conn, user_id),
        selection=await get_selection(conn, user_id, factory.settings.local_model),
        keys_enabled=factory.vault.available,
    )


@router.put("/credentials/{provider_id}", response_model=KeySaved)
async def put_credential(
    provider_id: ProviderId,
    body: KeyInput,
    user_id: CurrentUser,
    engine: Engine,
    registry: RegistryDep,
    factory: Factory,
) -> KeySaved:
    provider = registry.provider(provider_id)
    if not provider.needs_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{provider.name} doesn't use a key.")
    await _require_cloud_ai(engine, user_id, registry)
    if not factory.vault.available:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Saving keys needs NAJMA_MASTER_KEY on the server.",
        )
    api_key = body.api_key.get_secret_value().strip()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            models = await list_models(provider, api_key, factory.api_base(provider_id), client)
    except KeyRejected as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That key didn't work. Check it and try again."
        ) from exc
    except OutOfCredit as exc:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, f"{provider.name} says this account has no credit."
        ) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{provider.name} couldn't be reached. Try again soon."
        ) from exc

    if body.model and body.model in models:
        model = body.model
    elif provider.default_model in models or not models:
        model = provider.default_model
    else:
        model = models[0]
    sealed = factory.vault.seal(user_id, provider_id, api_key)
    async with engine.begin() as conn:
        await save_credential(conn, user_id, provider_id, sealed, "ok")
        selection = LlmSelection(mode="hosted", provider=provider_id, model=model)
        await set_selection(conn, user_id, selection)
    return KeySaved(
        credential=CredentialSummary(provider=provider_id, key_last4=sealed.last4, status="ok"),
        models=models,
        model=model,
    )


@router.delete("/credentials/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_credential(
    provider_id: ProviderId, user_id: CurrentUser, engine: Engine, factory: Factory
) -> Response:
    local_model = factory.settings.local_model
    async with engine.begin() as conn:
        if not await delete_credential(conn, user_id, provider_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No key saved for that provider.")
        current = await get_selection(conn, user_id, local_model)
        if current.mode == "hosted" and current.provider == provider_id:
            local = LlmSelection(mode="local", provider="ollama", model=local_model)
            await set_selection(conn, user_id, local)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/selection", response_model=LlmSelection)
async def put_selection(
    body: SelectionInput,
    user_id: CurrentUser,
    engine: Engine,
    registry: RegistryDep,
    factory: Factory,
) -> LlmSelection:
    local_model = factory.settings.local_model
    if body.mode == "hosted":
        await _require_cloud_ai(engine, user_id, registry)
    async with engine.begin() as conn:
        if body.mode == "hosted":
            if await get_credential(conn, user_id, body.provider) is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Add a key for that provider first."
                )
            selection = LlmSelection(mode="hosted", provider=body.provider, model=body.model)
        else:
            selection = LlmSelection(mode="local", provider="ollama", model=local_model)
        await set_selection(conn, user_id, selection)
        return await get_selection(conn, user_id, local_model)
