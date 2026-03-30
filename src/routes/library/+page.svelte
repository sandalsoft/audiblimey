<script lang="ts">
	import { Search } from 'lucide-svelte';
	import BookCard from '$lib/components/BookCard.svelte';
	import { getLibrary } from '$lib/api/library.remote';

	const PAGE_SIZE = 20;
	let offset = $state(0);
	let search = $state('');
	let status = $state<'all' | 'finished' | 'in-progress' | 'not-started'>('all');

	const statuses = [
		{ value: 'all' as const, label: 'All' },
		{ value: 'finished' as const, label: 'Finished' },
		{ value: 'in-progress' as const, label: 'In Progress' },
		{ value: 'not-started' as const, label: 'Not Started' }
	];

	const libraryQuery = $derived(getLibrary({
		limit: PAGE_SIZE,
		offset,
		search: search || undefined,
		status: status !== 'all' ? status : undefined
	}));
	const data = $derived(await libraryQuery);
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
			oninput={(e) => { search = e.currentTarget.value; offset = 0; }}
			class="w-full rounded-lg border border-border bg-card py-2 pl-10 pr-4 text-sm text-card-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
		/>
	</div>

	<div class="flex gap-2">
		{#each statuses as s}
			<button
				onclick={() => { status = s.value; offset = 0; }}
				class="rounded-lg px-3 py-2 text-sm font-medium transition-colors {status === s.value ? 'bg-primary text-primary-foreground' : 'border border-border bg-card text-card-foreground hover:bg-muted'}"
			>
				{s.label}
			</button>
		{/each}
	</div>
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
					<BookCard {book} />
				{/each}
			</div>

			{@const totalPages = Math.ceil(data.total / PAGE_SIZE)}
			{@const currentPage = Math.floor(offset / PAGE_SIZE) + 1}

			{#if totalPages > 1}
				<div class="mt-6 flex items-center justify-center gap-4">
					<button
						onclick={() => { offset = Math.max(0, offset - PAGE_SIZE); }}
						disabled={offset === 0}
						class="rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
					>
						Previous
					</button>
					<span class="text-sm text-muted-foreground">
						Page {currentPage} of {totalPages}
					</span>
					<button
						onclick={() => { offset = offset + PAGE_SIZE; }}
						disabled={currentPage >= totalPages}
						class="rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-card-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
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
						<div class="h-5 w-3/4 rounded bg-muted"></div>
						<div class="mt-3 h-4 w-1/2 rounded bg-muted"></div>
						<div class="mt-2 h-4 w-1/3 rounded bg-muted"></div>
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
