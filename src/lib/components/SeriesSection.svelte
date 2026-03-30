<script lang="ts">
	import SeriesCard from '$lib/components/SeriesCard.svelte';
	import { getSeriesRecommendations } from '$lib/api/recommendations.remote';
</script>

<section class="mt-10">
	<h2 class="font-heading text-2xl font-bold text-foreground">Continue Your Series</h2>
	<p class="mt-1 text-sm text-muted-foreground">
		Incomplete series ranked by urgency — pick up where you left off.
	</p>

	<div class="mt-5">
		<svelte:boundary>
			{@const seriesData = await getSeriesRecommendations()}

			{#if seriesData.series.length === 0}
				<div class="rounded-xl border border-border bg-card p-10 text-center">
					<p class="font-heading text-lg text-card-foreground">No incomplete series</p>
					<p class="mt-2 text-sm text-muted-foreground">
						All your series are complete — or we haven't found any yet.
					</p>
				</div>
			{:else}
				<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
					{#each seriesData.series as series (series.series_title)}
						<SeriesCard {series} />
					{/each}
				</div>
			{/if}

			{#snippet pending()}
				<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
					{#each { length: 3 } as _}
						<div class="animate-pulse rounded-xl border border-border bg-card p-5">
							<div class="flex items-start justify-between">
								<div class="h-5 w-1/2 rounded bg-muted"></div>
								<div class="h-5 w-12 rounded-md bg-muted"></div>
							</div>
							<div class="mt-3 h-1.5 w-full rounded-full bg-muted"></div>
							<div class="mt-3 h-4 w-1/3 rounded bg-muted"></div>
							<div class="mt-4 rounded-lg bg-muted/30 p-3">
								<div class="h-4 w-3/4 rounded bg-muted"></div>
								<div class="mt-2 h-3 w-1/2 rounded bg-muted"></div>
							</div>
						</div>
					{/each}
				</div>
			{/snippet}

			{#snippet failed(error, reset)}
				<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
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
	</div>
</section>
