<script lang="ts">
	import { BookOpen } from 'lucide-svelte';
	import type { SeriesItem } from '$lib/api/recommendations.remote';

	let { series }: { series: SeriesItem } = $props();

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
			{series.series_title}
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

	<!-- Next book -->
	{#if series.next_book}
		<div class="mt-4 rounded-lg border border-border/60 bg-muted/30 p-3">
			<div class="flex items-start gap-2">
				<BookOpen class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
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
								<span>
									{formatPrice(series.next_book.pricing.list_price)} list
								</span>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>
