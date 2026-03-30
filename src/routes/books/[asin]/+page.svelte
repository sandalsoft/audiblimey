<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft } from 'lucide-svelte';
	import { getBookDetail, getSimilarBooks } from '$lib/api/library.remote';

	const asin = $derived(page.params.asin ?? '');
	const book = $derived(await getBookDetail(asin));
	const similar = $derived(await getSimilarBooks(asin));

	function formatRuntime(minutes: number | null): string {
		if (minutes == null) return '';
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		if (h === 0) return `${m}m`;
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}

	function formatPrice(amount: number | null, currency: string | null): string {
		if (amount == null) return '—';
		const sym = currency === 'USD' ? '$' : currency ?? '';
		return `${sym}${amount.toFixed(2)}`;
	}
</script>

<a href="/library" class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
	<ArrowLeft class="h-4 w-4" />
	Back to Library
</a>

<svelte:boundary>
	<article class="mt-6 space-y-6">
		<!-- Header -->
		<header>
			<h1 class="font-heading text-3xl font-bold text-foreground">{book.title}</h1>
			{#if book.subtitle}
				<p class="mt-1 text-lg text-muted-foreground">{book.subtitle}</p>
			{/if}
		</header>

		<!-- Metadata pills -->
		<div class="flex flex-wrap gap-2 text-sm">
			{#if book.runtime_minutes}
				<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-muted-foreground">
					{formatRuntime(book.runtime_minutes)}
				</span>
			{/if}
			{#if book.language}
				<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-muted-foreground">
					{book.language}
				</span>
			{/if}
			{#if book.content_type}
				<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-muted-foreground">
					{book.content_type}
				</span>
			{/if}
			{#if book.publisher}
				<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-muted-foreground">
					{book.publisher}
				</span>
			{/if}
			{#if book.release_date}
				<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-muted-foreground">
					{book.release_date}
				</span>
			{/if}
		</div>

		<!-- Authors -->
		{#if book.authors.length > 0}
			<div>
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Authors</h2>
				<div class="mt-1 flex flex-wrap gap-x-3 gap-y-1">
					{#each book.authors as author}
						<a href="/authors/{author.id}" class="text-primary hover:underline">{author.name}</a>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Narrators -->
		{#if book.narrators.length > 0}
			<div>
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Narrators</h2>
				<div class="mt-1 flex flex-wrap gap-x-3 gap-y-1">
					{#each book.narrators as narrator}
						<a href="/narrators/{narrator.id}" class="text-primary hover:underline">{narrator.name}</a>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Series -->
		{#if book.series.length > 0}
			<div>
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Series</h2>
				<ul class="mt-1 space-y-1">
					{#each book.series as s}
						<li class="text-sm text-card-foreground">
							{#if s.asin}
								<a href="/books/{s.asin}" class="text-primary hover:underline">{s.title}</a>
							{:else}
								{s.title}
							{/if}
							{#if s.sequence != null}
								<span class="text-muted-foreground">— Book {s.sequence}</span>
							{/if}
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		<!-- Summary -->
		{#if book.summary}
			<div class="rounded-xl border border-border bg-card p-5">
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Summary</h2>
				<p class="mt-2 text-sm leading-relaxed text-card-foreground">{book.summary}</p>
			</div>
		{/if}

		<!-- Pricing -->
		{#if book.pricing}
			<div class="rounded-xl border border-border bg-card p-5">
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Pricing</h2>
				<div class="mt-2 flex flex-wrap gap-6 text-sm">
					<div>
						<span class="text-muted-foreground">Member</span>
						<p class="font-medium text-card-foreground">{formatPrice(book.pricing.member_price, book.pricing.currency)}</p>
					</div>
					<div>
						<span class="text-muted-foreground">List</span>
						<p class="font-medium text-card-foreground">{formatPrice(book.pricing.list_price, book.pricing.currency)}</p>
					</div>
					<div>
						<span class="text-muted-foreground">Credits</span>
						<p class="font-medium text-card-foreground">{formatPrice(book.pricing.credit_price, book.pricing.currency)}</p>
					</div>
				</div>
			</div>
		{/if}

		<!-- Listening Progress -->
		{#if book.user_library}
			<div class="rounded-xl border border-border bg-card p-5">
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Your Progress</h2>
				<div class="mt-3 flex flex-wrap items-center gap-4 text-sm">
					{#if book.user_library.is_finished}
						<span class="rounded-md bg-primary/10 px-2.5 py-1 font-medium text-primary">Finished</span>
					{/if}
					{#if book.user_library.user_rating != null}
						<span class="flex items-center gap-1">
							<span class="text-primary">★</span>
							{book.user_library.user_rating}
						</span>
					{/if}
					{#if book.user_library.purchase_date}
						<span class="text-muted-foreground">Purchased {book.user_library.purchase_date}</span>
					{/if}
				</div>
				{#if book.user_library.percent_complete > 0 && !book.user_library.is_finished}
					<div class="mt-3">
						<div class="flex items-center justify-between text-xs text-muted-foreground">
							<span>Progress</span>
							<span>{Math.round(book.user_library.percent_complete)}%</span>
						</div>
						<div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
							<div
								class="h-full rounded-full bg-primary transition-all"
								style="width: {book.user_library.percent_complete}%"
							></div>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</article>

	{#snippet pending()}
		<div class="mt-6 space-y-6 animate-pulse">
			<div class="h-8 w-2/3 rounded bg-muted"></div>
			<div class="h-5 w-1/3 rounded bg-muted"></div>
			<div class="flex gap-2">
				{#each { length: 4 } as _}
					<div class="h-7 w-20 rounded-md bg-muted"></div>
				{/each}
			</div>
			<div class="h-4 w-1/4 rounded bg-muted"></div>
			<div class="rounded-xl border border-border bg-card p-5">
				<div class="h-4 w-16 rounded bg-muted"></div>
				<div class="mt-3 space-y-2">
					<div class="h-4 w-full rounded bg-muted"></div>
					<div class="h-4 w-5/6 rounded bg-muted"></div>
					<div class="h-4 w-3/4 rounded bg-muted"></div>
				</div>
			</div>
		</div>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="mt-6 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Failed to load book details</p>
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

<!-- Similar Books — independent boundary per K006 -->
<svelte:boundary>
	{#if similar.items.length > 0}
		<section class="mt-10">
			<h2 class="font-heading text-xl font-bold text-foreground">Similar Books</h2>
			<div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each similar.items as item}
					<a
						href="/books/{item.asin}"
						class="group rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/30"
					>
						<p class="font-heading text-base font-semibold leading-snug text-card-foreground group-hover:text-primary">
							{item.title}
						</p>
						{#if item.authors}
							<p class="mt-1.5 text-sm text-muted-foreground">by {item.authors}</p>
						{/if}
						<div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
							{#if item.runtime_hours != null}
								<span>{item.runtime_hours}h</span>
							{/if}
							{#if item.similarity_score != null}
								<span class="rounded-md bg-primary/10 px-2 py-0.5 font-medium text-primary">
									{Math.round(item.similarity_score * 100)}% match
								</span>
							{/if}
						</div>
					</a>
				{/each}
			</div>
		</section>
	{/if}

	{#snippet pending()}
		<section class="mt-10">
			<div class="h-6 w-36 rounded bg-muted animate-pulse"></div>
			<div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
				{#each { length: 3 } as _}
					<div class="rounded-xl border border-border bg-card p-4 animate-pulse">
						<div class="h-5 w-3/4 rounded bg-muted"></div>
						<div class="mt-2 h-4 w-1/2 rounded bg-muted"></div>
						<div class="mt-2 h-4 w-1/4 rounded bg-muted"></div>
					</div>
				{/each}
			</div>
		</section>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="mt-10 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Failed to load similar books</p>
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
