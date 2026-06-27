<script lang="ts">
	import { Layers, Ban } from 'lucide-svelte';
	import type { SeriesGroup } from '$lib/api/recommendations.remote';

	let {
		group,
		onExclude
	}: {
		group: SeriesGroup;
		onExclude: (scope: string, entityId: number) => void;
	} = $props();

	let imageFailed = $state(false);

	function formatScore(score: number): string {
		const pct = score > 1 ? score : score * 100;
		return `${Math.round(pct)}%`;
	}
</script>

<div class="group relative rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
	<div class="flex items-start gap-4">
		<a
			href={`/series/${group.series_id}`}
			class="flex h-24 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/40"
		>
			{#if group.image_url && !imageFailed}
				<img
					src={group.image_url}
					alt={`Cover for ${group.series_title}`}
					loading="lazy"
					onerror={() => {
						imageFailed = true;
					}}
					class="h-full w-full object-cover"
				/>
			{:else}
				<span class="px-1 text-center font-heading text-2xl text-muted-foreground/60">
					{group.series_title.slice(0, 1)}
				</span>
			{/if}
		</a>

		<div class="min-w-0 flex-1">
			<div class="flex items-start gap-2">
				<span class="inline-flex shrink-0 items-center rounded-md bg-primary px-2 py-0.5 text-sm font-semibold text-primary-foreground">
					{formatScore(group.score)}
				</span>
				<h3 class="font-heading text-base font-semibold leading-snug text-card-foreground">
					<a href={`/series/${group.series_id}`} class="transition-colors hover:text-primary">
						{group.series_title}
					</a>
				</h3>
			</div>

			<div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
				<span class="inline-flex items-center gap-1.5 text-primary">
					<Layers class="h-3.5 w-3.5" />
					{group.recommended_count} book{group.recommended_count === 1 ? '' : 's'} recommended
				</span>
				{#if group.genre}
					<span aria-hidden="true">·</span>
					<span>{group.genre.name}</span>
				{/if}
			</div>

			<div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
				<button
					type="button"
					onclick={() => onExclude('series', group.series_id)}
					class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
				>
					<Ban class="h-3 w-3" />
					Exclude series
				</button>
				{#if group.genre}
					{@const genre = group.genre}
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
	</div>
</div>
