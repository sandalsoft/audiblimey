<script lang="ts">
	import type { ProfileStats, ProfileBook } from '$lib/api/library.remote';
	import BookCard from '$lib/components/BookCard.svelte';

	let { personType, name, stats, books }: {
		personType: 'Author' | 'Narrator';
		name: string;
		stats: ProfileStats;
		books: ProfileBook[];
	} = $props();

	function formatHours(minutes: number): string {
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}
</script>

<!-- Stats row -->
<div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
	<div class="rounded-xl border border-border bg-card p-4 text-center">
		<p class="text-2xl font-bold text-foreground">{stats.book_count}</p>
		<p class="mt-1 text-xs text-muted-foreground">Books</p>
	</div>
	<div class="rounded-xl border border-border bg-card p-4 text-center">
		{#if stats.avg_rating != null}
			<p class="text-2xl font-bold text-foreground">
				<span class="text-primary">★</span> {stats.avg_rating.toFixed(1)}
			</p>
		{:else}
			<p class="text-2xl font-bold text-muted-foreground">—</p>
		{/if}
		<p class="mt-1 text-xs text-muted-foreground">Avg Rating</p>
	</div>
	<div class="rounded-xl border border-border bg-card p-4 text-center">
		<p class="text-2xl font-bold text-foreground">{formatHours(stats.total_runtime_minutes)}</p>
		<p class="mt-1 text-xs text-muted-foreground">Total Time</p>
	</div>
	<div class="rounded-xl border border-border bg-card p-4 text-center">
		<p class="text-2xl font-bold text-foreground">{stats.total_runtime_hours.toFixed(0)}</p>
		<p class="mt-1 text-xs text-muted-foreground">Hours</p>
	</div>
</div>

<!-- Books grid -->
<div class="mt-8">
	<h2 class="font-heading text-xl font-semibold text-foreground">
		Books by this {personType}
	</h2>
	{#if books.length === 0}
		<div class="mt-4 rounded-xl border border-border bg-card p-8 text-center">
			<p class="text-muted-foreground">No books found in your library for this {personType.toLowerCase()}.</p>
		</div>
	{:else}
		<div class="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
			{#each books as book (book.asin)}
				<BookCard {book} />
			{/each}
		</div>
	{/if}
</div>
