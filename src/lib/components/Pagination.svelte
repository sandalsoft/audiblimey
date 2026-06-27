<script lang="ts">
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

	let {
		currentPage,
		totalPages,
		onNavigate
	}: {
		currentPage: number;
		totalPages: number;
		onNavigate: (page: number) => void;
	} = $props();

	// Build the list of page numbers to show, inserting `null` for ellipsis gaps.
	// Always show page 1, the last page, and currentPage ± 1.
	const items = $derived.by<(number | null)[]>(() => {
		const pages = new Set<number>([1, totalPages]);
		for (let p = currentPage - 1; p <= currentPage + 1; p++) {
			if (p >= 1 && p <= totalPages) pages.add(p);
		}
		const sorted = [...pages].sort((a, b) => a - b);
		const result: (number | null)[] = [];
		let prev = 0;
		for (const p of sorted) {
			if (p - prev > 1) result.push(null);
			result.push(p);
			prev = p;
		}
		return result;
	});
</script>

{#if totalPages > 1}
	<nav class="mt-6 flex items-center justify-center gap-2" aria-label="Pagination">
		<button
			onclick={() => onNavigate(currentPage - 1)}
			disabled={currentPage === 1}
			aria-label="Previous page"
			class="flex items-center gap-1 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
		>
			<ChevronLeft class="h-4 w-4" />
			Prev
		</button>

		{#each items as item}
			{#if item === null}
				<span class="px-2 text-sm text-muted-foreground">…</span>
			{:else if item === currentPage}
				<span
					aria-current="page"
					class="rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground"
				>
					{item}
				</span>
			{:else}
				<button
					onclick={() => onNavigate(item)}
					aria-label="Go to page {item}"
					class="rounded-lg border border-border bg-card px-3.5 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted"
				>
					{item}
				</button>
			{/if}
		{/each}

		<button
			onclick={() => onNavigate(currentPage + 1)}
			disabled={currentPage >= totalPages}
			aria-label="Next page"
			class="flex items-center gap-1 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
		>
			Next
			<ChevronRight class="h-4 w-4" />
		</button>
	</nav>
{/if}
