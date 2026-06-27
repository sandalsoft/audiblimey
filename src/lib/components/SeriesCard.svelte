<script lang="ts">
	import { BookOpen, Ban } from 'lucide-svelte';
	import type { SeriesItem } from '$lib/api/recommendations.remote';

	let {
		series,
		onExclude
	}: {
		series: SeriesItem;
		onExclude: (scope: string, entityId: number) => void;
	} = $props();

	let imageFailed = $state(false);

	function formatRuntime(minutes: number | null): string {
		if (minutes == null) return '';
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}

	function formatPrice(price: number | null): string {
		if (price == null) return '—';
		return `$${price.toFixed(2)}`;
	}

	function urgencyLabel(score: number): string {
		if (score >= 0.8) return 'High';
		if (score >= 0.5) return 'Medium';
		return 'Low';
	}

	function urgencyColor(score: number): string {
		if (score >= 0.8) return 'bg-accent text-accent-foreground';
		if (score >= 0.5) return 'bg-primary text-primary-foreground';
		return 'bg-muted text-muted-foreground';
	}
</script>

<div class="rounded-xl border border-border bg-card p-5">
	<div class="flex items-start justify-between gap-3">
		<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground">
			<a href={`/series/${series.series_id}`} class="transition-colors hover:text-primary">
				{series.series_title}
			</a>
		</h3>
		<span class="shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold {urgencyColor(series.urgency_score)}">
			{urgencyLabel(series.urgency_score)}
		</span>
	</div>

	<!-- Progress -->
	<div class="mt-3">
		<div class="flex items-center justify-between text-xs text-muted-foreground">
			<span>{series.owned_count} of {series.total_books} books</span>
			<span>{Math.round(series.progress_pct)}%</span>
		</div>
		<div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
			<div
				class="h-full rounded-full bg-primary transition-all"
				style="width: {series.progress_pct}%"
			></div>
		</div>
	</div>

	<!-- Average rating -->
	<div class="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
		<span class="text-primary">★</span>
		<span>{series.avg_rating.toFixed(1)} avg rating</span>
	</div>

	<!-- Next book (links to the series detail; no nested interactive controls) -->
	{#if series.next_book}
		<a
			href={`/series/${series.series_id}`}
			class="mt-4 block rounded-lg border border-border/60 bg-muted/30 p-3 transition-colors hover:border-primary/30"
		>
			<div class="flex items-start gap-3">
				<div class="flex h-20 w-14 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted/40">
					{#if series.next_book.image_url && !imageFailed}
						<img
							src={series.next_book.image_url}
							alt={`Cover for ${series.next_book.title}`}
							loading="lazy"
							onerror={() => {
								imageFailed = true;
							}}
							class="h-full w-full object-cover"
						/>
					{:else}
						<BookOpen class="h-5 w-5 text-primary" />
					{/if}
				</div>
				<div class="min-w-0">
					<p class="text-xs font-medium text-muted-foreground">
						Book {series.next_book.sequence ?? series.next_sequence}
					</p>
					<p class="mt-0.5 text-sm font-medium leading-snug text-card-foreground">
						{series.next_book.title}
					</p>
					{#if series.next_book.runtime_minutes}
						<p class="mt-1 text-xs text-muted-foreground">
							{formatRuntime(series.next_book.runtime_minutes)}
						</p>
					{/if}
					{#if series.next_book.pricing}
						<div class="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
							{#if series.next_book.pricing.member_price != null}
								<span class="font-medium text-primary">
									{formatPrice(series.next_book.pricing.member_price)} member
								</span>
							{/if}
							{#if series.next_book.pricing.list_price != null}
								<span>{formatPrice(series.next_book.pricing.list_price)} list</span>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		</a>
	{/if}

	<!-- Exclude actions (kept outside the link) -->
	<div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
		<button
			type="button"
			onclick={() => onExclude('series', series.series_id)}
			class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
		>
			<Ban class="h-3 w-3" />
			Exclude series
		</button>
		{#if series.next_book?.genre}
			{@const genre = series.next_book.genre}
			<button
				type="button"
				onclick={() => onExclude('category', genre.id)}
				title={`Exclude ${genre.name} from recommendations`}
				class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
			>
				<Ban class="h-3 w-3" />
				Exclude {genre.name}
			</button>
		{/if}
	</div>
</div>
