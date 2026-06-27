<script lang="ts">
	import { X, Ban } from 'lucide-svelte';
	import type { BookItem } from '$lib/api/recommendations.remote';
	import { dismissRecommendation } from '$lib/api/recommendations.remote';
	import type { RemoteQuery } from '@sveltejs/kit';

	let {
		rec,
		query,
		onExclude
	}: {
		rec: BookItem;
		query: RemoteQuery<any>;
		onExclude: (scope: string, entityId: number) => void;
	} = $props();

	let dismissing = $state(false);
	let imageFailed = $state(false);

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

	<div class="flex items-start gap-4">
		<a
			href={`/books/${rec.book.asin}`}
			class="flex h-24 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/40"
		>
			{#if rec.book.image_url && !imageFailed}
				<img
					src={rec.book.image_url}
					alt={`Cover for ${rec.book.title}`}
					loading="lazy"
					onerror={() => {
						imageFailed = true;
					}}
					class="h-full w-full object-cover"
				/>
			{:else}
				<span class="px-1 text-center font-heading text-2xl text-muted-foreground/60">
					{rec.book.title.slice(0, 1)}
				</span>
			{/if}
		</a>

		<div class="min-w-0 flex-1">
			<div class="flex items-start gap-2 pr-6">
				<span class="inline-flex shrink-0 items-center rounded-md bg-primary px-2 py-0.5 text-sm font-semibold text-primary-foreground">
					{formatScore(rec.score)}
				</span>
				<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground">
					<a href={`/books/${rec.book.asin}`} class="transition-colors hover:text-primary">
						{rec.book.title}
					</a>
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
						<span>{formatPrice(rec.pricing.list_price)} list</span>
					{/if}
				</div>
			{/if}

			<div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground/70">
				{#if rec.source_name}
					<span>via {rec.source_name}</span>
				{/if}
				{#if rec.genre}
					{@const genre = rec.genre}
					<button
						type="button"
						onclick={() => onExclude('category', genre.id)}
						title={`Exclude ${genre.name} from recommendations`}
						class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-muted hover:text-destructive"
					>
						<Ban class="h-3 w-3" />
						Exclude {genre.name}
					</button>
				{/if}
			</div>
		</div>
	</div>
</div>
