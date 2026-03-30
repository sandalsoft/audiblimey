<script lang="ts">
	import HealthCheck from '$lib/components/HealthCheck.svelte';
	import RecommendationCard from '$lib/components/RecommendationCard.svelte';
	import SeriesSection from '$lib/components/SeriesSection.svelte';
	import { getRecommendations } from '$lib/api/recommendations.remote';

	const PAGE_SIZE = 20;
	let offset = $state(0);

	const recsQuery = $derived(getRecommendations({ limit: PAGE_SIZE, offset }));
	const recs = $derived(await recsQuery);
</script>

<h1 class="font-heading text-3xl font-bold text-foreground">Your Next Listen</h1>
<p class="mt-2 text-muted-foreground">
	Scored recommendations — powered by Audible + Goodreads taste fusion.
</p>

<div class="mt-6">
	<HealthCheck />
</div>

<section class="mt-8">
	<svelte:boundary>
		{#if recs.items.length === 0}
			<div class="rounded-xl border border-border bg-card p-10 text-center">
				<p class="font-heading text-lg text-card-foreground">No recommendations yet</p>
				<p class="mt-2 text-sm text-muted-foreground">
					Import your Audible library and Goodreads shelves to get started.
				</p>
			</div>
		{:else}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each recs.items as rec (rec.id)}
					<RecommendationCard {rec} query={recsQuery} />
				{/each}
			</div>

			{@const totalPages = Math.ceil(recs.total / PAGE_SIZE)}
			{@const currentPage = Math.floor(offset / PAGE_SIZE) + 1}

			{#if totalPages > 1}
				<div class="mt-6 flex items-center justify-center gap-4">
					<button
						onclick={() => { offset = Math.max(0, offset - PAGE_SIZE); }}
						disabled={offset === 0}
						class="rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
					>
						Previous
					</button>
					<span class="text-sm text-muted-foreground">
						Page {currentPage} of {totalPages}
					</span>
					<button
						onclick={() => { offset = offset + PAGE_SIZE; }}
						disabled={currentPage >= totalPages}
						class="rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
					>
						Next
					</button>
				</div>
			{/if}
		{/if}

		{#snippet pending()}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each { length: 6 } as _}
					<div class="animate-pulse rounded-xl border border-border bg-card p-5">
						<div class="flex items-start gap-3">
							<div class="h-6 w-10 rounded-md bg-muted"></div>
							<div class="h-5 w-3/4 rounded bg-muted"></div>
						</div>
						<div class="mt-3 h-4 w-full rounded bg-muted"></div>
						<div class="mt-2 h-4 w-2/3 rounded bg-muted"></div>
					</div>
				{/each}
			</div>
		{/snippet}

		{#snippet failed(error, reset)}
			<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
				<p class="font-heading text-lg text-destructive">Failed to load recommendations</p>
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
</section>

<SeriesSection />
