<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft, RefreshCw } from 'lucide-svelte';
	import {
		getBookDetail,
		getBookEnrichment,
		getSimilarBooks,
		refreshBookDetails
	} from '$lib/api/library.remote';
	import type { AudibleReview } from '$lib/api/library.remote';
	import { putTasteRule, deleteTasteRule } from '$lib/api/taste.remote';

	const asin = $derived(page.params.asin ?? '');
	const bookQuery = $derived(getBookDetail(asin));
	const enrichmentQuery = $derived(getBookEnrichment(asin));
	const book = $derived(await bookQuery);
	const enrichment = $derived(await enrichmentQuery);
	const similar = $derived(await getSimilarBooks(asin));
	let imageFailed = $state(false);
	let descriptionExpanded = $state(false);
	let expandedReviews = $state<Set<number>>(new Set());
	let failedRelatedImages = $state<Set<string>>(new Set());
	let refreshing = $state(false);
	let refreshError = $state<string | null>(null);

	const descriptionHtml = $derived(enrichment.full_description ?? '');
	const hasLongDescription = $derived(descriptionHtml.length > 900);
	const tagList = $derived(
		enrichment.tags.length > 0 ? enrichment.tags : enrichment.categories.map((category) => category.name)
	);
	const ratingItems = $derived(
		[
			{ label: 'Overall', value: enrichment.ratings.overall },
			{ label: 'Performance', value: enrichment.ratings.performance },
			{ label: 'Story', value: enrichment.ratings.story }
		].filter((item) => item.value.avg != null || item.value.count != null)
	);

	const SCOPE_LABEL: Record<string, string> = {
		title: 'Title',
		author: 'Author',
		narrator: 'Narrator',
		category: 'Genre',
		series: 'Series'
	};

	type Rule = { id: number; mode: string } | null;
	type Target = { scope: string; id: number; name: string; rule: Rule };

	const tasteTargets = $derived.by<Target[]>(() => {
		const t: Target[] = [
			{ scope: 'title', id: book.book_id, name: book.title, rule: book.title_rule }
		];
		for (const a of book.authors) t.push({ scope: 'author', id: a.id, name: a.name, rule: a.rule });
		for (const n of book.narrators) t.push({ scope: 'narrator', id: n.id, name: n.name, rule: n.rule });
		for (const c of book.categories) t.push({ scope: 'category', id: c.id, name: c.name, rule: c.rule });
		for (const s of book.series) t.push({ scope: 'series', id: s.id, name: s.title, rule: s.rule });
		return t;
	});

	async function setRule(scope: string, id: number, mode: 'exclude' | 'include') {
		await putTasteRule({ scope, entity_id: id, mode }).updates(bookQuery);
	}
	async function clearRule(id: number) {
		await deleteTasteRule(id).updates(bookQuery);
	}

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

	function formatCount(value: number | null): string {
		if (value == null) return '';
		return new Intl.NumberFormat('en-US').format(value);
	}

	function formatDate(value: string | null): string {
		if (!value) return '';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return new Intl.DateTimeFormat('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		}).format(date);
	}

	function ratingWidth(avg: number | null): string {
		if (avg == null) return '0%';
		return `${Math.max(0, Math.min(100, (avg / 5) * 100))}%`;
	}

	function reviewPreview(review: AudibleReview, index: number): string {
		const body = review.body ?? '';
		if (expandedReviews.has(index) || body.length <= 520) return body;
		return `${body.slice(0, 520).trim()}...`;
	}

	function toggleReview(index: number) {
		const next = new Set(expandedReviews);
		if (next.has(index)) next.delete(index);
		else next.add(index);
		expandedReviews = next;
	}

	function relatedImageFailed(relatedAsin: string): boolean {
		return failedRelatedImages.has(relatedAsin);
	}

	function markRelatedImageFailed(relatedAsin: string) {
		failedRelatedImages = new Set(failedRelatedImages).add(relatedAsin);
	}

	async function refreshDetails() {
		refreshing = true;
		refreshError = null;
		try {
			await refreshBookDetails(asin).updates(enrichmentQuery);
		} catch (error) {
			refreshError = error instanceof Error ? error.message : 'Failed to refresh Audible details';
		} finally {
			refreshing = false;
		}
	}
</script>

<a href="/library" class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
	<ArrowLeft class="h-4 w-4" />
	Back to Library
</a>

<svelte:boundary>
	<article class="mt-6 space-y-6">
		<!-- Header -->
		<header class="flex flex-col gap-6 sm:flex-row">
			<div class="flex h-72 w-52 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/40 sm:h-80 sm:w-56">
				{#if book.image_url && !imageFailed}
					<img
						src={book.image_url}
						alt="Cover for {book.title}"
						onerror={() => { imageFailed = true; }}
						class="h-full w-full object-cover"
					/>
				{:else}
					<span class="px-4 text-center font-heading text-6xl text-muted-foreground/60">{book.title.slice(0, 1)}</span>
				{/if}
			</div>

			<div class="min-w-0 flex-1">
				<h1 class="font-heading text-3xl font-bold text-foreground">{book.title}</h1>
				{#if book.subtitle}
					<p class="mt-1 text-lg text-muted-foreground">{book.subtitle}</p>
				{/if}

				<!-- Metadata pills -->
				<div class="mt-5 flex flex-wrap gap-2 text-sm">
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
			</div>
		</header>

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
							<a href="/series/{s.id}" class="text-primary hover:underline">{s.title}</a>
							{#if s.sequence != null}
								<span class="text-muted-foreground">— Book {s.sequence}</span>
							{/if}
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		<!-- Taste rules -->
		<div class="rounded-xl border border-border bg-card p-5">
			<div class="flex items-center justify-between">
				<h2 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Taste</h2>
				{#if book.taste_excluded}
					<span class="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
						Excluded from taste
					</span>
				{/if}
			</div>
			<ul class="mt-3 divide-y divide-border">
				{#each tasteTargets as t (t.scope + ':' + t.id)}
					<li class="flex items-center justify-between gap-3 py-2 text-sm">
						<span class="min-w-0 truncate">
							<span class="text-muted-foreground">{SCOPE_LABEL[t.scope]}:</span>
							{t.name}
							{#if t.rule}
								<span class="ml-1 rounded px-1.5 py-0.5 text-xs font-medium {t.rule.mode === 'include' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}">
									{t.rule.mode}
								</span>
							{/if}
						</span>
						<span class="flex shrink-0 items-center gap-1">
							<button
								type="button"
								onclick={() => setRule(t.scope, t.id, 'exclude')}
								class="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-destructive"
							>Exclude</button>
							<button
								type="button"
								onclick={() => setRule(t.scope, t.id, 'include')}
								class="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-primary"
							>Include</button>
							{#if t.rule}
								<button
									type="button"
									onclick={() => clearRule(t.rule!.id)}
									class="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
								>Clear</button>
							{/if}
						</span>
					</li>
				{/each}
			</ul>
		</div>

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
			<div class="flex flex-col gap-6 sm:flex-row">
				<div class="h-72 w-52 rounded-lg bg-muted sm:h-80 sm:w-56"></div>
				<div class="flex-1">
					<div class="h-8 w-2/3 rounded bg-muted"></div>
					<div class="mt-3 h-5 w-1/3 rounded bg-muted"></div>
					<div class="mt-5 flex gap-2">
						{#each { length: 4 } as _}
							<div class="h-7 w-20 rounded-md bg-muted"></div>
						{/each}
					</div>
				</div>
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

<!-- Audible enrichment — independent boundary so the core detail page stays fast -->
<svelte:boundary>
	<section class="mt-10 space-y-6">
		<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
			<div>
				<h2 class="font-heading text-xl font-bold text-foreground">Audible Details</h2>
				{#if enrichment.enriched_at}
					<p class="mt-1 text-sm text-muted-foreground">Updated {formatDate(enrichment.enriched_at)}</p>
				{/if}
			</div>
			<button
				type="button"
				onclick={refreshDetails}
				disabled={refreshing}
				class="inline-flex w-fit items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-card-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
			>
				<RefreshCw class={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
				{refreshing ? 'Refreshing' : 'Refresh from Audible'}
			</button>
		</div>

		{#if enrichment.error || refreshError}
			<div class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-muted-foreground">
				<span class="font-medium text-destructive">Audible refresh failed.</span>{' '}
				{enrichment.error ?? refreshError}
			</div>
		{/if}

		{#if enrichment.full_description}
			<section class="rounded-xl border border-border bg-card p-5">
				<h3 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Description</h3>
				<div
					class={`mt-3 text-sm leading-relaxed text-card-foreground ${!descriptionExpanded && hasLongDescription ? 'max-h-48 overflow-hidden' : ''}`}
				>
					{@html descriptionHtml}
				</div>
				{#if hasLongDescription}
					<button
						type="button"
						onclick={() => { descriptionExpanded = !descriptionExpanded; }}
						class="mt-3 text-sm font-medium text-primary hover:underline"
					>
						{descriptionExpanded ? 'Show less' : 'Show more'}
					</button>
				{/if}
			</section>
		{/if}

		{#if ratingItems.length > 0}
			<section>
				<h3 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Ratings</h3>
				<div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
					{#each ratingItems as item}
						<div class="rounded-xl border border-border bg-card p-4">
							<div class="flex items-baseline justify-between gap-3">
								<span class="text-sm font-medium text-card-foreground">{item.label}</span>
								<span class="font-heading text-2xl font-bold text-foreground">
									{item.value.avg != null ? item.value.avg.toFixed(1) : '—'}
								</span>
							</div>
							<div class="mt-3 h-2 overflow-hidden rounded-full bg-muted">
								<div class="h-full rounded-full bg-primary" style="width: {ratingWidth(item.value.avg)}"></div>
							</div>
							{#if item.value.count != null}
								<p class="mt-2 text-xs text-muted-foreground">{formatCount(item.value.count)} ratings</p>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/if}

		{#if tagList.length > 0}
			<section>
				<h3 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Tags</h3>
				<div class="mt-3 flex flex-wrap gap-2">
					{#each tagList as tag}
						<span class="rounded-md border border-border bg-muted/50 px-2.5 py-1 text-sm text-muted-foreground">
							{tag}
						</span>
					{/each}
				</div>
			</section>
		{/if}

		{#if enrichment.editorial_reviews.length > 0}
			<section>
				<h3 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Critic Reviews</h3>
				<div class="mt-3 space-y-3">
					{#each enrichment.editorial_reviews as review}
						<article class="rounded-xl border border-border bg-card p-5 text-sm leading-relaxed text-card-foreground">
							{@html review}
						</article>
					{/each}
				</div>
			</section>
		{/if}

		{#if enrichment.user_reviews.length > 0}
			<section>
				<h3 class="text-sm font-medium uppercase tracking-wide text-muted-foreground">Most Helpful Reviews</h3>
				<div class="mt-3 space-y-4">
					{#each enrichment.user_reviews as review, index}
						<article class="rounded-xl border border-border bg-card p-5">
							<div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
								<div>
									<h4 class="font-heading text-base font-semibold text-card-foreground">
										{review.title ?? 'Audible review'}
									</h4>
									<p class="mt-1 text-sm text-muted-foreground">
										{review.author ?? 'Audible listener'}
										{#if review.date}
											<span> · {formatDate(review.date)}</span>
										{/if}
									</p>
								</div>
								{#if review.overall != null}
									<span class="inline-flex w-fit items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-sm font-medium text-primary">
										★ {review.overall.toFixed(1)}
									</span>
								{/if}
							</div>

							{#if review.body}
								<p class="mt-3 whitespace-pre-line text-sm leading-relaxed text-card-foreground">
									{reviewPreview(review, index)}
								</p>
								{#if review.body.length > 520}
									<button
										type="button"
										onclick={() => toggleReview(index)}
										class="mt-2 text-sm font-medium text-primary hover:underline"
									>
										{expandedReviews.has(index) ? 'Show less' : 'Show more'}
									</button>
								{/if}
							{/if}

							<div class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
								{#if review.performance != null}
									<span>Performance {review.performance.toFixed(1)}</span>
								{/if}
								{#if review.story != null}
									<span>Story {review.story.toFixed(1)}</span>
								{/if}
								{#if review.helpful_votes != null}
									<span>
										{formatCount(review.helpful_votes)}
										{review.helpful_votes === 1 ? 'person' : 'people'} found this helpful
									</span>
								{/if}
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/if}

		{#if enrichment.related.length > 0}
			<section>
				<h3 class="font-heading text-xl font-bold text-foreground">Listeners also enjoyed</h3>
				<div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
					{#each enrichment.related as item}
						<a
							href="/books/{item.asin}"
							class="group flex gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/30"
						>
							<div class="flex h-24 w-16 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted/40">
								{#if item.image_url && !relatedImageFailed(item.asin)}
									<img
										src={item.image_url}
										alt="Cover for {item.title}"
										loading="lazy"
										onerror={() => markRelatedImageFailed(item.asin)}
										class="h-full w-full object-cover"
									/>
								{:else}
									<span class="px-2 text-center font-heading text-2xl text-muted-foreground/60">
										{item.title.slice(0, 1)}
									</span>
								{/if}
							</div>
							<div class="min-w-0">
								<p class="font-heading text-base font-semibold leading-snug text-card-foreground group-hover:text-primary">
									{item.title}
								</p>
								{#if item.authors.length > 0}
									<p class="mt-1.5 text-sm text-muted-foreground">by {item.authors.join(', ')}</p>
								{/if}
							</div>
						</a>
					{/each}
				</div>
			</section>
		{/if}
	</section>

	{#snippet pending()}
		<section class="mt-10 space-y-6 animate-pulse">
			<div class="flex items-center justify-between">
				<div>
					<div class="h-6 w-40 rounded bg-muted"></div>
					<div class="mt-2 h-4 w-28 rounded bg-muted"></div>
				</div>
				<div class="h-9 w-40 rounded-lg bg-muted"></div>
			</div>
			<div class="rounded-xl border border-border bg-card p-5">
				<div class="h-4 w-24 rounded bg-muted"></div>
				<div class="mt-3 space-y-2">
					<div class="h-4 w-full rounded bg-muted"></div>
					<div class="h-4 w-11/12 rounded bg-muted"></div>
					<div class="h-4 w-4/5 rounded bg-muted"></div>
				</div>
			</div>
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
				{#each { length: 3 } as _}
					<div class="h-28 rounded-xl border border-border bg-card"></div>
				{/each}
			</div>
		</section>
	{/snippet}

	{#snippet failed(error, reset)}
		<div class="mt-10 rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-center">
			<p class="font-heading text-lg text-destructive">Failed to load Audible details</p>
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
