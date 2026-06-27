<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft } from 'lucide-svelte';
	import BookCard from '$lib/components/BookCard.svelte';
	import type { RuleAction } from '$lib/components/BookCard.svelte';
	import { getSeriesDetail, setRating } from '$lib/api/library.remote';
	import { putTasteRule, deleteTasteRule } from '$lib/api/taste.remote';

	const seriesQuery = $derived(getSeriesDetail(Number(page.params.id)));
	const series = $derived(await seriesQuery);

	async function applyRule(action: RuleAction) {
		const cmd = 'deleteId' in action ? deleteTasteRule(action.deleteId) : putTasteRule(action);
		await cmd.updates(seriesQuery);
	}

	async function setSeriesRule(mode: 'exclude' | 'include') {
		await applyRule({ scope: 'series', entity_id: series.id, mode });
	}
	async function clearSeriesRule() {
		if (series.rule) await applyRule({ deleteId: series.rule.id });
	}

	async function rate(asin: string, rating: number | null) {
		await setRating({ asin, rating }).updates(seriesQuery);
	}

	async function rateAll(rating: number | null) {
		const owned = series.books.filter((b) => b.in_library);
		await Promise.all(owned.map((b) => setRating({ asin: b.asin, rating })));
		await seriesQuery.refresh();
	}
</script>

<a href="/library" class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
	<ArrowLeft class="h-4 w-4" />
	Back to Library
</a>

<svelte:boundary>
	<div class="mt-6 space-y-6">
		<header>
			<h1 class="font-heading text-3xl font-bold text-foreground">{series.title}</h1>
			<p class="mt-2 text-sm text-muted-foreground">
				{series.book_count} book{series.book_count === 1 ? '' : 's'} in series · {series.owned_count} in your library
				{#if series.avg_rating != null}
					· <span class="text-primary">★</span> {series.avg_rating.toFixed(1)} avg
				{/if}
			</p>
		</header>

		<!-- Mass actions for the whole series -->
		<div class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Whole series</h2>

			<div class="mt-3 flex flex-wrap items-center gap-3">
				<span class="text-sm text-card-foreground">Taste:</span>
				{#if series.rule}
					<span class="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
						{series.rule.mode === 'include' ? 'Included' : 'Excluded'}
					</span>
				{/if}
				<button
					type="button"
					onclick={() => setSeriesRule('exclude')}
					class="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-destructive"
				>Exclude series</button>
				<button
					type="button"
					onclick={() => setSeriesRule('include')}
					class="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-primary"
				>Include series</button>
				{#if series.rule}
					<button
						type="button"
						onclick={clearSeriesRule}
						class="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
					>Clear</button>
				{/if}
			</div>

			<div class="mt-4 flex flex-wrap items-center gap-2">
				<span class="text-sm text-card-foreground">Rate all owned:</span>
				<div class="flex items-center gap-0.5" aria-label="Rate all owned books">
					{#each [1, 2, 3, 4, 5] as star (star)}
						<button
							type="button"
							onclick={() => rateAll(star)}
							aria-label={`Rate all ${star} star${star > 1 ? 's' : ''}`}
							class="text-lg leading-none text-muted-foreground/40 transition-colors hover:text-primary"
						>★</button>
					{/each}
				</div>
				<button
					type="button"
					onclick={() => rateAll(null)}
					class="ml-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
				>Clear all</button>
			</div>
		</div>

		<!-- Books in the series -->
		{#if series.books.length === 0}
			<div class="rounded-xl border border-border bg-card p-8 text-center">
				<p class="text-muted-foreground">No books found for this series.</p>
			</div>
		{:else}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each series.books as book (book.asin)}
					<div class="relative">
						{#if !book.in_library}
							<span class="absolute right-3 top-3 z-10 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
								Not in library
							</span>
						{/if}
						<BookCard
							{book}
							onRate={book.in_library ? (r) => rate(book.asin, r) : undefined}
							onClearRating={book.in_library ? () => rate(book.asin, null) : undefined}
							onRule={applyRule}
						/>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	{#snippet pending()}
		<div class="mt-6 space-y-6 animate-pulse">
			<div class="h-8 w-1/3 rounded bg-muted"></div>
			<div class="h-28 rounded-xl border border-border bg-card"></div>
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each { length: 3 } as _}
					<div class="h-40 rounded-xl border border-border bg-card"></div>
				{/each}
			</div>
		</div>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="mt-6 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Failed to load series</p>
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
