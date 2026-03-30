<script lang="ts">
	import { Search as SearchIcon, SlidersHorizontal, X } from 'lucide-svelte';
	import { searchBooks, type SearchResult } from '$lib/api/search.remote';

	let queryText = $state('');
	let submittedQuery = $state('');
	let minRuntime = $state<number | undefined>(undefined);
	let maxRuntime = $state<number | undefined>(undefined);
	let minRating = $state<number | undefined>(undefined);
	let showFilters = $state(false);

	function handleSubmit(e: Event) {
		e.preventDefault();
		const trimmed = queryText.trim();
		if (trimmed) {
			submittedQuery = trimmed;
		}
	}

	function clearFilters() {
		minRuntime = undefined;
		maxRuntime = undefined;
		minRating = undefined;
	}

	function parseNumber(value: string): number | undefined {
		const n = Number(value);
		return value === '' || isNaN(n) ? undefined : n;
	}

	function formatRuntime(hours: number | null): string {
		if (hours == null) return '';
		const h = Math.floor(hours);
		const m = Math.round((hours - h) * 60);
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}

	function formatScore(score: number | null): string {
		if (score == null) return '';
		return `${Math.round(score * 100)}%`;
	}

	const hasActiveFilters = $derived(
		minRuntime != null || maxRuntime != null || minRating != null
	);

	const searchData = $derived(
		submittedQuery
			? await searchBooks({
					q: submittedQuery,
					min_runtime: minRuntime,
					max_runtime: maxRuntime,
					min_rating: minRating,
					limit: 20
				})
			: null
	);
</script>

<h1 class="font-heading text-3xl font-bold text-foreground">Search</h1>
<p class="mt-2 text-muted-foreground">Find audiobooks using natural language — describe what you're looking for.</p>

<!-- Search Form -->
<form onsubmit={handleSubmit} class="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center">
	<div class="relative flex-1">
		<SearchIcon class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
		<input
			type="text"
			placeholder="e.g. long fantasy series with great narration…"
			bind:value={queryText}
			class="w-full rounded-lg border border-border bg-card py-2 pl-10 pr-4 text-sm text-card-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
		/>
	</div>
	<div class="flex gap-2">
		<button
			type="submit"
			disabled={!queryText.trim()}
			class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
		>
			Search
		</button>
		<button
			type="button"
			onclick={() => { showFilters = !showFilters; }}
			class="rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors hover:bg-muted {showFilters || hasActiveFilters ? 'text-primary border-primary/50' : 'text-card-foreground'}"
		>
			<SlidersHorizontal class="h-4 w-4" />
		</button>
	</div>
</form>

<!-- Filters Panel -->
{#if showFilters}
	<div class="mt-4 rounded-xl border border-border bg-card p-4">
		<div class="flex items-center justify-between">
			<h3 class="text-sm font-medium text-card-foreground">Filters</h3>
			{#if hasActiveFilters}
				<button
					onclick={clearFilters}
					class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
				>
					<X class="h-3 w-3" />
					Clear all
				</button>
			{/if}
		</div>
		<div class="mt-3 grid gap-4 sm:grid-cols-3">
			<div>
				<label for="min-runtime" class="block text-xs font-medium text-muted-foreground">Min Runtime (hours)</label>
				<input
					id="min-runtime"
					type="number"
					min="0"
					step="0.5"
					placeholder="0"
					value={minRuntime ?? ''}
					oninput={(e) => { minRuntime = parseNumber(e.currentTarget.value); }}
					class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</div>
			<div>
				<label for="max-runtime" class="block text-xs font-medium text-muted-foreground">Max Runtime (hours)</label>
				<input
					id="max-runtime"
					type="number"
					min="0"
					step="0.5"
					placeholder="∞"
					value={maxRuntime ?? ''}
					oninput={(e) => { maxRuntime = parseNumber(e.currentTarget.value); }}
					class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</div>
			<div>
				<label for="min-rating" class="block text-xs font-medium text-muted-foreground">Min Rating</label>
				<input
					id="min-rating"
					type="number"
					min="1"
					max="5"
					step="0.5"
					placeholder="Any"
					value={minRating ?? ''}
					oninput={(e) => { minRating = parseNumber(e.currentTarget.value); }}
					class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</div>
		</div>
	</div>
{/if}

<!-- Results Section -->
<section class="mt-8">
	{#if !submittedQuery}
		<div class="rounded-xl border border-border bg-card p-10 text-center">
			<SearchIcon class="mx-auto h-10 w-10 text-muted-foreground/50" />
			<p class="mt-4 font-heading text-lg text-card-foreground">Describe what you want to listen to</p>
			<p class="mt-2 text-sm text-muted-foreground">
				Try something like "cozy mystery with humor" or "epic sci-fi space opera with great world building"
			</p>
		</div>
	{:else if searchData}
		<svelte:boundary>
			<p class="mb-4 text-sm text-muted-foreground">
				{searchData.items.length} result{searchData.items.length !== 1 ? 's' : ''} for "<span class="text-foreground">{searchData.query}</span>"
			</p>

			{#if searchData.items.length === 0}
				<div class="rounded-xl border border-border bg-card p-10 text-center">
					<p class="font-heading text-lg text-card-foreground">No results found</p>
					<p class="mt-2 text-sm text-muted-foreground">
						Try a different query or loosen the filters.
					</p>
				</div>
			{:else}
				<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
					{#each searchData.items as result (result.asin)}
						<a
							href="/books/{result.asin}"
							class="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30"
						>
							<div class="flex items-start justify-between gap-2">
								<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground group-hover:text-primary">
									{result.title}
								</h3>
								{#if result.similarity_score != null}
									<span class="shrink-0 rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
										{formatScore(result.similarity_score)} match
									</span>
								{/if}
							</div>

							{#if result.authors}
								<p class="mt-2 text-sm text-muted-foreground">
									by {result.authors}
								</p>
							{/if}

							{#if result.categories}
								<p class="mt-1 text-xs text-muted-foreground/80 line-clamp-1">
									{result.categories}
								</p>
							{/if}

							<div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
								{#if result.runtime_hours != null}
									<span>{formatRuntime(result.runtime_hours)}</span>
								{/if}
								{#if result.user_rating != null}
									<span class="flex items-center gap-1">
										<span class="text-primary">★</span>
										{result.user_rating}
									</span>
								{/if}
							</div>
						</a>
					{/each}
				</div>
			{/if}

			{#snippet pending()}
				<p class="mb-4 text-sm text-muted-foreground">Searching…</p>
				<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
					{#each { length: 6 } as _}
						<div class="animate-pulse rounded-xl border border-border bg-card p-5">
							<div class="flex items-start justify-between gap-2">
								<div class="h-5 w-3/4 rounded bg-muted"></div>
								<div class="h-5 w-16 rounded bg-muted"></div>
							</div>
							<div class="mt-3 h-4 w-1/2 rounded bg-muted"></div>
							<div class="mt-2 h-3 w-2/3 rounded bg-muted"></div>
							<div class="mt-3 flex gap-3">
								<div class="h-4 w-12 rounded bg-muted"></div>
								<div class="h-4 w-10 rounded bg-muted"></div>
							</div>
						</div>
					{/each}
				</div>
			{/snippet}

			{#snippet failed(error, reset)}
				<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
					<p class="font-heading text-lg text-destructive">Search failed</p>
					<p class="mt-2 text-sm text-muted-foreground">
						{error instanceof Error ? error.message : 'An unexpected error occurred'}
					</p>
					<button
						onclick={reset}
						class="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
					>
						Retry
					</button>
				</div>
			{/snippet}
		</svelte:boundary>
	{/if}
</section>
