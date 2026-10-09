"""The creator's package editor: dictate, save, publish and set a private floor.

A `PackageService` belongs to one creator and every operation is scoped to their
packages: another creator's package is `PackageNotFound`, never a permission error that
would confirm it exists. Only published packages feed the creator's search embedding, so
publishing (and editing a published package) refreshes it after the change is committed.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.core.money import format_cents
from app.core.package_rules import (
    draft_violations,
    merge_package_draft,
    missing_fields,
    patch_package_draft,
    terms_from_draft,
    validate_package,
)
from app.core.package_text import creator_embedding_document, text_hash
from app.modules.discovery.service import package_summary
from app.modules.packages import repo
from app.modules.packages.prompts import DRAFT_SYSTEM, draft_prompt
from app.schemas.my_packages import MyPackage, SavedPackage
from app.schemas.packages import (
    DraftFromSpeechRequest,
    DraftResult,
    ExtractedDraft,
    PackageDraft,
    PackageTerms,
    RuleViolation,
)

logger = logging.getLogger(__name__)

SEARCH_INDEX_PENDING = "search index update pending"

# The numeric fields the database refuses to store out of range (CHECK constraints and the
# 32-bit column). A draft that breaks them cannot be saved at all, unlike the other
# publishing rules, which only block publishing.
STORED_NUMBER_FIELDS = ("volume_count", "base_price_cents", "slots_per_month", "lead_time_days")
INT4_MAX = 2**31 - 1


class PackageNotFound(Exception):
    """No such package among this creator's packages."""


class DraftIncomplete(Exception):
    """Required fields have no value yet."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(", ".join(missing))
        self.missing = missing


class RulesViolated(Exception):
    """The package breaks rules that must be fixed before it can be saved or published."""

    def __init__(self, violations: list[RuleViolation]) -> None:
        super().__init__("; ".join(v.message for v in violations))
        self.violations = violations


class DraftUnavailable(Exception):
    """The model could not be reached, so the dictation could not be read."""


@dataclass(frozen=True)
class MyCreator:
    id: UUID
    name: str
    bio: str | None
    niches: list[str]


async def find_creator(db: Database, profile_id: UUID) -> MyCreator | None:
    """The creator row of a signed-in user."""
    async with db.acquire() as conn:
        row = await repo.creator_for_profile(conn, profile_id)
    return None if row is None else MyCreator(**row)


def _my_package(row: dict[str, Any]) -> MyPackage:
    terms = PackageTerms.model_validate(row)
    return MyPackage(
        **package_summary(row["id"], terms).model_dump(),
        status=row["status"],
        floor_price_cents=row["floor_price_cents"],
        currency=terms.currency,
        included=terms.included,
        freebies=terms.freebies,
        extras=terms.extras,
        slots_per_month=terms.slots_per_month,
    )


def _saved(row: dict[str, Any], warnings: list[str]) -> SavedPackage:
    return SavedPackage(**_my_package(row).model_dump(), warnings=warnings)


class PackageService:
    def __init__(self, db: Database, creator: MyCreator) -> None:
        self._db = db
        self._creator = creator

    async def list_packages(self) -> list[MyPackage]:
        """All of the creator's packages, drafts included, cheapest first."""
        async with self._db.acquire() as conn:
            rows = await repo.list_packages(conn, self._creator.id)
        return [_my_package(row) for row in rows]

    async def draft_from_speech(
        self, gemini: GeminiPort, req: DraftFromSpeechRequest
    ) -> DraftResult:
        """Fold what the creator just said into their open draft.

        A reply the model got wrong (not valid for the schema) changes nothing: the draft
        comes back as it was, with the transcript as `heard`. Raises `DraftUnavailable`
        when the model cannot be reached. Anything else, such as pydantic rejecting our
        own request schema, is a bug and propagates.
        """
        try:
            reply = await gemini.generate_structured(
                system=DRAFT_SYSTEM, prompt=draft_prompt(req), schema=ExtractedDraft
            )
        except GeminiInvalidOutput as exc:
            logger.warning("package draft reply unusable: %s", exc)
            return self._draft_result(req.current, heard=req.transcript)
        except GeminiUnavailable as exc:
            raise DraftUnavailable from exc
        draft = merge_package_draft(req.current, reply.draft)
        return self._draft_result(draft, heard=reply.heard.strip() or req.transcript)

    async def create(self, draft: PackageDraft) -> MyPackage:
        """Save a complete draft as a new unpublished package.

        Raises `DraftIncomplete`, or `RulesViolated` for numbers the database cannot store.
        Rules that only matter for publishing (such as the niche) are checked then.
        """
        if missing := missing_fields(draft):
            raise DraftIncomplete(missing)
        terms = terms_from_draft(draft)
        if violations := self._violations(terms, publishing=False):
            raise RulesViolated(violations)
        async with self._db.transaction() as conn:
            package_id = await repo.insert_package(conn, self._creator.id, terms)
            row = await self._load(conn, package_id)
        return _my_package(row)

    async def patch(
        self, gemini: GeminiPort, package_id: UUID, patch: PackageDraft
    ) -> SavedPackage:
        """Change the fields `patch` sets; lists are replaced and an explicit null clears an
        optional field. A published package must still pass every publishing rule, and its
        new text goes into the search index. The base price cannot drop below the floor."""
        async with self._db.transaction() as conn:
            row = await self._load(conn, package_id, lock=True)
            draft = patch_package_draft(PackageDraft.model_validate(row), patch)
            if missing := missing_fields(draft):
                raise DraftIncomplete(missing)
            terms = terms_from_draft(draft)
            published = row["status"] == "published"
            violations = self._violations(terms, publishing=published)
            floor = row["floor_price_cents"]
            if floor is not None and terms.base_price_cents < floor:
                violations.append(
                    RuleViolation(
                        field="base_price_cents",
                        message=f"The base price can't be below your floor ({format_cents(floor)}).",
                    )
                )
            if violations:
                raise RulesViolated(violations)
            await repo.update_package(conn, self._creator.id, package_id, terms)
            row = await self._load(conn, package_id)
        warnings = await self._refresh_search_index(gemini) if published else []
        return _saved(row, warnings)

    async def publish(self, gemini: GeminiPort, package_id: UUID) -> SavedPackage:
        """Make the package visible to brands, then refresh the creator's search embedding.

        Raises `RulesViolated` while any publishing rule fails. Once the package is
        published it stays published even if the embedding cannot be refreshed; the
        result then carries a warning and the next publish or edit retries.
        """
        async with self._db.transaction() as conn:
            row = await self._load(conn, package_id, lock=True)
            if violations := self._violations(PackageTerms.model_validate(row), publishing=True):
                raise RulesViolated(violations)
            if row["status"] != "published":
                await repo.publish_package(conn, self._creator.id, package_id)
                row = await self._load(conn, package_id)
        return _saved(row, await self._refresh_search_index(gemini))

    async def set_floor(self, package_id: UUID, floor_price_cents: int) -> MyPackage:
        """Set the private lowest price the creator accepts; it cannot exceed the base price."""
        async with self._db.transaction() as conn:
            row = await self._load(conn, package_id, lock=True)
            base = row["base_price_cents"]
            if floor_price_cents > base:
                raise RulesViolated(
                    [
                        RuleViolation(
                            field="floor_price_cents",
                            message=f"Your floor can't be above the base price ({format_cents(base)}).",
                        )
                    ]
                )
            await repo.set_floor(conn, package_id, floor_price_cents)
            row = await self._load(conn, package_id)
        return _my_package(row)

    # Internals ----------------------------------------------------------------------

    async def _load(
        self, conn: asyncpg.Connection, package_id: UUID, *, lock: bool = False
    ) -> dict[str, Any]:
        row = await repo.get_package(conn, self._creator.id, package_id, lock=lock)
        if row is None:
            raise PackageNotFound
        return row

    def _violations(self, terms: PackageTerms, *, publishing: bool) -> list[RuleViolation]:
        """The rules `terms` breaks: all of them when publishing, otherwise only the
        numeric ones that make the package unstorable."""
        violations = validate_package(terms, self._creator.niches)
        if not publishing:
            violations = [v for v in violations if v.field in STORED_NUMBER_FIELDS]
        violations += [
            RuleViolation(field=field, message="That number is too large.")
            for field in STORED_NUMBER_FIELDS
            if (getattr(terms, field) or 0) > INT4_MAX
        ]
        return violations

    def _draft_result(self, draft: PackageDraft, *, heard: str) -> DraftResult:
        return DraftResult(
            draft=draft,
            missing=missing_fields(draft),
            violations=draft_violations(draft, self._creator.niches),
            heard=heard,
        )

    async def _refresh_search_index(self, gemini: GeminiPort) -> list[str]:
        """Re-embed the creator when the text of their published packages changed.

        Runs after the package change is committed, so a model failure cannot undo it:
        it returns the warnings to show instead. Skips the model call when the text
        hashes the same as the stored embedding's.
        """
        async with self._db.acquire() as conn:
            rows = await repo.list_packages(conn, self._creator.id)
            stored_hash = await repo.embedding_hash(conn, self._creator.id)
        published = [PackageTerms.model_validate(r) for r in rows if r["status"] == "published"]
        title, text = creator_embedding_document(
            self._creator.name, self._creator.bio or "", self._creator.niches, published
        )
        digest = text_hash(title, text)
        if digest == stored_hash:
            return []
        try:
            [embedding] = await gemini.embed_documents([(title, text)])
        except (GeminiUnavailable, GeminiInvalidOutput) as exc:
            logger.warning("creator %s embedding not refreshed: %s", self._creator.id, exc)
            return [SEARCH_INDEX_PENDING]
        async with self._db.acquire() as conn:
            await repo.save_embedding(conn, self._creator.id, embedding, digest)
        return []
