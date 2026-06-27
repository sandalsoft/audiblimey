<script lang="ts">
	import { Search } from 'lucide-svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import BookCard from '$lib/components/BookCard.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { RuleAction } from '$lib/components/BookCard.svelte';
	import { getLibrary, setRating } from '$lib/api/library.remote';
	import { putTasteRule, deleteTasteRule } from '$lib/api/taste.remote';

	const PAGE_SIZE = 20;

	const sp = $derived(page.url.searchParams);
	const pageNum = $derived(Math.max(1, Number(sp.get('page')) || 1));
	const search = $derived(sp.get('search') ?? '');
	const status = $derived((sp.get('status') ?? 'all') as 'all' | 'finished' | 'in-progress' | 'not-started');
	const taste = $derived((sp.get('taste') ?? 'all') as 'all' | 'included' | 'excluded');
	const offset = $derived((pageNum - 1) * PAGE_SIZE);

	function setQuery(changes: Record<string, string | undefined>) {
		const next = new URLSearchParams(page.url.searchParams);
		for (const [k, v] of Object.entries(changes)) {
			if (!v || v === 'all') next.delete(k);
			else next.set(k, v);
		}
		// Any filter/search change resets paging back to page 1.
		if (!('page' in changes)) next.delete('page');
		if (next.get('page') === '1') next.delete('page');
		const qs = next.toString();
		goto(qs ? `?${qs}` : '?', {
			keepFocus: true,
			noScroll: true,
			replaceState: !('page' in changes)
		});
	}

	const statuses = [
		{ value: 'all' as const, label: 'All' },
		{ value: 'finished' as const, label: 'Finished' },
		{ value: 'in-progress' as const, label: 'In Progress' },
		{ value: 'not-started' as const, label: 'Not Started' }
	];

	const tasteFilters = [
		{ value: 'all' as const, label: 'All' },
		{ value: 'included' as const, label: 'Included' },
		{ value: 'excluded' as const, label: 'Excluded' }
	];

	const libraryQuery = $derived(getLibrary({
		limit: PAGE_SIZE,
		offset,
		search: search || undefined,
		status: status !== 'all' ? status : undefined,
		taste: taste !== 'all' ? taste : undefined
	}));
	const data = $derived(await libraryQuery);

	async function rate(asin: string, rating: number | null) {
		await setRating({ asin, rating }).updates(libraryQuery);
	}

	async function applyRule(action: RuleAction) {
		const cmd = 'deleteId' in action ? deleteTasteRule(action.deleteId) : putTasteRule(action);
		await cmd.updates(libraryQuery);
	}
</script>

<h1 class="font-heading text-3xl font-bold text-foreground">Your Library</h1>
<p class="mt-2 text-muted-foreground">Browse, search, and filter your Audible collection.</p>

<!-- Search & Filters -->
<div class="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center">
	<div class="relative flex-1">
		<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
		<input
			type="text"
			placeholder="Search titles, authors, narrators…"
			value={search}
			oninput={(e) => setQuery({ search: e.currentTarget.value })}
			class="w-full rounded-lg border border-border bg-card py-2 pl-10 pr-4 text-sm text-card-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
		/>
	</div>

	<div class="flex gap-2">
		{#each statuses as s}
			<button
				onclick={() => setQuery({ status: s.value })}
				class="rounded-lg px-3 py-2 text-sm font-medium transition-colors {status === s.value ? 'bg-primary text-primary-foreground' : 'border border-border bg-card text-card-foreground hover:bg-muted'}"
			>
				{s.label}
			</button>
		{/each}
	</div>
</div>

<!-- Taste filter -->
<div class="mt-3 flex items-center gap-2">
	<span class="text-sm text-muted-foreground">Taste:</span>
	{#each tasteFilters as t}
		<button
			onclick={() => setQuery({ taste: t.value })}
			class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors {taste === t.value ? 'bg-primary text-primary-foreground' : 'border border-border bg-card text-card-foreground hover:bg-muted'}"
		>
			{t.label}
		</button>
	{/each}
</div>

<!-- Library Grid -->
<section class="mt-8">
	<svelte:boundary>
		{#if data.items.length === 0}
			<div class="rounded-xl border border-border bg-card p-10 text-center">
				<p class="font-heading text-lg text-card-foreground">No books found</p>
				<p class="mt-2 text-sm text-muted-foreground">
					{search ? 'Try a different search term or filter.' : 'Import your Audible library to get started.'}
				</p>
			</div>
		{:else}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each data.items as book (book.asin)}
					<BookCard
						{book}
						query={search}
						onRate={(r) => rate(book.asin, r)}
						onClearRating={() => rate(book.asin, null)}
						onRule={applyRule}
					/>
				{/each}
			</div>

			{@const totalPages = Math.ceil(data.total / PAGE_SIZE)}

			<Pagination
				currentPage={pageNum}
				{totalPages}
				onNavigate={(p) => setQuery({ page: String(p) })}
			/>
		{/if}

		{#snippet pending()}
			<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each { length: 6 } as _}
					<div class="animate-pulse rounded-xl border border-border bg-card p-5">
						<div class="flex gap-4">
							<div class="h-32 w-24 shrink-0 rounded-lg bg-muted"></div>
							<div class="flex-1">
								<div class="h-5 w-3/4 rounded bg-muted"></div>
								<div class="mt-3 h-4 w-1/2 rounded bg-muted"></div>
								<div class="mt-2 h-4 w-1/3 rounded bg-muted"></div>
							</div>
						</div>
						<div class="mt-3 flex gap-3">
							<div class="h-4 w-12 rounded bg-muted"></div>
							<div class="h-4 w-10 rounded bg-muted"></div>
						</div>
					</div>
				{/each}
			</div>
		{/snippet}

		{#snippet failed(error, reset)}
			<div class="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
				<p class="font-heading text-lg text-destructive">Failed to load library</p>
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
