import type { components } from "@/lib/api/schema"
import { formatFollowers } from "@/lib/format"
import { formatCents } from "@/lib/money"
import {
  asRegion,
  contentTypeLabel,
  nicheLabel,
  regionLabel,
} from "@/lib/vocab"

export type SearchFilters = components["schemas"]["SearchFilters"]
export type SearchRequest = components["schemas"]["SearchRequest"]
export type SearchResponse = components["schemas"]["SearchResponse"]
export type CreatorCard = components["schemas"]["CreatorCard"]
export type PackageSummary = components["schemas"]["PackageSummary"]

/** A search as a voice intent or a page hands it over: anything left out is open. */
export type SearchInput = {
  query?: string | null
  filters?: Partial<SearchFilters> | null
  limit?: number
}

export type DiscoverState = {
  /** The words the brand searched for, or null for "everyone, most followed first". */
  query: string | null
  filters: SearchFilters
  /** Creator ids in the order they were picked. */
  selected: string[]
  /** The creators on screen, best match first. */
  results: CreatorCard[]
}

/** How many creators one batch may hold. */
export const MAX_SELECTED = 10
export const SELECTION_CAP_MESSAGE = "Batches are limited to 10 creators"
/** How many creators one search asks for (the API allows up to 48). */
export const SEARCH_LIMIT = 24

export const SELECTION_KEY = "collabio:selection"
export const SEARCH_KEY = "collabio:search"

export const emptyDiscover: DiscoverState = {
  query: null,
  filters: { niches: [], content_types: [] },
  selected: [],
  results: [],
}

/**
 * Filters with only the dimensions that are actually set: an empty value is the same
 * as no filter, so it is dropped rather than kept as `null` or `""`.
 */
export function normalizeFilters(
  filters?: Partial<SearchFilters> | null
): SearchFilters {
  const clean: SearchFilters = {
    niches: [...new Set(filters?.niches ?? [])],
    content_types: [...new Set(filters?.content_types ?? [])],
  }
  if (filters?.max_price_cents != null && filters.max_price_cents > 0) {
    clean.max_price_cents = filters.max_price_cents
  }
  if (filters?.min_followers != null && filters.min_followers > 0) {
    clean.min_followers = filters.min_followers
  }
  // Only a stored code can match a creator; anything else (a place name left over from
  // an older session) would be refused by the API, so it is no filter.
  const region = asRegion(filters?.region)
  if (region) clean.region = region
  return clean
}

function normalizeQuery(query: string | null | undefined): string | null {
  return query?.trim() || null
}

/** A search replaces the query and every filter. What is selected stays selected. */
export function applySearchIntent(
  state: DiscoverState,
  search: SearchInput
): DiscoverState {
  return {
    ...state,
    query: normalizeQuery(search.query),
    filters: normalizeFilters(search.filters),
  }
}

/** The API request for what the state asks for. */
export function requestFor(state: DiscoverState): SearchRequest {
  return {
    query: state.query,
    filters: state.filters,
    limit: SEARCH_LIMIT,
  }
}

// Filter chips ------------------------------------------------------------------------

export type FilterChip = {
  /** Distinct among one filter set, so it can key a list. */
  id: string
  kind: "niche" | "content_type" | "max_price" | "min_followers" | "region"
  /** The filter value this chip stands for. */
  value: string | number
  label: string
}

/** One chip per active filter value, in reading order. */
export function chipsFor(filters: SearchFilters): FilterChip[] {
  const chips: FilterChip[] = []
  const add = (
    kind: FilterChip["kind"],
    value: string | number,
    label: string
  ) => chips.push({ id: `${kind}:${value}`, kind, value, label })

  for (const niche of filters.niches) add("niche", niche, nicheLabel(niche))
  for (const type of filters.content_types) {
    add("content_type", type, contentTypeLabel(type))
  }
  if (filters.max_price_cents) {
    add(
      "max_price",
      filters.max_price_cents,
      `≤ ${formatCents(filters.max_price_cents)}`
    )
  }
  if (filters.min_followers) {
    add(
      "min_followers",
      filters.min_followers,
      `${formatFollowers(filters.min_followers)}+ followers`
    )
  }
  if (filters.region) {
    add("region", filters.region, regionLabel(filters.region))
  }
  return chips
}

/** The state without the one filter value a chip stands for. */
export function removeFilter(
  state: DiscoverState,
  chip: FilterChip
): DiscoverState {
  const { filters } = state
  const next: Partial<SearchFilters> = { ...filters }
  switch (chip.kind) {
    case "niche":
      next.niches = filters.niches.filter((niche) => niche !== chip.value)
      break
    case "content_type":
      next.content_types = filters.content_types.filter(
        (type) => type !== chip.value
      )
      break
    case "max_price":
      delete next.max_price_cents
      break
    case "min_followers":
      delete next.min_followers
      break
    case "region":
      delete next.region
      break
  }
  return { ...state, filters: normalizeFilters(next) }
}

/**
 * Whether a package is one the filters asked for. Format and price cap both have to
 * hold on the same package (as the search applies them), so a creator who matched
 * through one package can show which.
 */
export function packageFits(
  pkg: PackageSummary,
  filters: SearchFilters
): boolean {
  const { content_types, max_price_cents } = filters
  if (content_types.length > 0 && !content_types.includes(pkg.content_type)) {
    return false
  }
  if (max_price_cents != null && pkg.base_price_cents > max_price_cents) {
    return false
  }
  return true
}

/**
 * The package to compare for a creator by default: the cheapest one the filters asked
 * for, or the cheapest overall when none of them fits. Null for a creator with no
 * packages.
 */
export function bestFitPackage(
  packages: PackageSummary[],
  filters: SearchFilters
): PackageSummary | null {
  const cheapest = (list: PackageSummary[]) =>
    list.reduce<PackageSummary | null>(
      (best, pkg) =>
        best === null || pkg.base_price_cents < best.base_price_cents
          ? pkg
          : best,
      null
    )
  const fitting = packages.filter((pkg) => packageFits(pkg, filters))
  return cheapest(fitting.length > 0 ? fitting : packages)
}

// Selection ---------------------------------------------------------------------------

export type SelectionAction =
  | { type: "toggle"; id: string }
  /** Replace the selection with the first `n` creators on screen. */
  | { type: "top_n"; n: number }
  | { type: "add"; ids: string[] }
  | { type: "clear" }

/** The picks an action leads to, and how many creators it wanted past the cap. */
function resolveSelection(
  state: DiscoverState,
  action: SelectionAction
): { selected: string[]; overflow: boolean } {
  const { selected, results } = state
  const capped = (wanted: string[]) => ({
    selected: wanted.slice(0, MAX_SELECTED),
    overflow: wanted.length > MAX_SELECTED,
  })

  switch (action.type) {
    case "toggle":
      if (selected.includes(action.id)) {
        return {
          selected: selected.filter((id) => id !== action.id),
          overflow: false,
        }
      }
      return capped([...selected, action.id])
    case "top_n":
      return capped(
        results.slice(0, Math.max(0, action.n)).map((creator) => creator.id)
      )
    case "add":
      return capped([...new Set([...selected, ...action.ids])])
    case "clear":
      return { selected: [], overflow: false }
  }
}

/** The state after a selection action, never holding more than {@link MAX_SELECTED}. */
export function selectionReducer(
  state: DiscoverState,
  action: SelectionAction
): DiscoverState {
  return { ...state, selected: resolveSelection(state, action).selected }
}

/**
 * True when the action asked for more creators than a batch holds, so the caller can
 * say so ({@link SELECTION_CAP_MESSAGE}). The reducer stays free of side effects.
 */
export function selectionOverflow(
  state: DiscoverState,
  action: SelectionAction
): boolean {
  return resolveSelection(state, action).overflow
}

// Session storage ---------------------------------------------------------------------
// The selection and the last search outlive a page change, so Review can read the
// batch and send the brand back to the search it came from. Storage can be missing or
// refuse access (private windows, blocked site data): every access is guarded.

function read(key: string): unknown {
  try {
    const raw = sessionStorage.getItem(key)
    return raw === null ? null : JSON.parse(raw)
  } catch {
    return null
  }
}

function write(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    // The page works without it; only the hand-over to Review is lost.
  }
}

/** The ids picked on Discover, as far as they can be trusted. */
export function loadSelection(): string[] {
  const stored = read(SELECTION_KEY)
  if (!Array.isArray(stored)) return []
  const ids = stored.filter((id): id is string => typeof id === "string")
  return [...new Set(ids)].slice(0, MAX_SELECTED)
}

export function saveSelection(ids: string[]) {
  write(SELECTION_KEY, ids)
}

/** The search Discover last ran, or null if there is none to go back to. */
export function loadSearch(): SearchRequest | null {
  const stored = read(SEARCH_KEY)
  if (typeof stored !== "object" || stored === null || Array.isArray(stored)) {
    return null
  }
  const { query, filters, limit } = stored as Record<string, unknown>
  return {
    query: typeof query === "string" ? normalizeQuery(query) : null,
    filters: normalizeFilters(
      typeof filters === "object" && filters !== null
        ? (filters as Partial<SearchFilters>)
        : null
    ),
    limit: typeof limit === "number" ? limit : SEARCH_LIMIT,
  }
}

export function saveSearch(search: SearchInput) {
  write(SEARCH_KEY, search)
}

/**
 * Forgets the saved selection and search. They belong to whoever made them, so they
 * must not carry over to the next account signed in on this tab.
 */
export function clearDiscoverSession() {
  for (const key of [SELECTION_KEY, SEARCH_KEY]) {
    try {
      sessionStorage.removeItem(key)
    } catch {
      // Storage is unavailable, so there is nothing saved to carry over.
    }
  }
}
