<script lang="ts">
	import { X } from 'lucide-svelte';
	import type { RecommendationItem } from '$lib/api/recommendations.remote';
	import { dismissRecommendation } from '$lib/api/recommendations.remote';
	import type { RemoteQuery } from '@sveltejs/kit';

	let { rec, query }: { rec: RecommendationItem; query: RemoteQuery<any> } = $props();

	let dismissing = $state(false);

	async function handleDismiss() {
		dismissing = true;
		try {
			await dismissRecommendation(rec.id).updates(query);
		} catch (err) {
			console.error('Failed to dismiss recommendation:', err);
			dismissing = false;
		}
	}

	function formatScore(score: number): string {
		const pct = score > 1 ? score : score * 100;
		return `${Math.round(pct)}%`;
	}

	function formatPrice(price: number | null): string {
		if (price == null) return '—';
		return `$${price.toFixed(2)}`;
	}
</script>

<div class="group relative rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
	<button
		onclick={handleDismiss}
		disabled={dismissing}
		class="absolute right-3 top-3 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover:opacity-100 disabled:opacity-50"
		aria-label="Dismiss recommendation"
	>
		<X class="h-4 w-4" />
	</button>

	<div class="flex items-start gap-3">
		<span class="inline-flex shrink-0 items-center rounded-md bg-primary px-2 py-0.5 text-sm font-semibold text-primary-foreground">
			{formatScore(rec.score)}
		</span>
		<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground">
			{rec.book.title}
		</h3>
	</div>

	<p class="mt-2 text-sm leading-relaxed text-muted-foreground">
		{rec.short_explanation}
	</p>

	{#if rec.pricing}
		<div class="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
			{#if rec.pricing.member_price != null}
				<span class="font-medium text-primary">
					{formatPrice(rec.pricing.member_price)} member
				</span>
			{/if}
			{#if rec.pricing.list_price != null}
				<span>
					{formatPrice(rec.pricing.list_price)} list
				</span>
			{/if}
		</div>
	{/if}

	{#if rec.source_name}
		<p class="mt-2 text-xs text-muted-foreground/70">
			via {rec.source_name}
		</p>
	{/if}
</div>
